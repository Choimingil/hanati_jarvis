"""결재(Approval)·에러별 예외 처리 규칙·알림을 공유 SQLite에 영속화한다.

API·분석 Worker가 같은 `learned-script-state` 볼륨을 사용하므로 별도 컨테이너
없이 여러 프로세스가 같은 결재 대기열·예외 규칙·알림을 본다.

- 결재: 운영자가 Runbook의 "결재 요청"을 누르면 PENDING으로 저장되고, 관리자가
  admin 화면에서 승인해야 실제 조치가 실행된다.
- 예외 처리 규칙: 당장 해결이 어려운 오류를 자동으로 보류(ON_HOLD)하고, 발생할
  때마다(간격 제한) 알림을 남긴다.
- 알림: 화면 알림 목록에 표시하며 `NOTIFICATION_WEBHOOK_URL`이 있으면 같은 내용을
  JSON으로 전송한다.
"""

from contextlib import contextmanager
import json
import os
import sqlite3
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from operations.privacy import redact
from utils.time_utils import now_iso

HOLD_STATUS = "ON_HOLD"
# 시뮬레이션 검증용 기본 예외 규칙. 삭제하면 다시 생성하지 않는다.
# 장애는 기본적으로 보류하지 않는다. 예외 처리(자동 보류)는 관리자가 규칙을 등록한 오류에만 적용한다.
DEFAULT_RULES = []
# 이전 버전이 기본으로 등록하던 자동 보류 규칙. 기존 저장소에서도 비활성화한다.
RETIRED_DEFAULT_RULE_IDS = ("RULE-LEGACY-INTERFACE-TIMEOUT",)


def _parse(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


class WorkflowStore:
    def __init__(self, directory=None):
        base = Path(directory or os.getenv("LEARNED_SCRIPT_STATE_DIR", "learned-script-state"))
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / "incident-workflow.sqlite"
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS approvals (
                approval_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL,
                recommendation_id TEXT NOT NULL, action_id TEXT NOT NULL,
                script_id TEXT NOT NULL, error_code TEXT, service TEXT, environment TEXT,
                target TEXT, requested_by TEXT NOT NULL, requested_at TEXT NOT NULL,
                comment TEXT, status TEXT NOT NULL, decided_by TEXT, decided_at TEXT,
                decision_reason TEXT, execution_id TEXT, result_status TEXT, last_error TEXT
            );
            CREATE INDEX IF NOT EXISTS approvals_status ON approvals(status, requested_at);
            CREATE INDEX IF NOT EXISTS approvals_incident ON approvals(incident_id, requested_at);
            CREATE TABLE IF NOT EXISTS exception_rules (
                rule_id TEXT PRIMARY KEY, error_code TEXT NOT NULL, service TEXT,
                environment TEXT, reason TEXT NOT NULL, notify_interval_seconds INTEGER NOT NULL,
                created_by TEXT NOT NULL, created_at TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS notifications (
                notification_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, kind TEXT NOT NULL,
                incident_id TEXT, error_code TEXT, service TEXT, environment TEXT,
                rule_id TEXT, title TEXT NOT NULL, message TEXT NOT NULL,
                occurrence_count INTEGER, delivery TEXT, read INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS notifications_incident ON notifications(incident_id, kind, created_at);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
            """)
            if not db.execute("SELECT 1 FROM meta WHERE key='default_rules_seeded'").fetchone():
                for rule in DEFAULT_RULES:
                    db.execute(
                        "INSERT OR IGNORE INTO exception_rules VALUES (?,?,?,?,?,?,?,?,1)",
                        (rule["rule_id"], rule["error_code"], rule["service"], rule["environment"],
                         rule["reason"], rule["notify_interval_seconds"], rule["created_by"], now_iso()),
                    )
                db.execute("INSERT INTO meta VALUES ('default_rules_seeded', ?)", (now_iso(),))
            if not db.execute("SELECT 1 FROM meta WHERE key='default_rules_retired'").fetchone():
                db.execute(
                    "UPDATE exception_rules SET enabled=0 WHERE created_by='system' AND rule_id IN ("
                    + ",".join("?" * len(RETIRED_DEFAULT_RULE_IDS)) + ")", RETIRED_DEFAULT_RULE_IDS)
                db.execute("INSERT INTO meta VALUES ('default_rules_retired', ?)", (now_iso(),))

    @contextmanager
    def connect(self):
        """트랜잭션을 커밋(오류 시 롤백)하고 연결을 닫는다."""
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    # ---------------------------------------------------------------- 결재
    @staticmethod
    def _approval(row):
        if row is None:
            return None
        item = dict(row)
        item["target"] = json.loads(item["target"]) if item.get("target") else None
        return item

    def create_approval(self, request):
        """같은 장애에 진행 중인 결재가 있으면 새로 만들지 않고 기존 결재를 돌려준다."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            pending = db.execute(
                "SELECT * FROM approvals WHERE incident_id=? AND status IN ('PENDING','EXECUTING') "
                "ORDER BY requested_at DESC LIMIT 1", (request["incident_id"],),
            ).fetchone()
            if pending:
                return self._approval(pending), False
            approval_id = "APR-" + uuid.uuid4().hex[:16].upper()
            db.execute(
                "INSERT INTO approvals (approval_id, incident_id, recommendation_id, action_id, script_id, "
                "error_code, service, environment, target, requested_by, requested_at, comment, status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'PENDING')",
                (approval_id, request["incident_id"], request["recommendation_id"], request["action_id"],
                 request["script_id"], request.get("error_code"), request.get("service"),
                 request.get("environment"), json.dumps(request.get("target"), sort_keys=True),
                 redact(request["requested_by"]), now_iso(), redact(request.get("comment") or "")),
            )
            return self._approval(db.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()), True

    def expire_superseded(self, incident):
        """이전 분석(추천)에 걸린 결재 대기를 만료시킨다.

        장애 ID는 fingerprint로 결정되므로 같은 오류를 다시 발생시키면 같은 장애로 집계된다.
        새 발생으로 재분석되어 최신 추천이 바뀌었거나 장애가 처리 완료된 경우, 이전 회차에
        요청해 둔 결재 대기가 남아 있으면 새 조치 제안을 고르지 못하고 바로 결재 대기로
        보인다. 이런 결재는 실행하지 않고 EXPIRED로 종료한다. (실행 중인 EXECUTING은 건드리지 않는다.)
        """
        incident_id = (incident or {}).get("incident_id")
        if not incident_id:
            return 0
        recommendation_id = incident.get("latest_recommendation_id")
        if incident.get("status") == "RESOLVED":
            reason, clause, params = "incident resolved", "", []
        elif recommendation_id:
            reason, clause, params = "superseded by newer analysis", " AND recommendation_id<>?", [recommendation_id]
        else:
            return 0
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE approvals SET status='EXPIRED', decided_at=?, last_error=? "
                "WHERE incident_id=? AND status='PENDING'" + clause,
                [now_iso(), reason, incident_id] + params)
            return cursor.rowcount

    def get_approval(self, approval_id):
        with self.connect() as db:
            return self._approval(db.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone())

    def list_approvals(self, status=None, incident_id=None, limit=50):
        clauses, params = [], []
        if status:
            statuses = [status] if isinstance(status, str) else list(status)
            clauses.append("status IN (" + ",".join("?" * len(statuses)) + ")")
            params += statuses
        if incident_id:
            clauses.append("incident_id=?")
            params.append(incident_id)
        sql = "SELECT * FROM approvals" + (" WHERE " + " AND ".join(clauses) if clauses else "")
        sql += " ORDER BY requested_at DESC LIMIT ?"
        with self.connect() as db:
            return [self._approval(row) for row in db.execute(sql, params + [int(limit)])]

    def pending_incident_ids(self):
        with self.connect() as db:
            return {row[0] for row in db.execute(
                "SELECT incident_id FROM approvals WHERE status IN ('PENDING','EXECUTING')")}

    def claim_approval(self, approval_id, approver):
        """PENDING → EXECUTING. 동시에 두 관리자가 눌러도 한 번만 실행한다."""
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE approvals SET status='EXECUTING', decided_by=?, decided_at=? "
                "WHERE approval_id=? AND status='PENDING'", (redact(approver), now_iso(), approval_id))
            return cursor.rowcount == 1

    def finish_approval(self, approval_id, status, **fields):
        allowed = {"execution_id", "result_status", "last_error", "decision_reason", "decided_by", "decided_at"}
        changes = {k: v for k, v in fields.items() if k in allowed}
        changes["status"] = status
        assignments = ", ".join(k + "=?" for k in changes)
        with self.connect() as db:
            db.execute("UPDATE approvals SET " + assignments + " WHERE approval_id=?",
                       [redact(v) if isinstance(v, str) else v for v in changes.values()] + [approval_id])
        return self.get_approval(approval_id)

    def reject_approval(self, approval_id, approver, reason):
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE approvals SET status='REJECTED', decided_by=?, decided_at=?, decision_reason=? "
                "WHERE approval_id=? AND status='PENDING'",
                (redact(approver), now_iso(), redact(reason or ""), approval_id))
            changed = cursor.rowcount == 1
        return self.get_approval(approval_id), changed

    # ------------------------------------------------------ 예외 처리 규칙
    def list_rules(self, include_disabled=False):
        with self.connect() as db:
            sql = "SELECT * FROM exception_rules" + ("" if include_disabled else " WHERE enabled=1")
            return [dict(row) for row in db.execute(sql + " ORDER BY created_at, rule_id")]

    def create_rule(self, body):
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        code = str(body.get("error_code") or "").strip()
        reason = str(body.get("reason") or "").strip()
        operator = str(body.get("created_by") or "").strip()
        if not code or len(code) > 120 or not all(c.isalnum() or c in "_-." for c in code):
            raise ValueError("invalid error_code")
        if not reason or len(reason) > 1000:
            raise ValueError("invalid reason")
        if not operator or len(operator) > 200:
            raise ValueError("invalid created_by")
        interval = body.get("notify_interval_seconds", 300)
        if type(interval) is not int or not 0 <= interval <= 86400:
            raise ValueError("notify_interval_seconds must be 0..86400")
        scope = {}
        for field in ("service", "environment"):
            value = body.get(field)
            value = str(value).strip() if value not in (None, "") else None
            if value is not None and len(value) > 200:
                raise ValueError("invalid " + field)
            scope[field] = value
        with self.connect() as db:
            existing = db.execute(
                "SELECT * FROM exception_rules WHERE enabled=1 AND error_code=? AND service IS ? AND environment IS ?",
                (code, scope["service"], scope["environment"]),
            ).fetchone()
            if existing:
                return dict(existing), False
            rule_id = "RULE-" + uuid.uuid4().hex[:12].upper()
            db.execute("INSERT INTO exception_rules VALUES (?,?,?,?,?,?,?,?,1)",
                       (rule_id, code, scope["service"], scope["environment"], redact(reason),
                        interval, redact(operator), now_iso()))
            return dict(db.execute("SELECT * FROM exception_rules WHERE rule_id=?", (rule_id,)).fetchone()), True

    def delete_rule(self, rule_id):
        with self.connect() as db:
            return db.execute("UPDATE exception_rules SET enabled=0 WHERE rule_id=? AND enabled=1",
                              (rule_id,)).rowcount == 1

    def match_rule(self, incident):
        """가장 구체적인(서비스·환경이 지정된) 규칙을 우선 적용한다."""
        candidates = [
            rule for rule in self.list_rules()
            if rule["error_code"] == incident.get("error_code")
            and rule["service"] in (None, incident.get("service"))
            and rule["environment"] in (None, incident.get("environment"))
        ]
        candidates.sort(key=lambda r: (r["service"] is None, r["environment"] is None))
        return candidates[0] if candidates else None

    # ---------------------------------------------------------------- 알림
    def notify(self, kind, incident, title, message, rule=None, interval_seconds=0):
        """간격 안에 같은 장애·종류의 알림이 있으면 새로 만들지 않는다."""
        incident = incident or {}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if interval_seconds and incident.get("incident_id"):
                last = db.execute(
                    "SELECT created_at FROM notifications WHERE incident_id=? AND kind=? "
                    "ORDER BY created_at DESC LIMIT 1", (incident["incident_id"], kind)).fetchone()
                created = _parse(last[0]) if last else None
                if created and datetime.now(UTC) - created < timedelta(seconds=interval_seconds):
                    return None
            item = {
                "notification_id": "NTF-" + uuid.uuid4().hex[:16].upper(), "created_at": now_iso(),
                "kind": kind, "incident_id": incident.get("incident_id"),
                "error_code": incident.get("error_code"), "service": incident.get("service"),
                "environment": incident.get("environment"), "rule_id": (rule or {}).get("rule_id"),
                "title": redact(title), "message": redact(message),
                "occurrence_count": incident.get("occurrence_count"), "delivery": "ui", "read": 0,
            }
            db.execute("INSERT INTO notifications VALUES (:notification_id,:created_at,:kind,:incident_id,"
                       ":error_code,:service,:environment,:rule_id,:title,:message,:occurrence_count,"
                       ":delivery,:read)", item)
        item["delivery"] = self._deliver(item)
        if item["delivery"] != "ui":
            with self.connect() as db:
                db.execute("UPDATE notifications SET delivery=? WHERE notification_id=?",
                           (item["delivery"], item["notification_id"]))
        return item

    @staticmethod
    def _deliver(item):
        url = os.getenv("NOTIFICATION_WEBHOOK_URL", "").strip()
        if not url:
            return "ui"
        try:
            request = urllib.request.Request(url, data=json.dumps(item).encode(), method="POST",
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=3) as response:
                return "ui+webhook" if 200 <= response.status < 300 else "ui+webhook_failed"
        except Exception:
            return "ui+webhook_failed"

    def list_notifications(self, limit=30):
        with self.connect() as db:
            rows = [dict(row) for row in db.execute(
                "SELECT * FROM notifications ORDER BY created_at DESC LIMIT ?", (int(limit),))]
            unread = db.execute("SELECT COUNT(*) FROM notifications WHERE read=0").fetchone()[0]
        return rows, unread

    def mark_notifications_read(self):
        with self.connect() as db:
            return db.execute("UPDATE notifications SET read=1 WHERE read=0").rowcount

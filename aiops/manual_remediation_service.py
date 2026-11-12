"""Register an operator's externally performed action without executing input."""

import hashlib
import json
import posixpath
import re

from operations.privacy import redact
from operations.settings import manual_action_available
from utils.time_utils import now_iso


_ACCOUNT = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}")
_SHELL_PATH = re.compile(r"/[A-Za-z0-9_./+@%=,:-]{0,1023}")


def executed_shell(value, incident):
    """수동 조치 시 오류 발생 서버에서 호출한 셸 정보(서버·절대경로·실행 계정)를 검증한다.

    기록만 하며 이 값으로 어떤 명령도 실행하지 않는다.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("invalid executed_shell")
    host = value.get("host")
    path = value.get("path")
    account = value.get("account")
    if not isinstance(host, str) or not host.strip() or len(host) > 200:
        raise ValueError("invalid executed_shell host")
    hosts = [str(item) for item in incident.get("affected_hosts") or []]
    if hosts and host.strip() not in hosts:
        raise ValueError("executed_shell host must be an affected host")
    if not isinstance(path, str) or not _SHELL_PATH.fullmatch(path.strip()) or ".." in path.split("/"):
        raise ValueError("invalid executed_shell path")
    if not isinstance(account, str) or not _ACCOUNT.fullmatch(account.strip()):
        raise ValueError("invalid executed_shell account")
    return {"host": host.strip(), "path": posixpath.normpath(path.strip()), "account": account.strip()}


class ManualRemediationService:
    def __init__(self, repository):
        self.repository = repository

    def submit(self, body, attachment=None):
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        for field, limit in (("incident_id", 200), ("registration_id", 100), ("operator", 200), ("method", 8000)):
            value = body.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ValueError("invalid " + field)
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", body["registration_id"]):
            raise ValueError("invalid registration_id")
        version = body.get("incident_version")
        if type(version) is not int or version < 1:
            raise ValueError("incident_version must be an integer")
        if body.get("performed") is not True:
            raise ValueError("manual action must already be performed")
        if type(body.get("recovered")) is not bool:
            raise ValueError("recovered must be a boolean")
        incident = self.repository.get_operational_incident(body["incident_id"])
        if incident is None:
            raise LookupError("incident not found")
        from operations.learned_scripts import ScriptLibrary, metadata

        script = None
        if attachment is not None:
            # Validate eligibility before accepting attachment bytes into the library.
            if incident.get("version") != version and not any(
                item["registration_id"] == body["registration_id"] for item in incident.get("manual_actions", [])
            ):
                raise ValueError("incident changed; reload details before registering")
            script = ScriptLibrary().attach(incident, attachment[0], attachment[1])
        shell = executed_shell(body.get("executed_shell"), incident)
        content = redact({
            "operator": body["operator"].strip(), "method": body["method"].strip(),
            "performed": True, "recovered": body["recovered"],
            **({"attachment": metadata(script)} if script else {}),
        })
        if shell:
            # 경로·계정은 식별 정보라 마스킹하지 않고 그대로 기록한다 (형식은 위에서 제한).
            content["executed_shell"] = shell
        fingerprint = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
        history = list(incident.get("manual_actions") or [])
        existing = next((item for item in history if item["registration_id"] == body["registration_id"]), None)
        if existing:
            if existing["fingerprint"] != fingerprint:
                raise ValueError("registration id reused with different action")
            self._learn_confirmed(incident, history)
            return {"status": "registered", "duplicate": True, "manual_action": existing, "incident": incident}
        if incident.get("version") != version:
            raise ValueError("incident changed; reload details before registering")
        if not manual_action_available(incident):
            raise ValueError("manual registration unavailable for this incident")
        if len(history) >= 100:
            raise ValueError("manual registration limit reached")
        timestamp = now_iso()
        action = {
            "registration_id": body["registration_id"], "fingerprint": fingerprint,
            "registered_at": timestamp, "incident_id": incident["incident_id"],
            "service": incident.get("service"), "environment": incident.get("environment"),
            "affected_hosts": incident.get("affected_hosts", []), "error_code": incident.get("error_code"),
            **content, "recovery_confirmation": "operator_report" if content["recovered"] else "pending",
        }
        changes = {
            "manual_actions": history + [action], "last_manual_action_id": action["registration_id"],
            "status": "RESOLVED" if content["recovered"] else "MONITORING",
            "recovery_confirmation": "operator_report" if content["recovered"] else "pending_manual",
            "version": version + 1, "updated_at": timestamp,
            **({"recovered_at": timestamp} if content["recovered"] else {}),
        }
        if content["recovered"]:
            from operations.incident_history import with_resolution

            changes = with_resolution(incident, changes, manual_action=action)
        updated = self.repository.update_operational_incident(
            incident["incident_id"], changes, expected_version=version,
        )
        self._learn_confirmed(updated, history + [action])
        return {"status": "registered", "duplicate": False, "manual_action": action, "incident": updated}

    @staticmethod
    def _learn_confirmed(incident, history):
        from operations.learned_scripts import ScriptLibrary

        if incident.get("status") != "RESOLVED" or incident.get("recovery_confirmation") != "operator_report":
            return
        # A follow-up recovery confirmation can promote the preceding attachment.
        attachment = next((item["attachment"] for item in reversed(history) if item.get("attachment")), None)
        if attachment:
            ScriptLibrary().activate(attachment["script_id"], incident)

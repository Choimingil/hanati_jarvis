"""Bounded pipeline activity for the console, independent of analysis receipts."""

import json
from datetime import UTC, datetime, timedelta
from itertools import islice

from redis.exceptions import ResponseError

from operations.privacy import redact
from utils.time_utils import now_iso

ACTIVITY_KEYS = {source: "jarvis:activity:" + source for source in ("redis", "worker")}
MAX_EVENTS = 1000
RETENTION_SECONDS = 3600
EVENT_LABELS = {
    "queued": "접수", "retry_scheduled": "재시도 대기",
    "acknowledged": "처리 확인·큐 제거", "dead_lettered": "실패 보관",
    "missing_payload": "작업 본문 누락", "started": "Worker 기동",
    "processing": "분석 시작", "completed": "처리 완료",
    "retrying": "분석 실패·재시도", "failed": "최종 분석 실패",
    "loop_error": "Worker 루프 오류", "heartbeat_error": "생존 신호 오류",
    "heartbeat_recovered": "생존 신호 연결 복구",
}


def record_many(redis, source, events):
    """Observability writes must never turn an accepted/completed job into a failure."""
    try:
        pipe = redis.pipeline(transaction=False)
        for event in events:
            document = redact({"timestamp": now_iso(), **event})
            document = {
                key: value if value is None or isinstance(value, (bool, int, float))
                else str(value)[:400]
                for key, value in document.items()
            }
            pipe.xadd(
                ACTIVITY_KEYS[source], {"document": json.dumps(document)},
                maxlen=MAX_EVENTS, approximate=False,
            )
        pipe.expire(ACTIVITY_KEYS[source], RETENTION_SECONDS)
        pipe.execute()
    except Exception:
        # Redis outages remain visible through service status and Worker stdout.
        pass


def record(redis, source, event, **fields):
    record_many(redis, source, [{"event": event, **fields}])


def job_fields(job):
    payload = job.get("payload") or {}
    host = payload.get("host")
    if isinstance(host, dict):
        host = host.get("hostname")
    return {
        "job_id": job["job_id"], "kind": job["kind"],
        "attempt": job.get("attempts", 0), "host": host or "unknown",
        "service": payload.get("service") or payload.get("application") or "unknown",
        "message": payload.get("message", ""),
    }


def recent_events(redis, source, since=None):
    start = datetime.fromisoformat(since.replace("Z", "+00:00")) if since else (
        datetime.now(UTC) - timedelta(minutes=5)
    )
    if start.tzinfo is None:
        raise ValueError("timezone-aware activity timestamp required")
    entries = redis.xrevrange(
        ACTIVITY_KEYS[source], min=str(int(start.timestamp() * 1000)) + "-0", count=60
    )
    lines = []
    for _, fields in reversed(entries):
        event = json.loads(fields["document"])
        fields_text = " ".join(
            f"{key}={event[key]}" for key in (
                "job_id", "kind", "consumer", "host", "service", "attempt",
                "result_status", "incident_id", "elapsed_ms", "error", "retry_seconds",
            ) if event.get(key) is not None
        )
        label = EVENT_LABELS.get(event["event"], event["event"])
        message = str(event.get("message") or "")
        lines.append(
            f"{event['timestamp'][11:19]} [{label}] {fields_text}"
            + (" — " + message if message else "")
        )
    return lines


def redis_activity(redis, since=None):
    from operations.queue import GROUP, METRIC_STREAM, STREAM

    if not redis.ping():
        raise ConnectionError("Redis ping failed")
    lines = ["Redis PING 정상 / 확인 시각: " + now_iso()]
    for label, stream in (("로그", STREAM), ("메트릭", METRIC_STREAM)):
        length = redis.xlen(stream)
        try:
            group = next((item for item in redis.xinfo_groups(stream)
                          if item["name"] == GROUP), None)
        except ResponseError:
            group = None
        lines.append(
            f"{label} 스트림: 잔여 {length}건 / "
            + (f"처리 확인 대기 {group['pending']}건 / 미전달 {group.get('lag', '?')}건"
               if group else "Worker 소비 그룹 미생성")
        )
    lines.append(f"최종 실패 보관: {redis.xlen('jarvis:dead-letter')}건")
    events = recent_events(redis, "redis", since)
    return lines + (events or ["조회 구간에 Redis 큐 이벤트가 없습니다."])


def worker_activity(redis, since=None):
    workers = list(islice(redis.scan_iter("jarvis:worker:*", count=100), 100))
    lines = [f"생존 신호가 유효한 Worker: {len(workers)}개 / 확인 시각: {now_iso()}"]
    for key in sorted(workers):
        value = redis.get(key)
        if value:
            stamp = datetime.fromtimestamp(float(value), UTC).isoformat()
            lines.append(f"{key.removeprefix('jarvis:worker:')} / 마지막 생존 신호: {stamp}")
    events = recent_events(redis, "worker", since)
    return lines + (events or ["조회 구간에 Worker 처리 이벤트가 없습니다."])

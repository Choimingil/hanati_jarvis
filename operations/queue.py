"""Redis Streams queue: persisted receipt, explicit acknowledgement and dead letters."""

import json
import time
import uuid
import threading
import hashlib
from redis.exceptions import ResponseError
from operations.privacy import redact
from operations.settings import JOB_RETENTION_SECONDS

STREAM = "jarvis:analysis"
METRIC_STREAM = "jarvis:metrics-analysis"
GROUP = "analysis-workers"


class AnalysisQueue:
    def __init__(self, redis):
        self.redis = redis

    def ensure_group(self):
        for stream in (STREAM, METRIC_STREAM):
            try:
                self.redis.xgroup_create(stream, GROUP, id="0", mkstream=True)
            except ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise

    def enqueue(self, kind, payload):
        return self.enqueue_many(kind, [payload])[0]

    def enqueue_many(self, kind, payloads):
        pipe = self.redis.pipeline(transaction=True)
        job_ids = []
        for payload in payloads:
            job_id = uuid.uuid4().hex
            job_ids.append(job_id)
            document = {
                "job_id": job_id,
                "kind": kind,
                "payload": redact(payload),
                "status": "queued",
                "attempts": 0,
                "created_at": time.time(),
            }
            pipe.set("jarvis:job:" + job_id, json.dumps(document))
            pipe.xadd(
                METRIC_STREAM if kind == "metrics" else STREAM, {"job_id": job_id}
            )
        pipe.hset("jarvis:collection", mapping={"last_" + kind: str(time.time())})
        pipe.execute()
        return job_ids

    def get(self, job_id):
        value = self.redis.get("jarvis:job:" + job_id)
        if not value:
            return None
        document = json.loads(value)
        document.pop("payload", None)
        return document

    def process(self, message_id, fields, handler, consumer="test", stream=STREAM):

        job_id = fields["job_id"]
        key = "jarvis:job:" + job_id
        raw = self.redis.get(key)
        if not raw:
            # Missing payload is a failure, never silently a successful job.
            pipe = self.redis.pipeline()
            pipe.xadd(
                "jarvis:dead-letter", {"job_id": job_id, "reason": "missing_payload"}
            )
            pipe.xack(stream, GROUP, message_id)
            pipe.xdel(stream, message_id)
            pipe.execute()
            return
        job = json.loads(raw)
        if job["status"] in {"completed", "failed"}:
            self.redis.xack(stream, GROUP, message_id)
            self.redis.xdel(stream, message_id)
            return
        if job.get("next_attempt_at", 0) > time.time():
            return
        if job["kind"] == "logs":
            from aiops.operational_incident_service import build_fingerprint
            from error_detector import detect_error_code
            from log_normalizer import normalize_log

            log = normalize_log(job["payload"])
            scope = build_fingerprint(log, detect_error_code(log["message"]))
        else:
            scope = "metrics:" + str(job["payload"].get("host", {}).get("hostname"))
        lock_key = hashlib.sha256(scope.encode()).hexdigest()
        lock = self.redis.lock(
            "jarvis:analysis-lock:" + lock_key,
            timeout=300,
            blocking_timeout=0,
            thread_local=False,
        )
        if not lock.acquire(blocking=False):
            return
        # Re-read after acquiring the shared incident/host lock to avoid replaying
        # a job which another worker finished between receipt and acquisition.
        job = json.loads(self.redis.get(key))
        if job["status"] in {"completed", "failed"}:
            self.redis.xack(stream, GROUP, message_id)
            self.redis.xdel(stream, message_id)
            lock.release()
            return
        stop = threading.Event()

        def renew():
            while not stop.wait(10):
                try:
                    lock.extend(300, replace_ttl=True)
                    self.redis.set("jarvis:worker:" + consumer, str(time.time()), ex=30)
                except Exception:
                    return

        heartbeat = threading.Thread(target=renew, daemon=True)
        heartbeat.start()
        try:
            job.update(status="processing", attempts=job["attempts"] + 1)
            self.redis.set(key, json.dumps(job))
            try:
                result = handler(job["kind"], job["payload"], job_id)
                job.update(
                    status="completed", result=redact(result), finished_at=time.time()
                )
            except Exception as exc:
                job.update(
                    status="retrying" if job["attempts"] < 3 else "failed",
                    error=type(exc).__name__,
                    finished_at=time.time(),
                )
            if job["status"] == "retrying":
                job["next_attempt_at"] = time.time() + min(
                    60, 5 * 2 ** (job["attempts"] - 1)
                )
                self.redis.set(key, json.dumps(job))
                return  # pending message is reclaimed after the visibility interval
            pipe = self.redis.pipeline(transaction=True)
            # Remove payload when terminal; receipt remains available for seven days.
            job.pop("payload", None)
            pipe.set(key, json.dumps(job), ex=JOB_RETENTION_SECONDS)
            if job["status"] == "failed":
                pipe.xadd(
                    "jarvis:dead-letter", {"job_id": job_id, "error": job["error"]}
                )
            pipe.hset(
                "jarvis:collection",
                mapping={
                    "last_analysis": str(time.time()),
                    "analysis_status": job["status"],
                },
            )
            pipe.xack(stream, GROUP, message_id)
            pipe.xdel(stream, message_id)
            pipe.execute()
        finally:
            stop.set()
            heartbeat.join(timeout=1)
            if lock.owned():
                lock.release()

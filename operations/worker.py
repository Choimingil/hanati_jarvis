import os
import socket
import time
import threading
from operations.redis_store import client
from operations.queue import AnalysisQueue, STREAM, METRIC_STREAM, GROUP
from operations.activity import record


def handle(kind, payload, job_id):
    from dependencies import log_processor, metric_analysis_service, repository

    if kind == "logs":
        return log_processor.process(payload, ingestion_id=job_id)
    if kind == "metrics":
        from datetime import datetime, UTC
        from operations.settings import FRESHNESS_SECONDS

        age = (
            datetime.now(UTC)
            - datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))
        ).total_seconds()
        repository.save_metric({**payload, "ingestion_id": job_id})
        if age > FRESHNESS_SECONDS:
            return {
                "status": "stale_data",
                "reason": "stored for history; fresh data required for current diagnosis",
            }
        return metric_analysis_service.analyze({**payload, "ingestion_id": job_id})
    raise ValueError("unknown job kind")


def start_heartbeat(redis, consumer, interval=10, ttl=30):
    """Keep worker liveness fresh while embedding or LLM analysis is blocking."""
    stopped = threading.Event()
    key = "jarvis:worker:" + consumer

    def beat():
        last_error = None
        while not stopped.is_set():
            try:
                redis.set(key, str(time.time()), ex=ttl)
                if last_error:
                    record(redis, "worker", "heartbeat_recovered", consumer=consumer, error=last_error)
                    last_error = None
            except Exception as exc:
                last_error = type(exc).__name__
                record(redis, "worker", "heartbeat_error", consumer=consumer, error=last_error)
                print("worker heartbeat error: " + type(exc).__name__, flush=True)
            stopped.wait(interval)

    thread = threading.Thread(target=beat, name="worker-heartbeat", daemon=True)
    thread.start()
    return stopped, thread


def main():
    redis = client()
    queue = AnalysisQueue(redis)
    queue.ensure_group()
    from operations.maintenance import start_maintenance

    start_maintenance(redis)
    consumer = socket.gethostname() + "-" + str(os.getpid())
    start_heartbeat(redis, consumer)
    record(redis, "worker", "started", consumer=consumer)
    while True:
        try:
            # At most one metric and one log per cycle; legacy mixed jobs remain consumable.
            work = []
            for stream in (METRIC_STREAM, STREAM):
                reclaimed = redis.xautoclaim(
                    stream, GROUP, consumer, 5000, "0-0", count=1
                )[1]
                if reclaimed:
                    work.extend(
                        (stream, identifier, fields) for identifier, fields in reclaimed
                    )
                else:
                    batches = redis.xreadgroup(GROUP, consumer, {stream: ">"}, count=1)
                    if batches:
                        work.extend(
                            (stream, identifier, fields)
                            for identifier, fields in batches[0][1]
                        )
            for stream, message_id, fields in work:
                queue.process(message_id, fields, handle, consumer, stream=stream)
            if not work:
                time.sleep(0.5)
        except Exception as exc:
            record(redis, "worker", "loop_error", consumer=consumer, error=type(exc).__name__)
            print("analysis worker error: " + type(exc).__name__, flush=True)
            time.sleep(2)


if __name__ == "__main__":
    main()

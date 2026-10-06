import os
import socket
import time
from operations.redis_store import client
from operations.queue import AnalysisQueue, STREAM, GROUP


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


def main():
    redis = client()
    queue = AnalysisQueue(redis)
    queue.ensure_group()
    consumer = socket.gethostname() + "-" + str(os.getpid())
    while True:
        try:
            redis.set("jarvis:worker:" + consumer, str(time.time()), ex=30)
            reclaimed = redis.xautoclaim(
                STREAM, GROUP, consumer, 360000, "0-0", count=1
            )
            messages = reclaimed[1]
            if not messages:
                batches = redis.xreadgroup(
                    GROUP, consumer, {STREAM: ">"}, count=1, block=1000
                )
                messages = batches[0][1] if batches else []
            for message_id, fields in messages:
                queue.process(message_id, fields, handle, consumer)
        except Exception as exc:
            print("analysis worker error: " + type(exc).__name__, flush=True)
            time.sleep(2)


if __name__ == "__main__":
    main()

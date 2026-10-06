"""Single maintenance thread: metric retention and durable old stream archival."""

import threading
import time
from config import METRICS_RETENTION_ENABLED, METRICS_RETENTION_INTERVAL_SECONDS
from elastic.metric_retention import delete_expired_metrics
from elastic.client import get_client
from operations.privacy import redact


def archive_stream(redis, es, stream, index, days, now=None):
    cutoff = int(((time.time() if now is None else now) - days * 86400) * 1000)
    if cutoff <= 0:
        return 0
    entries = redis.xrange(stream, max=str(cutoff) + "-0", count=100)
    for identifier, fields in entries:
        es.index(
            index=index,
            id=identifier,
            document=redact(
                {"stream_id": identifier, "archived_at": time.time(), "fields": fields}
            ),
        )
        redis.xdel(stream, identifier)
    return len(entries)


def start_maintenance(redis):
    stop = threading.Event()

    def run():
        while not stop.is_set():
            try:
                lock = redis.lock(
                    "jarvis:maintenance-lock",
                    timeout=300,
                    blocking_timeout=0,
                    thread_local=False,
                )
                if lock.acquire(blocking=False):
                    try:
                        es = get_client()
                        if METRICS_RETENTION_ENABLED and not redis.exists(
                            "jarvis:metric-retention-due"
                        ):
                            delete_expired_metrics(es)
                            redis.set(
                                "jarvis:metric-retention-due",
                                "completed",
                                ex=max(60, METRICS_RETENTION_INTERVAL_SECONDS),
                            )
                        archive_stream(
                            redis, es, "jarvis:dead-letter", "jarvis-dead-letters", 30
                        )
                        archive_stream(redis, es, "jarvis:audit", "jarvis-audit", 90)
                    finally:
                        if lock.owned():
                            lock.release()
            except Exception as exc:
                print("maintenance error: " + type(exc).__name__, flush=True)
            stop.wait(60)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return stop

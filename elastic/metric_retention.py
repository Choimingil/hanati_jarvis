"""Elasticsearch 시스템 메트릭 보존 작업.

서비스 시작 시 한 번 실행하고 이후 기본 24시간마다 14일 이전 원본
메트릭을 삭제한다. 삭제 대상은 ELASTIC_METRICS_INDEX 하나로 제한한다.
"""

import argparse
import signal
import threading
from typing import Any

from config import (
    ELASTIC_METRICS_INDEX,
    METRICS_RETENTION_DAYS,
    METRICS_RETENTION_INTERVAL_SECONDS,
)
from elastic.client import get_client


def delete_expired_metrics(
    client: Any,
    retention_days: int = METRICS_RETENTION_DAYS,
) -> dict[str, Any]:
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1")

    return client.delete_by_query(
        index=ELASTIC_METRICS_INDEX,
        query={
            "range": {
                "timestamp": {
                    "lt": f"now-{retention_days}d",
                }
            }
        },
        conflicts="proceed",
        refresh=False,
        wait_for_completion=True,
        ignore_unavailable=True,
    )


def run_forever(
    interval_seconds: int = METRICS_RETENTION_INTERVAL_SECONDS,
) -> None:
    if interval_seconds < 1:
        raise ValueError("interval_seconds must be at least 1")

    stop_event = threading.Event()

    def stop(_signum, _frame) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    client = get_client()
    while not stop_event.is_set():
        try:
            result = delete_expired_metrics(client)
            print(
                "[metrics-retention] "
                f"deleted={result.get('deleted', 0)} "
                f"retention_days={METRICS_RETENTION_DAYS}",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[metrics-retention] cleanup failed: {exc}",
                flush=True,
            )

        stop_event.wait(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--once",
        action="store_true",
        help="보존 작업을 한 번만 실행",
    )
    args = parser.parse_args()

    if args.once:
        result = delete_expired_metrics(get_client())
        print(
            "[metrics-retention] "
            f"deleted={result.get('deleted', 0)} "
            f"retention_days={METRICS_RETENTION_DAYS}",
            flush=True,
        )
        return

    run_forever()


if __name__ == "__main__":
    main()

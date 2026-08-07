from __future__ import annotations

import argparse
import json
import time
from urllib import error, request

from collector.system_collector import SystemCollector
from config import (
    METRICS_API_URL,
    METRICS_COLLECT_INTERVAL_SECONDS,
    METRICS_PROCESS_LIMIT,
)


def send_snapshot(url: str, snapshot: dict) -> None:
    payload = json.dumps(snapshot).encode("utf-8")
    http_request = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(http_request, timeout=10) as response:
        if response.status >= 300:
            raise RuntimeError(f"metrics API returned {response.status}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Host metrics collector")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--url", default=METRICS_API_URL)
    parser.add_argument(
        "--interval", type=int,
        default=METRICS_COLLECT_INTERVAL_SECONDS,
    )
    args = parser.parse_args()
    collector = SystemCollector(METRICS_PROCESS_LIMIT)

    while True:
        try:
            send_snapshot(args.url, collector.collect())
            print("system metrics snapshot sent", flush=True)
        except (error.URLError, OSError, RuntimeError) as exc:
            print(f"system metrics send failed: {exc}", flush=True)
            if args.once:
                raise SystemExit(1) from exc

        if args.once:
            break
        time.sleep(max(1, args.interval))


if __name__ == "__main__":
    main()

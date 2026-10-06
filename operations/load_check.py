"""Explicit bounded synthetic ERROR benchmark in a non-production identity."""

import argparse
import concurrent.futures
import json
import time
import uuid
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts", type=int, nargs="+", default=[10, 50, 100])
    parser.add_argument("--deadline-seconds", type=int, default=60)
    args = parser.parse_args()
    if (
        any(n < 1 or n > 100 for n in args.counts)
        or len(args.counts) > 3
        or not 5 <= args.deadline_seconds <= 120
    ):
        parser.error("at most 3 batches of 1..100; deadline 5..120 seconds")
    reports = []
    with httpx.Client(
        base_url="http://aiops:8080", timeout=5, trust_env=False
    ) as client:
        for count in args.counts:
            stamp = time.monotonic()
            run = uuid.uuid4().hex
            logs = [
                {
                    "level": "ERROR",
                    "message": "OutOfMemoryError validation " + run,
                    "host": "validation-only",
                    "service": "jarvis-load-validation",
                    "environment": "validation",
                }
                for _ in range(count)
            ]
            response = client.post("/api/v1/logs", json=logs)
            if response.status_code != 202:
                reports.append(
                    {
                        "count": count,
                        "passed": False,
                        "status": "ingestion_failed",
                        "http_status": response.status_code,
                    }
                )
                break
            identifiers = response.json()["job_ids"]
            accepted = time.monotonic() - stamp
            pending = set(identifiers)
            receipts = {}
            deadline = stamp + args.deadline_seconds
            while pending and time.monotonic() < deadline:
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:

                    def poll(identifier):
                        try:
                            r = client.get("/api/v1/analysis/jobs/" + identifier)
                            r.raise_for_status()
                            return identifier, r.json()
                        except Exception as exc:
                            return identifier, {
                                "status": "poll_error",
                                "error": type(exc).__name__,
                            }

                    for identifier, receipt in pool.map(poll, list(pending)):
                        if receipt.get("status") in {"completed", "failed"}:
                            receipts[identifier] = receipt
                            pending.remove(identifier)
                if pending:
                    time.sleep(0.5)
            elapsed = time.monotonic() - stamp
            failed = sum(r["status"] == "failed" for r in receipts.values())
            reports.append(
                {
                    "count": count,
                    "passed": not pending and not failed,
                    "accepted_seconds": round(accepted, 3),
                    "elapsed_seconds": round(elapsed, 3),
                    "completed": len(receipts) - failed,
                    "failed": failed,
                    "pending": len(pending),
                    "completed_per_second": round(
                        (len(receipts) - failed) / elapsed, 3
                    ),
                    "result_types": [
                        r.get("result", {}).get("status") for r in receipts.values()
                    ],
                }
            )
            if pending or failed:
                break
    print(
        json.dumps(
            {
                "reports": reports,
                "scope": "synthetic validation ERRORs; duplicate aggregation benchmark, not unique-error capacity",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    raise SystemExit(0 if reports and all(r["passed"] for r in reports) else 1)


if __name__ == "__main__":
    main()

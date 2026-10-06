"""Bounded live checks using INFO sentinels; no ERROR, transaction or remediation."""

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import time
import uuid
import httpx


def wait_for(callback, seconds):
    deadline = time.monotonic() + seconds
    while True:
        result = callback()
        if result:
            return result
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait-seconds", type=int, default=20)
    args = parser.parse_args()
    if not 5 <= args.wait_seconds <= 30:
        parser.error("wait must be 5..30 seconds per path")
    checks = []
    with httpx.Client(timeout=3, trust_env=False, follow_redirects=False) as http:

        def check(name, callback):
            try:
                checks.append({"name": name, "passed": bool(callback())})
            except Exception as exc:
                checks.append(
                    {"name": name, "passed": False, "reason": type(exc).__name__}
                )

        def stored(marker):
            r = http.post(
                "http://elasticsearch:9200/application-logs/_search",
                json={"query": {"match_phrase": {"message": marker}}, "size": 1},
            )
            r.raise_for_status()
            return bool(r.json().get("hits", {}).get("hits", []))

        def direct():
            marker = "jarvisintegration" + uuid.uuid4().hex
            r = http.post(
                "http://aiops:8080/api/v1/logs",
                json={
                    "level": "INFO",
                    "message": marker,
                    "host": "validation-only",
                    "service": "jarvis-integration-validation",
                    "environment": "validation",
                },
            )
            r.raise_for_status()
            job = r.json()["job_ids"][0]

            def completed():
                r = http.get("http://aiops:8080/api/v1/analysis/jobs/" + job)
                r.raise_for_status()
                return r.json().get("status") == "completed"

            return bool(
                wait_for(completed, args.wait_seconds)
                and wait_for(lambda: stored(marker), args.wait_seconds)
            )

        check("api_to_redis_worker_elasticsearch", direct)

        def fluent():
            marker = "jarvisfluentintegration" + uuid.uuid4().hex
            path = Path("/workspace/fluentbit/application.log")
            if not path.is_file():
                raise ValueError("shared log file absent; start log-generator first")
            # Wait for tail discovery before appending with Read_From_Head Off.
            time.sleep(6)
            with path.open("a") as file:
                file.write(
                    json.dumps(
                        {
                            "timestamp": datetime.now(UTC).strftime(
                                "%Y-%m-%dT%H:%M:%S%z"
                            ),
                            "level": "INFO",
                            "message": marker,
                            "host": "validation-only",
                            "service": "jarvis-integration-validation",
                            "environment": "validation",
                        }
                    )
                    + "\n"
                )
            return wait_for(lambda: stored(marker), args.wait_seconds)

        check("shared_log_to_fluent_bit_api_worker_elasticsearch", fluent)

        def qdrant():
            base = "http://qdrant:6333/collections/incident_cases"
            r = http.get(base)
            r.raise_for_status()
            if r.json()["result"]["points_count"] < 1:
                return False
            r = http.post(
                base + "/points/scroll",
                json={"limit": 1, "with_vector": True, "with_payload": True},
            )
            r.raise_for_status()
            point = r.json()["result"]["points"][0]
            vector = point["vector"]
            if not isinstance(vector, list) or len(vector) != 384:
                return False
            r = http.post(
                base + "/points/query",
                json={
                    "query": vector,
                    "limit": 1,
                    "with_payload": True,
                    "filter": {
                        "must": [
                            {
                                "key": "error_code",
                                "match": {"value": point["payload"]["error_code"]},
                            }
                        ]
                    },
                },
            )
            r.raise_for_status()
            return bool(r.json()["result"]["points"])

        check("qdrant_collection_vector_and_filtered_search", qdrant)

        def collector():
            r = http.get("http://aiops:8080/api/v1/operations/status")
            r.raise_for_status()
            hosts = r.json().get("hosts", [])
            return any(h.get("status") == "fresh" for h in hosts)

        check("recent_metric_ingestion", lambda: wait_for(collector, args.wait_seconds))

        def llm():
            r = http.get("http://llm-agent:8000/health")
            r.raise_for_status()
            return r.json().get("status") == "ok"

        check("llm_agent_network_and_health", llm)
    passed = all(c["passed"] for c in checks)
    print(
        json.dumps(
            {
                "passed": passed,
                "checks": checks,
                "limits": "INFO end-to-end and stored-vector search; external LLM generation, embedding inference, Agent execution and real business probes are not tested",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()

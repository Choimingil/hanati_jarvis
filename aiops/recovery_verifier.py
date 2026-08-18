from __future__ import annotations

from typing import Any

from aiops.feature_extractor import MetricFeatureExtractor


class RecoveryVerifier:
    def __init__(self) -> None:
        self.extractor = MetricFeatureExtractor()

    def verify(
        self,
        incident: dict[str, Any],
        after_snapshots: list[dict[str, Any]],
    ) -> dict[str, Any]:
        before = incident.get("metric_features", {})
        after = self.extractor.extract(after_snapshots)
        code = incident.get("error_code")
        checks: list[dict[str, Any]] = []

        def check(name: str, passed: bool, before_value, after_value):
            checks.append({
                "name": name,
                "passed": passed,
                "before": before_value,
                "after": after_value,
            })

        if code == "MEMORY_LEAK":
            check(
                "memory_percent_decreased",
                after.get("memory_latest", 100)
                <= before.get("memory_latest", 0) - 5,
                before.get("memory_latest"),
                after.get("memory_latest"),
            )
        elif code == "DISK_FULL":
            check(
                "disk_percent_decreased",
                after.get("disk_latest", 100)
                < before.get("disk_latest", 0),
                before.get("disk_latest"),
                after.get("disk_latest"),
            )
        elif code == "DB_CONNECTION_FAILURE":
            check(
                "close_wait_decreased",
                after.get("close_wait_latest", 10**9)
                < before.get("close_wait_latest", 0),
                before.get("close_wait_latest"),
                after.get("close_wait_latest"),
            )
        else:
            check(
                "network_errors_stable",
                after.get("network_error_growth", 1) <= 0,
                before.get("network_error_growth"),
                after.get("network_error_growth"),
            )

        return {
            "incident_id": incident.get("incident_id"),
            "recovered": bool(checks) and all(
                item["passed"] for item in checks
            ),
            "checks": checks,
        }

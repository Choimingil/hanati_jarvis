from __future__ import annotations

from typing import Any


class ResourceContextLoader:
    def __init__(self, repository, feature_extractor) -> None:
        self.repository = repository
        self.feature_extractor = feature_extractor

    def load(self, log: dict[str, Any]) -> dict[str, Any]:
        host = log.get("host", "unknown")
        snapshots = self.repository.recent_metrics(host, minutes=15)
        try:
            related_logs = self.repository.recent_error_logs(
                host, minutes=10
            )
        except Exception:
            related_logs = []
        return {
            "host": host,
            "log_timestamp": log.get("timestamp"),
            "snapshot_count": len(snapshots),
            "features": self.feature_extractor.extract(snapshots),
            "related_logs": related_logs,
        }

from __future__ import annotations

from typing import Any
from datetime import datetime, UTC
from operations.settings import FRESHNESS_SECONDS


class ResourceContextLoader:
    def __init__(self, repository, feature_extractor) -> None:
        self.repository = repository
        self.feature_extractor = feature_extractor

    def load(self, log: dict[str, Any]) -> dict[str, Any]:
        host = log.get("host", "unknown")
        snapshots = self.repository.recent_metrics(host, minutes=15)
        fresh = []
        for snapshot in snapshots:
            try:
                stamp = datetime.fromisoformat(snapshot["timestamp"].replace("Z", "+00:00"))
                if 0 <= (datetime.now(UTC)-stamp).total_seconds() <= FRESHNESS_SECONDS:
                    fresh.append(snapshot)
            except (ValueError, TypeError, KeyError):
                continue
        # Retain the trend only if its newest sample is fresh; otherwise no diagnosis.
        data_stale = bool(snapshots) and not fresh
        if data_stale:
            snapshots = []
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
            "data_stale": data_stale,
            "features": self.feature_extractor.extract(snapshots),
            "related_logs": related_logs,
        }

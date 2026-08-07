from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean
from typing import Any


def _get(document: dict[str, Any], *path: str, default=0):
    value: Any = document
    for key in path:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    return default if value is None else value


class MetricFeatureExtractor:
    """Turn raw snapshots into stable 1/5/15 minute analysis features."""

    def extract(
        self, snapshots: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if not snapshots:
            return {}

        ordered = sorted(
            snapshots, key=lambda item: item.get("timestamp", "")
        )
        latest_time = self._parse_time(ordered[-1].get("timestamp"))
        windows: dict[str, dict[str, Any]] = {}
        for minutes in (1, 5, 15):
            selected = [
                item for item in ordered
                if latest_time is None
                or (
                    self._parse_time(item.get("timestamp")) is not None
                    and self._parse_time(item.get("timestamp"))
                    >= latest_time - timedelta(minutes=minutes)
                )
            ]
            windows[f"{minutes}m"] = self._summarize(
                selected or [ordered[-1]]
            )

        features = self._summarize(ordered)
        features["windows"] = windows
        return features

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None

    def _summarize(
        self, ordered: list[dict[str, Any]]
    ) -> dict[str, Any]:
        latest = ordered[-1]
        cpu = [float(_get(item, "cpu", "percent")) for item in ordered]
        memory = [
            float(_get(item, "memory", "percent")) for item in ordered
        ]
        disk = [
            float(_get(item, "disk", "root", "percent"))
            for item in ordered
        ]
        close_wait = [
            int(
                _get(
                    item,
                    "network",
                    "connections",
                    "by_status",
                    "CLOSE_WAIT",
                )
            )
            for item in ordered
        ]
        network_errors = [
            int(_get(item, "network", "errors_in"))
            + int(_get(item, "network", "errors_out"))
            + int(_get(item, "network", "drops_in"))
            + int(_get(item, "network", "drops_out"))
            for item in ordered
        ]
        processes = _get(latest, "processes", "items", default=[])
        top_process = processes[0] if processes else {}

        return {
            "sample_count": len(ordered),
            "window_start": ordered[0].get("timestamp"),
            "window_end": latest.get("timestamp"),
            "cpu_avg": round(mean(cpu), 2),
            "cpu_max": round(max(cpu), 2),
            "cpu_latest": round(cpu[-1], 2),
            "memory_avg": round(mean(memory), 2),
            "memory_max": round(max(memory), 2),
            "memory_latest": round(memory[-1], 2),
            "memory_slope": round(memory[-1] - memory[0], 2),
            "available_memory_bytes": int(
                _get(latest, "memory", "available_bytes")
            ),
            "swap_used_bytes": int(
                _get(latest, "memory", "swap_used_bytes")
            ),
            "disk_avg": round(mean(disk), 2),
            "disk_latest": round(disk[-1], 2),
            "disk_growth": round(disk[-1] - disk[0], 2),
            "disk_free_bytes": int(
                _get(latest, "disk", "root", "free_bytes")
            ),
            "close_wait_latest": close_wait[-1],
            "close_wait_growth": close_wait[-1] - close_wait[0],
            "network_error_growth": (
                network_errors[-1] - network_errors[0]
            ),
            "top_process": {
                "pid": top_process.get("pid"),
                "name": top_process.get("name"),
                "cpu_percent": top_process.get("cpu_percent", 0),
                "memory_rss_bytes": top_process.get(
                    "memory_rss_bytes", 0
                ),
                "thread_count": top_process.get("thread_count", 0),
            },
        }

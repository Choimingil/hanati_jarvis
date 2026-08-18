from __future__ import annotations

from typing import Any


class IncidentCorrelator:
    """Reduce nearby error logs to evidence suitable for retrieval/LLM."""

    def correlate(
        self,
        event: dict[str, Any],
        logs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        related = []
        for log in logs[:20]:
            related.append({
                "timestamp": log.get("timestamp")
                or log.get("received_at"),
                "level": log.get("level"),
                "message": log.get("message", "")[:500],
                "service": log.get("service"),
            })
        return {
            "detection": event,
            "related_logs": related,
            "log_count": len(related),
        }

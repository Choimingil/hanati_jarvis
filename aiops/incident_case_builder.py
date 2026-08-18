from __future__ import annotations

import uuid
from typing import Any

from utils.time_utils import now_iso


class IncidentCaseBuilder:
    def build(
        self,
        host: str,
        event: dict[str, Any],
        features: dict[str, Any],
        correlation: dict[str, Any],
        recommendation: dict[str, Any],
    ) -> dict[str, Any]:
        evidence = "; ".join(event.get("evidence", []))
        return {
            "incident_id": str(uuid.uuid4()),
            "created_at": now_iso(),
            "host": host,
            "error_code": event["error_code"],
            "detection_code": event["detection_code"],
            "severity": event["severity"],
            "summary": (
                f"{host}에서 {event['detection_code']} 감지: {evidence}"
            ),
            "root_cause": recommendation.get("cause", "분석 필요"),
            "metric_features": features,
            "related_logs": correlation.get("related_logs", []),
            "recommendation": recommendation,
            "status": "open",
        }

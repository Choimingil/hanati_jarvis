from __future__ import annotations

from typing import Any


class ContextBuilder:
    def build(
        self,
        event: dict[str, Any],
        features: dict[str, Any],
        correlation: dict[str, Any],
    ) -> dict[str, Any]:
        log_messages = [
            log.get("message", "")
            for log in correlation.get("related_logs", [])
        ]
        evidence = event.get("evidence", [])
        message = " | ".join(
            [event["detection_code"], *evidence, *log_messages[:5]]
        )
        return {
            "message": message,
            "diagnosis_results": [{
                "status": "detected",
                "detection_code": event["detection_code"],
                "severity": event["severity"],
                "evidence": evidence,
                "metric_features": features,
                "related_logs": log_messages[:10],
            }],
        }

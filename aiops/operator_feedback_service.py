from __future__ import annotations

from typing import Any

from utils.time_utils import now_iso


class OperatorFeedbackService:
    ALLOWED_VERDICTS = {
        "confirmed", "partial", "rejected", "needs_investigation"
    }

    def __init__(self, repository, incident_indexer) -> None:
        self.repository = repository
        self.incident_indexer = incident_indexer

    def submit(self, body: dict[str, Any]) -> dict[str, Any]:
        guidance = self.repository.get_resource_guidance(
            body["guidance_id"]
        )
        if guidance is None:
            raise LookupError("guidance not found")
        verdict = body["verdict"]
        if verdict not in self.ALLOWED_VERDICTS:
            raise ValueError("invalid verdict")

        feedback = {
            "timestamp": now_iso(),
            "guidance_id": body["guidance_id"],
            "operator": body["operator"],
            "verdict": verdict,
            "confirmed_root_cause": body.get("confirmed_root_cause"),
            "successful_action": body.get("successful_action"),
            "recovered": bool(body.get("recovered", False)),
        }
        self.repository.save_operator_feedback(feedback)

        promoted = all([
            verdict == "confirmed",
            feedback["recovered"],
            feedback["confirmed_root_cause"],
            feedback["successful_action"],
        ])
        if promoted:
            related_code = next((
                item.get("related_error_code")
                for item in guidance.get("hypotheses", [])
                if item.get("problem_code")
                == guidance.get("primary_problem_code")
            ), None)
            incident = {
                "incident_id": guidance["guidance_id"],
                "created_at": guidance["created_at"],
                "host": guidance["host"],
                "service": guidance.get("service"),
                "error_code": body.get("confirmed_error_code")
                or related_code or "UNKNOWN_RESOURCE_ISSUE",
                "summary": guidance["summary"],
                "root_cause": feedback["confirmed_root_cause"],
                "resolution": feedback["successful_action"],
                "metric_features": guidance.get("resource_features", {}),
                "operator_verified": True,
                "recovered": True,
            }
            self.repository.save_incident(incident)
            try:
                self.incident_indexer.index(incident)
                indexed = True
            except Exception:
                indexed = False
        else:
            indexed = False

        return {
            "status": "feedback_stored",
            "promoted_to_incident_case": promoted,
            "qdrant_indexed": indexed,
        }

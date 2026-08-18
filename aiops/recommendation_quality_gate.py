from __future__ import annotations

from typing import Any

from config import RESOURCE_FALLBACK_CONFIDENCE_THRESHOLD


class RecommendationQualityGate:
    """Decide when the normal error-code/Runbook path is insufficient."""

    def requires_fallback(
        self,
        error_code: str | None,
        remediation_candidates: list[str],
        recommendation: dict[str, Any] | None,
    ) -> tuple[bool, str]:
        if error_code is None:
            return True, "unknown_error_code"
        if not remediation_candidates:
            return True, "no_remediation_candidates"
        if not recommendation:
            return True, "empty_recommendation"

        runbooks = recommendation.get("runbooks") or []
        if not runbooks:
            return True, "no_runbooks"
        confidence = max(
            float(runbook.get("confidence", 0)) for runbook in runbooks
        )
        if confidence < RESOURCE_FALLBACK_CONFIDENCE_THRESHOLD:
            return True, "low_recommendation_confidence"
        return False, "sufficient"

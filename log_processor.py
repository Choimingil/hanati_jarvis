from typing import Any

from config import (
    DIAGNOSTIC_SCRIPTS,
    ERROR_RULES,
)
from error_detector import detect_error_code
from log_normalizer import normalize_log
from ports.case_searcher import CaseSearcher
from ports.log_repository import LogRepository
from ports.recommendation_generator import (
    RecommendationGenerator,
)
from script_runner import run_script
from utils.time_utils import now_iso


class LogProcessor:

    def __init__(
        self,
        repository: LogRepository,
        case_searcher: CaseSearcher,
        recommendation_generator:
            RecommendationGenerator,
        quality_gate=None,
        resource_context_loader=None,
        resource_hypothesis_engine=None,
        fallback_guidance_generator=None,
        incident_service=None,
    ) -> None:
        self.repository = repository
        self.case_searcher = case_searcher
        self.recommendation_generator = (
            recommendation_generator
        )
        self.quality_gate = quality_gate
        self.resource_context_loader = resource_context_loader
        self.resource_hypothesis_engine = resource_hypothesis_engine
        self.fallback_guidance_generator = fallback_guidance_generator
        self.incident_service = incident_service

    def process(
        self,
        raw_log: dict[str, Any],
    ) -> dict[str, Any]:
        log = normalize_log(raw_log)

        if log["level"] != "ERROR":
            self.repository.save_log({
                "received_at": now_iso(),
                **log,
            })
            return {
                "status": "ignored",
                "reason": "log level is not ERROR",
            }

        error_code = detect_error_code(
            log["message"]
        )
        incident = (
            self.incident_service.start(log, error_code)
            if self.incident_service is not None
            else None
        )
        self.repository.save_log({
            "received_at": now_iso(),
            "incident_id": (
                incident.get("incident_id")
                if incident else None
            ),
            **log,
        })

        if error_code is None:
            return self._resource_fallback(
                log=log,
                reason="unknown_error_code",
                original_error_code=None,
                incident=incident,
            )

        rule = ERROR_RULES[error_code]

        diagnosis_results = self._run_diagnostics(
            error_code=error_code,
            log=log,
            script_ids=rule.get(
                "diagnostic_scripts",
                [],
            ),
        )

        try:
            past_cases = self.case_searcher.search(
                error_code=error_code,
                message=log["message"],
                limit=3,
            )
        except Exception:
            past_cases = []

        try:
            recommendation = self.recommendation_generator.generate(
                error_code=error_code,
                message=log["message"],
                diagnosis_results=(
                    diagnosis_results
                ),
                past_cases=past_cases,
                remediation_candidates=rule.get(
                    "remediation_candidates",
                    [],
                ),
            )
        except Exception:
            recommendation = None

        if self.quality_gate is not None:
            fallback, reason = self.quality_gate.requires_fallback(
                error_code,
                rule.get("remediation_candidates", []),
                recommendation,
            )
            if fallback:
                return self._resource_fallback(
                    log=log,
                    reason=reason,
                    original_error_code=error_code,
                    incident=incident,
                )

        if self.incident_service is not None and incident is not None:
            recommendation, incident = (
                self.incident_service.complete_analysis(
                    incident,
                    recommendation,
                    status="ACTION_REQUIRED",
                )
            )

        self.repository.save_recommendation({
            "timestamp": now_iso(),
            "incident_id": (
                incident.get("incident_id")
                if incident else None
            ),
            "log": log,
            "recommendation": recommendation,
        })

        return {
            "status": "recommended",
            "error_code": error_code,
            "diagnosis_count": len(
                diagnosis_results
            ),
            "recommendation": recommendation,
        }

    def _resource_fallback(
        self,
        log: dict[str, Any],
        reason: str,
        original_error_code: str | None,
        incident: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not all([
            self.resource_context_loader,
            self.resource_hypothesis_engine,
            self.fallback_guidance_generator,
        ]):
            return {
                "status": "unknown_error",
                "message": log["message"],
            }

        resource_context = self.resource_context_loader.load(log)
        hypotheses = self.resource_hypothesis_engine.analyze(
            resource_context["features"]
        )
        related_error_code = next((
            hypothesis.get("related_error_code")
            for hypothesis in hypotheses
            if hypothesis.get("related_error_code")
        ), None)
        search_code = (
            related_error_code
            or original_error_code
            or "UNKNOWN_RESOURCE_ISSUE"
        )
        try:
            past_cases = self.case_searcher.search(
                error_code=search_code,
                message=(
                    log["message"] + " "
                    + " ".join(
                        hypothesis["title"] for hypothesis in hypotheses
                    )
                ),
                limit=3,
            )
        except Exception:
            past_cases = []

        guidance = self.fallback_guidance_generator.generate(
            log=log,
            reason=reason,
            resource_context=resource_context,
            hypotheses=hypotheses,
            past_cases=past_cases,
        )
        guidance["original_error_code"] = original_error_code
        if self.incident_service is not None and incident is not None:
            guidance, incident = (
                self.incident_service.complete_analysis(
                    incident,
                    guidance,
                    status="INVESTIGATING",
                )
            )
        self.repository.save_resource_guidance(guidance)
        self.repository.save_recommendation({
            "timestamp": now_iso(),
            "source": "resource_fallback",
            "guidance_id": guidance["guidance_id"],
            "incident_id": (
                incident.get("incident_id")
                if incident else None
            ),
            "log": log,
            "guidance": guidance,
        })
        return guidance

    def _run_diagnostics(
        self,
        error_code: str,
        log: dict[str, Any],
        script_ids: list[str],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        for script_id in script_ids:
            result = run_script(
                script_id,
                DIAGNOSTIC_SCRIPTS,
            )

            results.append(result)

            self.repository.save_diagnosis({
                "timestamp": now_iso(),
                "error_code": error_code,
                "message": log["message"],
                "host": log["host"],
                "service": log["service"],
                "script_id": script_id,
                "result": result,
            })

        return results

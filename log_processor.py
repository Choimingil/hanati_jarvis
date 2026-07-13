from datetime import UTC, datetime
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


class LogProcessor:

    def __init__(
        self,
        repository: LogRepository,
        case_searcher: CaseSearcher,
        recommendation_generator:
            RecommendationGenerator,
    ) -> None:
        self.repository = repository
        self.case_searcher = case_searcher
        self.recommendation_generator = (
            recommendation_generator
        )

    def process(
        self,
        raw_log: dict[str, Any],
    ) -> dict[str, Any]:
        log = normalize_log(raw_log)

        self.repository.save_log({
            "received_at": now_iso(),
            **log,
        })

        if log["level"] != "ERROR":
            return {
                "status": "ignored",
                "reason": "log level is not ERROR",
            }

        error_code = detect_error_code(
            log["message"]
        )

        if error_code is None:
            return {
                "status": "unknown_error",
                "message": log["message"],
            }

        rule = ERROR_RULES[error_code]

        diagnosis_results = self._run_diagnostics(
            error_code=error_code,
            log=log,
            script_ids=rule.get(
                "diagnostic_scripts",
                [],
            ),
        )

        past_cases = self.case_searcher.search(
            error_code=error_code,
            message=log["message"],
            limit=3,
        )

        recommendation = (
            self.recommendation_generator.generate(
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
        )

        self.repository.save_recommendation({
            "timestamp": now_iso(),
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


def now_iso() -> str:
    return datetime.now(UTC).isoformat()

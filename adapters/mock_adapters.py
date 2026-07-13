from copy import deepcopy
from typing import Any

from ports.case_searcher import CaseSearcher
from ports.log_repository import LogRepository
from ports.recommendation_generator import (
    RecommendationGenerator,
)


class MockLogRepository(LogRepository):

    def __init__(self) -> None:
        self.logs: list[dict[str, Any]] = []
        self.diagnoses: list[dict[str, Any]] = []
        self.recommendations: list[
            dict[str, Any]
        ] = []
        self.remediations: list[
            dict[str, Any]
        ] = []

    def save_log(
        self,
        document: dict[str, Any],
    ) -> None:
        self.logs.append(deepcopy(document))
        print("[MOCK REPOSITORY] log saved:", document)

    def save_diagnosis(
        self,
        document: dict[str, Any],
    ) -> None:
        self.diagnoses.append(deepcopy(document))
        print(
            "[MOCK REPOSITORY] diagnosis saved:",
            document,
        )

    def save_recommendation(
        self,
        document: dict[str, Any],
    ) -> None:
        self.recommendations.append(
            deepcopy(document)
        )
        print(
            "[MOCK REPOSITORY] recommendation saved:",
            document,
        )

    def save_remediation(
        self,
        document: dict[str, Any],
    ) -> None:
        self.remediations.append(
            deepcopy(document)
        )
        print(
            "[MOCK REPOSITORY] remediation saved:",
            document,
        )


class MockCaseSearcher(CaseSearcher):

    def search(
        self,
        error_code: str,
        message: str,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        print(
            "[MOCK CASE SEARCH]",
            error_code,
            message,
        )

        if error_code == "DISK_FULL":
            return [
                {
                    "incident_id": "TEST-001",
                    "error_code": "DISK_FULL",
                    "summary": "로그 파일 증가로 디스크 부족",
                    "root_cause": "오래된 로그 미정리",
                    "resolution": "오래된 로그 압축",
                    "score": 0.95,
                }
            ]

        return []


class MockRecommendationGenerator(
    RecommendationGenerator
):

    def generate(
        self,
        error_code: str,
        message: str,
        diagnosis_results: list[dict[str, Any]],
        past_cases: list[dict[str, Any]],
        remediation_candidates: list[str],
    ) -> dict[str, Any]:
        print(
            "[MOCK LLM] recommendation requested:",
            error_code,
        )

        return {
            "error_code": error_code,
            "summary": (
                f"{error_code} 에러가 감지되었습니다."
            ),
            "message": message,
            "diagnosis_summary": diagnosis_results,
            "past_cases": past_cases,
            "recommended_actions": (
                remediation_candidates
            ),
            "requires_approval": True,
            "generated_by": "mock-llm",
        }

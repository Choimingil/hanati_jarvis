from typing import Any

from config import ERROR_RULES
from elastic_repository import find_incident_cases


def get_past_cases(
    error_code: str,
    message: str,
) -> list[dict[str, Any]]:
    try:
        return find_incident_cases(
            error_code=error_code,
            message=message,
            size=3,
        )

    except Exception as exc:
        # incident-cases 인덱스가 없거나
        # Elasticsearch 검색이 실패해도
        # 로그 수신 전체를 실패시키지 않습니다.
        return [
            {
                "search_status": "failed",
                "reason": str(exc),
            }
        ]


def make_recommendation(
    error_code: str,
    diagnosis_results: list[dict[str, Any]],
    past_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    rule = ERROR_RULES[error_code]

    return {
        "error_code": error_code,
        "summary": (
            f"{error_code} 에러가 감지되었습니다."
        ),
        "diagnosis_summary": diagnosis_results,
        "past_cases": past_cases,
        "recommended_actions": (
            rule["remediation_candidates"]
        ),
        "auto_remediate": rule.get(
            "auto_remediate",
            False,
        ),
        "requires_approval": not rule.get(
            "auto_remediate",
            False,
        ),
    }

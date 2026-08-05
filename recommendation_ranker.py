"""추천 스크립트 랭킹 / 원인 문구를 만드는 결정론적 헬퍼.

LLM이 없을 때(`LLMRecommendationGenerator`의 fallback)와
`MockRecommendationGenerator`가 공유해서, LLM 연동 여부와 무관하게
항상 "추천도 높은 순 스크립트 리스트"를 만들 수 있게 한다.
"""

from typing import Any

from config import SCRIPT_DESCRIPTIONS


def build_ranked_actions(
    error_code: str,
    remediation_candidates: list[str],
    past_cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """조치 후보를 추천도(score) 높은 순으로 정렬한 리스트로 만든다.

    - ERROR_RULES에 등록된 후보 순서를 기본 우선순위로 사용
    - 과거 유사 사례가 있으면 신뢰도를 소폭 상향
    """
    top_case_score = max(
        (float(c.get("score", 0.0)) for c in past_cases),
        default=0.0,
    )

    ranked: list[dict[str, Any]] = []

    for index, script_id in enumerate(remediation_candidates):
        base = 0.9 - index * 0.15
        boost = 0.05 if past_cases else 0.0
        score = round(min(base + boost, 0.99), 2)

        description = SCRIPT_DESCRIPTIONS.get(script_id, script_id)
        reason_parts = [description]
        if past_cases:
            reason_parts.append(
                f"과거 유사 사례 {len(past_cases)}건"
                f"(최고 유사도 {top_case_score:.2f}) 기반"
            )

        ranked.append({
            "script_id": script_id,
            "score": score,
            "reason": " · ".join(reason_parts),
        })

    return ranked


def build_cause(
    error_code: str,
    message: str,
    past_cases: list[dict[str, Any]],
) -> str:
    """오류 원인 설명 문구를 만든다."""
    root_cause = past_cases[0].get("root_cause") if past_cases else None

    if root_cause:
        return (
            f"'{message}' 로그가 감지되었습니다. "
            f"과거 유사 사례 기준 원인은 '{root_cause}'로 추정됩니다."
        )

    return (
        f"'{message}' 로그로 보아 {error_code} 유형의 "
        f"장애가 감지되었습니다."
    )

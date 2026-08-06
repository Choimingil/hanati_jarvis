"""LLM 기반 추천 생성기 (RecommendationGenerator 포트 구현체).

LLM(OpenAI 호환)에게 "현재 오류 원인"과 "호출하면 좋은 조치 스크립트를
추천도 높은 순으로" 물어보고, 그 결과를 표준 응답 스키마로 반환한다.

`llm_agent.services.llm_service.LLMService`를 감싸기 때문에, OPENAI_API_KEY가
없거나 openai 패키지가 없을 때는 LLMService가 fallback 모드로 동작하고,
여기서는 그 신호를 감지해 결정론적 랭킹(recommendation_ranker)으로
대체한다. 즉 어떤 환경에서도 "추천 스크립트 리스트"는 항상 채워진다.
"""

import json
from typing import Any

from config import SCRIPT_DESCRIPTIONS
from llm_agent.services.llm_service import LLMService
from ports.log_repository import LogRepository
from ports.recommendation_generator import (
    RecommendationGenerator,
)
from recommendation_ranker import (
    build_cause,
    build_ranked_actions,
)
from runbooks import REMEDIATION_RUNBOOKS


class LLMRecommendationGenerator(RecommendationGenerator):

    def __init__(
        self,
        llm_service: LLMService | None = None,
        history_provider: LogRepository | None = None,
    ) -> None:
        self.llm_service = llm_service or LLMService()
        self.history_provider = history_provider

    def generate(
        self,
        error_code: str,
        message: str,
        diagnosis_results: list[dict[str, Any]],
        past_cases: list[dict[str, Any]],
        remediation_candidates: list[str],
    ) -> dict[str, Any]:
        prompt = self._build_prompt(
            error_code=error_code,
            message=message,
            diagnosis_results=diagnosis_results,
            past_cases=past_cases,
            remediation_candidates=remediation_candidates,
        )

        raw_response = self.llm_service.generate_text(prompt)

        cause, ranked, used_llm = self._parse_response(
            raw_response,
            remediation_candidates,
        )

        if not used_llm:
            # LLM이 JSON을 못 주거나 fallback 모드 → 결정론적 랭킹으로 대체.
            cause = build_cause(error_code, message, past_cases)
            ranked = build_ranked_actions(
                error_code,
                remediation_candidates,
                past_cases,
            )

        runbooks = self._build_runbooks(cause, ranked)

        return {
            "error_code": error_code,
            "summary": f"{error_code} 에러가 감지되었습니다.",
            "cause": cause,
            "message": message,
            "diagnosis_summary": diagnosis_results,
            "past_cases": past_cases,
            "runbooks": runbooks,
            "requires_approval": True,
            "generated_by": (
                "llm" if used_llm else "llm-fallback"
            ),
        }

    def _build_runbooks(
        self,
        cause: str,
        ranked: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """스크립트 단위 랭킹(ranked)을 운영자가 승인/거부/진단 요청할 수
        있는 Runbook 단위로 감싼다. 실행 이력은 매번 저장소에서 실시간
        집계한다 (하드코딩하면 바로 거짓말이 되는 값이라)."""
        runbooks = []

        for action in ranked:
            script_id = action["script_id"]
            meta = REMEDIATION_RUNBOOKS.get(script_id, {})
            history = {"success": 0, "failure": 0}
            if self.history_provider is not None:
                history = self.history_provider.remediation_history(
                    script_id
                )

            runbooks.append({
                "script_id": script_id,
                "incident": meta.get(
                    "incident",
                    SCRIPT_DESCRIPTIONS.get(script_id, script_id),
                ),
                "estimated_cause": cause,
                "confidence": round(
                    max(0.0, min(1.0, action.get("score", 0.0)))
                    * 100
                ),
                "action": meta.get(
                    "action",
                    SCRIPT_DESCRIPTIONS.get(script_id, script_id),
                ),
                "reason": action.get("reason", ""),
                "expected_impact": meta.get(
                    "expected_impact", "확인되지 않음"
                ),
                "history": history,
                "rollback": meta.get(
                    "rollback", "담당팀에게 에스컬레이션"
                ),
            })

        return runbooks

    def _build_prompt(
        self,
        error_code: str,
        message: str,
        diagnosis_results: list[dict[str, Any]],
        past_cases: list[dict[str, Any]],
        remediation_candidates: list[str],
    ) -> str:
        candidate_lines = "\n".join(
            f"- {script_id}: "
            f"{SCRIPT_DESCRIPTIONS.get(script_id, script_id)}"
            for script_id in remediation_candidates
        )

        past_case_lines = "\n".join(
            f"- {case.get('summary', '')} "
            f"(원인: {case.get('root_cause', '')}, "
            f"해결: {case.get('resolution', '')})"
            for case in past_cases
        ) or "없음"

        candidate_ids = ", ".join(remediation_candidates)

        return f"""당신은 AIOps 장애 대응 전문가입니다.
아래 장애 정보를 보고 (1) 현재 오류의 원인과 (2) 실행하면 좋은 조치
스크립트를 추천도(0.0~1.0) 높은 순으로 정렬해 추천하십시오.

## 오류 코드
{error_code}

## 오류 메시지
{message}

## 과거 유사 사례
{past_case_lines}

## 선택 가능한 조치 스크립트 (반드시 이 id 중에서만 고를 것)
{candidate_lines}

아래 JSON 형식으로만 응답하십시오. script_id는 반드시
[{candidate_ids}] 중 하나여야 합니다.
{{"cause": "오류 원인 설명",
  "recommendations": [
    {{"script_id": "id", "score": 0.95, "reason": "추천 이유"}}
  ]}}
"""

    def _parse_response(
        self,
        raw_response: str,
        remediation_candidates: list[str],
    ) -> tuple[str, list[dict[str, Any]], bool]:
        """LLM 응답(JSON)을 파싱. 실패하면 (_, _, False)를 반환해
        상위에서 fallback 랭킹을 쓰도록 한다."""
        text = (raw_response or "").strip()

        # ```json ... ``` 코드펜스가 있으면 벗겨낸다.
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()

        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return "", [], False

        if not isinstance(parsed, dict):
            return "", [], False

        cause = str(parsed.get("cause", "")).strip()
        raw_recommendations = parsed.get("recommendations", [])

        if not cause or not isinstance(
            raw_recommendations, list
        ):
            return "", [], False

        allowed = set(remediation_candidates)
        ranked: list[dict[str, Any]] = []
        seen: set[str] = set()

        for item in raw_recommendations:
            if not isinstance(item, dict):
                continue
            script_id = item.get("script_id")
            if script_id not in allowed or script_id in seen:
                continue
            try:
                score = float(item.get("score", 0.0))
            except (TypeError, ValueError):
                score = 0.0
            ranked.append({
                "script_id": script_id,
                "score": round(score, 2),
                "reason": str(
                    item.get(
                        "reason",
                        SCRIPT_DESCRIPTIONS.get(
                            script_id, script_id
                        ),
                    )
                ),
            })
            seen.add(script_id)

        if not ranked:
            return "", [], False

        # LLM이 빠뜨린 후보는 낮은 점수로 뒤에 붙여 전체 목록을 보여준다.
        for script_id in remediation_candidates:
            if script_id not in seen:
                ranked.append({
                    "script_id": script_id,
                    "score": 0.3,
                    "reason": SCRIPT_DESCRIPTIONS.get(
                        script_id, script_id
                    ),
                })

        ranked.sort(
            key=lambda action: action["score"],
            reverse=True,
        )

        return cause, ranked, True

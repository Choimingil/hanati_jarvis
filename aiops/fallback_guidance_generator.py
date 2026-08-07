from __future__ import annotations

import json
import uuid
from typing import Any

from llm_agent.services.llm_service import LLMService
from utils.time_utils import now_iso


class FallbackGuidanceGenerator:
    def __init__(self, llm_service: LLMService | None = None) -> None:
        self.llm_service = llm_service or LLMService()

    def generate(
        self,
        log: dict[str, Any],
        reason: str,
        resource_context: dict[str, Any],
        hypotheses: list[dict[str, Any]],
        past_cases: list[dict[str, Any]],
    ) -> dict[str, Any]:
        primary = hypotheses[0]
        prompt = self._prompt(log, hypotheses, past_cases)
        generated_by = "rules-and-retrieval"
        summary = (
            "기존 Runbook을 추천할 수 없어 리소스를 분석했습니다. "
            f"{primary['title']}을 우선 확인해야 합니다."
        )
        try:
            parsed = json.loads(self.llm_service.generate_text(prompt))
            allowed = {item["problem_code"] for item in hypotheses}
            if parsed.get("primary_problem_code") in allowed:
                summary = str(parsed.get("summary") or summary)
                generated_by = "llm-grounded"
        except Exception:
            pass

        return {
            "guidance_id": str(uuid.uuid4()),
            "created_at": now_iso(),
            "status": "resource_guidance",
            "fallback_reason": reason,
            "host": resource_context["host"],
            "service": log.get("service"),
            "original_log": log,
            "summary": summary,
            "primary_problem_code": primary["problem_code"],
            "hypotheses": hypotheses,
            "resource_features": resource_context.get("features", {}),
            "related_logs": resource_context.get("related_logs", []),
            "past_cases": past_cases,
            "requires_operator_confirmation": True,
            "automatic_remediation": False,
            "generated_by": generated_by,
        }

    @staticmethod
    def _prompt(log, hypotheses, past_cases) -> str:
        return f"""당신은 AIOps 분석가입니다. 확정되지 않은 원인을 만들지 마십시오.
다음 후보 중 가장 근거가 강한 problem_code 하나를 고르고 수치 근거를 포함한
짧은 한국어 summary를 작성하십시오.

로그: {json.dumps(log, ensure_ascii=False)}
가설: {json.dumps(hypotheses, ensure_ascii=False)}
검증된 과거 사례: {json.dumps(past_cases, ensure_ascii=False)}

JSON만 응답: {{"primary_problem_code":"후보 코드", "summary":"설명"}}
"""

from llm_agent.builder.diagnosis import DiagnosisContextBuilder, DiagnosisPromptBuilder
from llm_agent.builder.recommendation import RecommendationContextBuilder, RecommendationPromptBuilder
from llm_agent.dto.diagnosis import DiagnosisRequest, DiagnosisResponse
from llm_agent.dto.recommendation import RecommendationRequest, RecommendationResponse
from llm_agent.services.llm_service import LLMService


class AiEngine:
    def __init__(self, llm_service: LLMService | None = None) -> None:
        self.llm_service = llm_service or LLMService()
        self._diagnosis_context_builder = DiagnosisContextBuilder()
        self._diagnosis_prompt_builder = DiagnosisPromptBuilder()
        self._recommendation_context_builder = RecommendationContextBuilder()
        self._recommendation_prompt_builder = RecommendationPromptBuilder()

    def get_recommendation(self, request: RecommendationRequest) -> RecommendationResponse:
        context = self._recommendation_context_builder.build(request)
        prompt = self._recommendation_prompt_builder.build(context)

        raw_response = self.llm_service.generate_text(prompt)

        try:
            import json

            parsed = json.loads(raw_response)
            command = parsed.get("command", "")
            reason = parsed.get("reason", "")
            confidence = float(parsed.get("confidence", 0.0))
        except (json.JSONDecodeError, TypeError, ValueError):
            command = ""
            reason = raw_response
            confidence = 0.0

        return RecommendationResponse(
            command=command,
            reason=reason,
            confidence=confidence,
        )

    def get_diagnosis(self, request: DiagnosisRequest) -> DiagnosisResponse:
        context = self._diagnosis_context_builder.build(request)
        prompt = self._diagnosis_prompt_builder.build(context)

        raw_response = self.llm_service.generate_text(prompt)

        try:
            import json

            parsed = json.loads(raw_response)
            reason = parsed.get("reason", "")
            confidence = float(parsed.get("confidence", 0.0))
        except (json.JSONDecodeError, TypeError, ValueError):
            reason = raw_response
            confidence = 0.0

        return DiagnosisResponse(
            reason=reason,
            confidence=confidence,
        )
from llm_agent.builder.context_builder import RecommendationContextBuilder
from llm_agent.builder.prompt_builder import RecommendationPromptBuilder
from llm_agent.dto.recommendation import RecommendationRequest, RecommendationResponse
from llm_agent.services.llm_service import LLMService


class AiEngine:
    def __init__(self, llm_service: LLMService | None = None) -> None:
        self.context_builder = RecommendationContextBuilder()
        self.prompt_builder = RecommendationPromptBuilder()
        self.llm_service = llm_service or LLMService()


    def get_recommendation(self, request: RecommendationRequest) -> RecommendationResponse:
        context = self.context_builder.build(request)
        prompt = self.prompt_builder.build(context)

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

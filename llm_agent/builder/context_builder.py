from typing import Any

from llm_agent.dto.recommendation import RecommendationRequest


class RecommendationContextBuilder:
    def build(self, request: RecommendationRequest) -> dict[str, Any]:
        return {
            "logs": [log.to_dict() if hasattr(log, "to_dict") else log for log in request.logs],
            "commands": [
                {
                    "name": command.name,
                    "description": command.description,
                    "category": command.category.name,
                    "permission": command.permission.name,
                    "risk": command.risk.name,
                    "ai_hint": command.ai_hint,
                    "enabled": command.enabled,
                }
                for command in request.commands
            ],
            "evidences": [
                evidence.to_dict() if hasattr(evidence, "to_dict") else evidence
                for evidence in request.evidences
            ],
        }

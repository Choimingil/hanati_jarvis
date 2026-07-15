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


class RecommendationPromptBuilder:
    def build(self, context: dict[str, Any]) -> str:
        logs = context.get("logs", [])
        commands = context.get("commands", [])
        evidences = context.get("evidences", [])

        logs_text = "\n".join(str(item) for item in logs[:5])
        commands_text = "\n".join(
            f"- {item['name']}: {item['description']} (위험도={item['risk']}, 분류={item['category']})"
            for item in commands
        )
        evidence_text = "\n".join(str(item) for item in evidences[:5])

        return f"""
당신은 AI Ops 시스템의 장애 분석 전문가입니다.
다음 정보를 바탕으로 현재 장애 상황에서 가장 적절한 명령어 하나를 선택하십시오.

## 로그
{logs_text or '없음'}

## 사용 가능한 명령어
{commands_text or '없음'}

## 시스템 상태
{evidence_text or '없음'}

다음 JSON 형식으로만 응답하십시오.
{{"command": "추천 명령어 이름", "reason": "추천 이유", "confidence": 0.95}}
"""

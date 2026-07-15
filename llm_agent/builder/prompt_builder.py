from typing import Any


class RecommendationPromptBuilder:
    def build(self, context: dict[str, Any]) -> str:
        logs = context.get("logs", [])
        commands = context.get("commands", [])
        evidences = context.get("evidences", [])

        logs_text = "\n".join(str(item) for item in logs[:5])

        commands_text = "\n".join(
            f"- {item['name']}: {item['description']} "
            f"(위험도={item['risk']}, 분류={item['category']})"
            for item in commands
        )

        evidence_text = "\n".join(str(item) for item in evidences[:5])

        return f"""
당신은 AI Ops 시스템의 장애 분석 전문가입니다.

다음 정보를 바탕으로 현재 장애 상황에서 가장 적절한 명령어 하나를 선택하십시오.

## 판단 기준
- 로그 내용을 우선적으로 분석합니다.
- 현재 시스템 상태(Evidence)를 함께 고려합니다.
- 제공된 명령어 목록에서만 선택합니다.
- 위험도가 낮은 명령을 우선 선택합니다.
- 현재 단계에서 가장 많은 정보를 얻을 수 있는 명령을 선택합니다.
- 명령을 실제 수행하지 말고 추천만 합니다.

## 로그
{logs_text or "없음"}

## 사용 가능한 명령어
{commands_text or "없음"}

## 시스템 상태
{evidence_text or "없음"}

다음 JSON 형식으로만 응답하십시오.

{{
    "command": "추천 명령어 이름",
    "reason": "추천 이유",
    "confidence": 0.95
}}
"""
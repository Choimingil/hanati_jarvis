from typing import Any

from llm_agent.dto.diagnosis import DiagnosisRequest


class DiagnosisContextBuilder:
    def build(self, request: DiagnosisRequest) -> dict[str, Any]:
        return {
            "logs": [log.to_dict() if hasattr(log, "to_dict") else log for log in request.logs],
            "evidences": [
                evidence.to_dict() if hasattr(evidence, "to_dict") else evidence
                for evidence in request.evidences
            ],
        }


class DiagnosisPromptBuilder:
    def build(self, context: dict[str, Any]) -> str:
        logs = context.get("logs", [])
        evidences = context.get("evidences", [])
        logs_text = "\n".join(str(item) for item in logs[:5])
        evidence_text = "\n".join(str(item) for item in evidences[:5])

        return f"""
당신은 AI Ops의 장애 진단 전문가입니다.
다음 로그와 증거를 바탕으로 원인과 대응 방향을 분석하십시오.

## 로그
{logs_text or '없음'}

## 증거
{evidence_text or '없음'}

다음 JSON 형식으로만 응답하십시오.
{{"reason": "진단 이유", "confidence": 0.95}}
"""

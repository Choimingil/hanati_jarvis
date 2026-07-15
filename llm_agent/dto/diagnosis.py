from pydantic import BaseModel

from llm_agent.model.log_evidence import LogDefinition
from llm_agent.model.system_evidence import SystemEvidence


class DiagnosisRequest(BaseModel):
    logs: list[LogDefinition]
    evidences: list[SystemEvidence]


class DiagnosisResponse(BaseModel):
    reason: str
    confidence: float
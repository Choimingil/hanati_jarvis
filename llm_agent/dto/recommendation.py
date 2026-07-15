from pydantic import BaseModel

from llm_agent.model.command import CommandDefinition
from llm_agent.model.log_evidence import LogDefinition
from llm_agent.model.system_evidence import SystemEvidence


class RecommendationRequest(BaseModel):
    logs: list[LogDefinition]
    commands: list[CommandDefinition]
    evidences: list[SystemEvidence]


class RecommendationResponse(BaseModel):
    command: str
    reason: str
    confidence: float
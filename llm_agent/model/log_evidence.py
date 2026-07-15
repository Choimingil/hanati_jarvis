from dataclasses import dataclass
from enum import Enum

from llm_agent.model.system_evidence import EvidenceBase, EvidenceImportance


LogImportance = EvidenceImportance


class LogCategory(Enum):
    DATABASE = "DATABASE"
    APPLICATION = "APPLICATION"
    NETWORK = "NETWORK"
    SECURITY = "SECURITY"
    SYSTEM = "SYSTEM"


@dataclass
class LogDefinition(EvidenceBase):
    source: str
    category: LogCategory
    keywords: list[str]
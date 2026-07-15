from dataclasses import dataclass
from enum import Enum

from llm_agent.model.evidence import EvidenceBase


class EvidenceType(Enum):
    CPU = "CPU"
    MEMORY = "MEMORY"
    DISK = "DISK"
    PROCESS = "PROCESS"
    NETWORK = "NETWORK"
    DATABASE = "DATABASE"
    SERVICE = "SERVICE"
    FILESYSTEM = "FILESYSTEM"


class EvidenceImportance(Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class SystemEvidence(EvidenceBase):
    type: EvidenceType
    current_value: str
    expected_value: str | None
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class EvidenceImportance(Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class EvidenceBase:
    name: str
    description: str
    importance: EvidenceImportance
    ai_hint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "importance": self.importance.name if isinstance(self.importance, Enum) else self.importance,
            "ai_hint": self.ai_hint,
        }

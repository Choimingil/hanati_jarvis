from dataclasses import dataclass
from enum import Enum


class CommandRisk(Enum):
    SAFE = "SAFE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CommandCategory(Enum):
    PROCESS = "PROCESS"
    LOG = "LOG"
    NETWORK = "NETWORK"
    FILESYSTEM = "FILESYSTEM"
    DATABASE = "DATABASE"
    SYSTEM = "SYSTEM"


class CommandPermission(Enum):
    READ = "READ"
    WRITE = "WRITE"
    ADMIN = "ADMIN"


@dataclass(frozen=True)
class CommandDefinition:
    name: str
    template: str
    description: str
    category: CommandCategory
    permission: CommandPermission
    risk: CommandRisk
    ai_hint: str
    enabled: bool = True
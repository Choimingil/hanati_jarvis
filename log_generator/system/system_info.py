from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class NormalLogPattern:
    delay: float
    messages: List[str] = field(default_factory=list)


@dataclass
class FailureBehavior:
    probability: float
    trigger_after: float
    scenario: Optional[object] = None


@dataclass
class SystemInfo:

    hostname: str

    ip: str

    os: str

    cpu_core: int

    memory_gb: int

    web_server: str

    application: str

    node_name: str

    cluster: str

    normal_log_pattern: Optional[NormalLogPattern] = None

    failure_behavior: Optional[FailureBehavior] = None
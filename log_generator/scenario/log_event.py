from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from logger.log_constants import SystemStatus


@dataclass
class LogEvent:

    delay: float

    level: str

    message: str

    status_after: Optional[str] = None

    source: Optional[str] = None

    timestamp: Optional[str] = None

    def __post_init__(self):
        if self.status_after is None:
            self.status_after = SystemStatus.HEALTHY

        if self.timestamp is None:
            self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
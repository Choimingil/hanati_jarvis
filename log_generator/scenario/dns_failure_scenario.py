
from .scenario import Scenario
from .log_event import LogEvent
from ..logger.log_constants import LogLevel, SystemStatus


class DNSFailureScenario(Scenario):

    def events(self):

        return [

            LogEvent(
                delay=0,
                level=LogLevel.WARN,
                message="DNS lookup timeout.",
                status_after=SystemStatus.DEGRADED,
                source="dns"
            ),

            LogEvent(
                delay=1,
                level=LogLevel.WARN,
                message="Retrying DNS resolution.",
                status_after=SystemStatus.DEGRADED,
                source="dns"
            ),

            LogEvent(
                delay=2,
                level=LogLevel.ERROR,
                message="Failed to resolve service endpoint.",
                status_after=SystemStatus.FAILED,
                source="dns"
            ),

            LogEvent(
                delay=3,
                level=LogLevel.ERROR,
                message="HTTP request aborted.",
                status_after=SystemStatus.FAILED,
                source="http"
            ),

            LogEvent(
                delay=4,
                level=LogLevel.ERROR,
                message="Circuit breaker opened.",
                status_after=SystemStatus.FAILED,
                source="circuit-breaker"
            ),
        ]
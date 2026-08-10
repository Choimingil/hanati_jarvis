from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class RateLimitExceededScenario(Scenario):

    stop_after_failure = False

    def events(self):

        return [

            LogEvent(
                delay=0,
                level=LogLevel.WARN,
                message="Inbound request rate approaching limit.",
                status_after=SystemStatus.DEGRADED,
                source="api-gateway"
            ),

            LogEvent(
                delay=1,
                level=LogLevel.WARN,
                message="Burst traffic detected from single client.",
                status_after=SystemStatus.DEGRADED,
                source="api-gateway"
            ),

            LogEvent(
                delay=2,
                level=LogLevel.ERROR,
                message="Rate limit exceeded for client requests.",
                status_after=SystemStatus.FAILED,
                source="api-gateway"
            ),

            LogEvent(
                delay=3,
                level=LogLevel.ERROR,
                message="Requests throttled with HTTP 429.",
                status_after=SystemStatus.FAILED,
                source="api-gateway"
            ),

            LogEvent(
                delay=4,
                level=LogLevel.ERROR,
                message="Downstream service overloaded by retry storm.",
                status_after=SystemStatus.FAILED,
                source="order-api"
            ),
        ]

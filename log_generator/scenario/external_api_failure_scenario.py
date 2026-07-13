from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class ExternalAPIFailureScenario(Scenario):

    stop_after_failure = False

    def events(self):

        return [

            LogEvent(
                delay=0,
                level=LogLevel.WARN,
                message="External API response time exceeded threshold.",
                status_after=SystemStatus.DEGRADED,
                source="http-client"
            ),

            LogEvent(
                delay=1,
                level=LogLevel.WARN,
                message="Retrying external API request.",
                status_after=SystemStatus.DEGRADED,
                source="http-client"
            ),

            LogEvent(
                delay=2,
                level=LogLevel.ERROR,
                message="Received HTTP 503 from external API.",
                status_after=SystemStatus.FAILED,
                source="http-client"
            ),

            LogEvent(
                delay=3,
                level=LogLevel.ERROR,
                message="Payment service unavailable.",
                status_after=SystemStatus.FAILED,
                source="payment"
            ),

            LogEvent(
                delay=4,
                level=LogLevel.ERROR,
                message="Transaction cancelled.",
                status_after=SystemStatus.FAILED,
                source="checkout"
            ),
        ]
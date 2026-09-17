from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class UpstreamGatewayTimeoutScenario(Scenario):

    stop_after_failure = False

    def events(self):

        return [

            LogEvent(
                delay=0,
                level=LogLevel.WARN,
                message="Upstream response time exceeded 2 seconds.",
                status_after=SystemStatus.DEGRADED,
                source="nginx"
            ),

            LogEvent(
                delay=1,
                level=LogLevel.WARN,
                message="Upstream connection retries increasing.",
                status_after=SystemStatus.DEGRADED,
                source="nginx"
            ),

            LogEvent(
                delay=2,
                level=LogLevel.ERROR,
                message="HTTP 504 gateway timeout from upstream.",
                status_after=SystemStatus.FAILED,
                source="nginx"
            ),

            LogEvent(
                delay=3,
                level=LogLevel.ERROR,
                message="Upstream marked as unavailable by health check.",
                status_after=SystemStatus.FAILED,
                source="nginx"
            ),

            LogEvent(
                delay=4,
                level=LogLevel.ERROR,
                message="Order submission failing for all clients.",
                status_after=SystemStatus.FAILED,
                source="order-api"
            ),
        ]

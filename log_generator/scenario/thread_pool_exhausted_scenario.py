from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class ThreadPoolExhaustedScenario(Scenario):

    stop_after_failure = False

    def events(self):

        return [

            LogEvent(
                delay=0,
                level=LogLevel.WARN,
                message="Request queue length exceeded threshold.",
                status_after=SystemStatus.DEGRADED,
                source="thread-pool"
            ),

            LogEvent(
                delay=1,
                level=LogLevel.WARN,
                message="Worker thread utilization at 95%.",
                status_after=SystemStatus.DEGRADED,
                source="thread-pool"
            ),

            LogEvent(
                delay=2,
                level=LogLevel.ERROR,
                message="Thread pool exhausted, no available workers.",
                status_after=SystemStatus.FAILED,
                source="thread-pool"
            ),

            LogEvent(
                delay=3,
                level=LogLevel.ERROR,
                message="Incoming requests rejected with 503.",
                status_after=SystemStatus.FAILED,
                source="api"
            ),

            LogEvent(
                delay=4,
                level=LogLevel.ERROR,
                message="Request latency exceeded SLA.",
                status_after=SystemStatus.FAILED,
                source="api"
            ),
        ]

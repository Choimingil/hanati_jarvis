from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class ConnectionPoolExhaustedScenario(Scenario):

    stop_after_failure = False

    def events(self):

        return [

            LogEvent(
                delay=0,
                level=LogLevel.WARN,
                message="Active DB connections reached 90% of pool size.",
                status_after=SystemStatus.DEGRADED,
                source="datasource"
            ),

            LogEvent(
                delay=1,
                level=LogLevel.WARN,
                message="Connection acquisition wait exceeded 3 seconds.",
                status_after=SystemStatus.DEGRADED,
                source="datasource"
            ),

            LogEvent(
                delay=2,
                level=LogLevel.ERROR,
                message="Connection pool exhausted, cannot acquire connection.",
                status_after=SystemStatus.FAILED,
                source="datasource"
            ),

            LogEvent(
                delay=3,
                level=LogLevel.ERROR,
                message="Order lookup requests timing out.",
                status_after=SystemStatus.FAILED,
                source="order-api"
            ),

            LogEvent(
                delay=4,
                level=LogLevel.ERROR,
                message="Health check endpoint returning 503.",
                status_after=SystemStatus.FAILED,
                source="order-api"
            ),
        ]

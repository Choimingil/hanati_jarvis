from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class DatabaseReplicationLagScenario(Scenario):

    stop_after_failure = False

    def events(self):

        return [

            LogEvent(
                delay=0,
                level=LogLevel.INFO,
                message="Read replica lag at 2 seconds.",
                status_after=SystemStatus.HEALTHY,
                source="database"
            ),

            LogEvent(
                delay=1,
                level=LogLevel.WARN,
                message="Read replica lag grew to 30 seconds.",
                status_after=SystemStatus.DEGRADED,
                source="database"
            ),

            LogEvent(
                delay=2,
                level=LogLevel.ERROR,
                message="Read replica replication lag exceeded threshold.",
                status_after=SystemStatus.FAILED,
                source="database"
            ),

            LogEvent(
                delay=3,
                level=LogLevel.ERROR,
                message="Stale order status returned to client.",
                status_after=SystemStatus.FAILED,
                source="order-api"
            ),

            LogEvent(
                delay=4,
                level=LogLevel.ERROR,
                message="Order status inconsistency reported by downstream.",
                status_after=SystemStatus.FAILED,
                source="order-api"
            ),
        ]

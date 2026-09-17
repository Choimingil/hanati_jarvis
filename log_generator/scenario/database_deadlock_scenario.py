from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class DatabaseDeadlockScenario(Scenario):

    stop_after_failure = False

    def events(self):

        return [

            LogEvent(
                delay=0,
                level=LogLevel.WARN,
                message="Lock wait time on orders table increasing.",
                status_after=SystemStatus.DEGRADED,
                source="database"
            ),

            LogEvent(
                delay=1,
                level=LogLevel.WARN,
                message="Transaction holding row lock for over 5 seconds.",
                status_after=SystemStatus.DEGRADED,
                source="database"
            ),

            LogEvent(
                delay=2,
                level=LogLevel.ERROR,
                message="Deadlock detected while updating order rows.",
                status_after=SystemStatus.FAILED,
                source="database"
            ),

            LogEvent(
                delay=3,
                level=LogLevel.ERROR,
                message="Order transaction rolled back after deadlock.",
                status_after=SystemStatus.FAILED,
                source="order-api"
            ),

            LogEvent(
                delay=4,
                level=LogLevel.ERROR,
                message="Checkout requests failing with transaction error.",
                status_after=SystemStatus.FAILED,
                source="order-api"
            ),
        ]

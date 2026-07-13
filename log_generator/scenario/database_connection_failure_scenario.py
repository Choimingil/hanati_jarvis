from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class DatabaseConnectionFailureScenario(Scenario):

    stop_after_failure = False

    def events(self):

        return [

            LogEvent(
                delay=0,
                level=LogLevel.WARN,
                message="Database connection timeout.",
                status_after=SystemStatus.DEGRADED,
                source="database"
            ),

            LogEvent(
                delay=1,
                level=LogLevel.WARN,
                message="Retrying database connection.",
                status_after=SystemStatus.DEGRADED,
                source="database"
            ),

            LogEvent(
                delay=2,
                level=LogLevel.ERROR,
                message="Database connection failed.",
                status_after=SystemStatus.FAILED,
                source="database"
            ),

            LogEvent(
                delay=3,
                level=LogLevel.ERROR,
                message="Unable to execute SQL query.",
                status_after=SystemStatus.FAILED,
                source="repository"
            ),

            LogEvent(
                delay=4,
                level=LogLevel.ERROR,
                message="Request processing aborted.",
                status_after=SystemStatus.FAILED,
                source="api"
            ),
        ]
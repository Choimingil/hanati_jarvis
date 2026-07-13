from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class DiskFullScenario(Scenario):

    stop_after_failure = False

    def events(self):

        return [

            LogEvent(
                delay=0,
                level=LogLevel.WARN,
                message="Disk usage exceeded 90%.",
                status_after=SystemStatus.DEGRADED,
                source="storage"
            ),

            LogEvent(
                delay=1,
                level=LogLevel.WARN,
                message="Failed to rotate log files.",
                status_after=SystemStatus.DEGRADED,
                source="logger"
            ),

            LogEvent(
                delay=2,
                level=LogLevel.ERROR,
                message="No space left on device.",
                status_after=SystemStatus.FAILED,
                source="storage"
            ),

            LogEvent(
                delay=3,
                level=LogLevel.ERROR,
                message="Unable to write application data.",
                status_after=SystemStatus.FAILED,
                source="application"
            ),

            LogEvent(
                delay=4,
                level=LogLevel.ERROR,
                message="Service entering read-only mode.",
                status_after=SystemStatus.FAILED,
                source="service"
            ),
        ]
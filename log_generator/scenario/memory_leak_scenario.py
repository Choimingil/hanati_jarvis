from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class MemoryLeakScenario(Scenario):

    stop_after_failure = False

    def events(self):

        return [

            LogEvent(
                delay=0,
                level=LogLevel.INFO,
                message="Memory usage steadily increasing.",
                status_after=SystemStatus.HEALTHY,
                source="runtime"
            ),

            LogEvent(
                delay=1,
                level=LogLevel.WARN,
                message="Heap usage exceeded 85%.",
                status_after=SystemStatus.DEGRADED,
                source="runtime"
            ),

            LogEvent(
                delay=2,
                level=LogLevel.WARN,
                message="Frequent garbage collection detected.",
                status_after=SystemStatus.DEGRADED,
                source="jvm"
            ),

            LogEvent(
                delay=3,
                level=LogLevel.ERROR,
                message="OutOfMemoryError encountered.",
                status_after=SystemStatus.FAILED,
                source="runtime"
            ),

            LogEvent(
                delay=4,
                level=LogLevel.ERROR,
                message="Application process terminated.",
                status_after=SystemStatus.FAILED,
                source="system"
            ),
        ]
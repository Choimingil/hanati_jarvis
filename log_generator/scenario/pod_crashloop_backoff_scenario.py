from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class PodCrashLoopBackOffScenario(Scenario):

    stop_after_failure = False

    def events(self):

        return [

            LogEvent(
                delay=0,
                level=LogLevel.WARN,
                message="Readiness probe failed for order-api pod.",
                status_after=SystemStatus.DEGRADED,
                source="kubelet"
            ),

            LogEvent(
                delay=1,
                level=LogLevel.WARN,
                message="Container restarted 3 times in 5 minutes.",
                status_after=SystemStatus.DEGRADED,
                source="kubelet"
            ),

            LogEvent(
                delay=2,
                level=LogLevel.ERROR,
                message="Pod entered CrashLoopBackOff state.",
                status_after=SystemStatus.FAILED,
                source="kubelet"
            ),

            LogEvent(
                delay=3,
                level=LogLevel.ERROR,
                message="Available replica count dropped below desired.",
                status_after=SystemStatus.FAILED,
                source="cluster"
            ),

            LogEvent(
                delay=4,
                level=LogLevel.ERROR,
                message="Service capacity reduced, requests shedding.",
                status_after=SystemStatus.FAILED,
                source="order-api"
            ),
        ]

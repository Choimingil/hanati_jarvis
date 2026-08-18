from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class ContainerOOMKilledScenario(Scenario):

    stop_after_failure = False

    def events(self):

        return [

            LogEvent(
                delay=0,
                level=LogLevel.WARN,
                message="Container memory usage approaching cgroup limit.",
                status_after=SystemStatus.DEGRADED,
                source="container"
            ),

            LogEvent(
                delay=1,
                level=LogLevel.WARN,
                message="Kubelet reported memory pressure on node.",
                status_after=SystemStatus.DEGRADED,
                source="kubelet"
            ),

            LogEvent(
                delay=2,
                level=LogLevel.ERROR,
                message="Container killed by OOM killer.",
                status_after=SystemStatus.FAILED,
                source="container"
            ),

            LogEvent(
                delay=3,
                level=LogLevel.ERROR,
                message="Pod restarted due to OOMKilled status.",
                status_after=SystemStatus.FAILED,
                source="kubernetes"
            ),

            LogEvent(
                delay=4,
                level=LogLevel.ERROR,
                message="Service unavailable during pod restart.",
                status_after=SystemStatus.FAILED,
                source="order-api"
            ),
        ]

from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class FileDescriptorExhaustedScenario(Scenario):

    stop_after_failure = False

    def events(self):

        return [

            LogEvent(
                delay=0,
                level=LogLevel.WARN,
                message="Open file descriptor count approaching ulimit.",
                status_after=SystemStatus.DEGRADED,
                source="runtime"
            ),

            LogEvent(
                delay=1,
                level=LogLevel.WARN,
                message="Socket close is lagging behind accept rate.",
                status_after=SystemStatus.DEGRADED,
                source="runtime"
            ),

            LogEvent(
                delay=2,
                level=LogLevel.ERROR,
                message="Too many open files.",
                status_after=SystemStatus.FAILED,
                source="runtime"
            ),

            LogEvent(
                delay=3,
                level=LogLevel.ERROR,
                message="Failed to accept new client connection.",
                status_after=SystemStatus.FAILED,
                source="nginx"
            ),

            LogEvent(
                delay=4,
                level=LogLevel.ERROR,
                message="Application stopped serving new requests.",
                status_after=SystemStatus.FAILED,
                source="order-api"
            ),
        ]

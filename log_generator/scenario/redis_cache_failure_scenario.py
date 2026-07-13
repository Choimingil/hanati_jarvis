from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class RedisFailureScenario(Scenario):

    stop_after_failure = False

    def events(self):

        return [

            LogEvent(
                delay=0,
                level=LogLevel.WARN,
                message="Redis latency exceeded threshold.",
                status_after=SystemStatus.DEGRADED,
                source="redis"
            ),

            LogEvent(
                delay=1,
                level=LogLevel.WARN,
                message="Cache miss rate increasing.",
                status_after=SystemStatus.DEGRADED,
                source="cache"
            ),

            LogEvent(
                delay=2,
                level=LogLevel.ERROR,
                message="Redis connection lost.",
                status_after=SystemStatus.FAILED,
                source="redis"
            ),

            LogEvent(
                delay=3,
                level=LogLevel.ERROR,
                message="Falling back to database.",
                status_after=SystemStatus.FAILED,
                source="cache"
            ),

            LogEvent(
                delay=4,
                level=LogLevel.ERROR,
                message="Database overloaded by cache fallback.",
                status_after=SystemStatus.FAILED,
                source="database"
            ),
        ]
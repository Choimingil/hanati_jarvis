from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class ClockSkewDetectedScenario(Scenario):

    stop_after_failure = False

    def events(self):

        return [

            LogEvent(
                delay=0,
                level=LogLevel.INFO,
                message="NTP offset at 120 milliseconds.",
                status_after=SystemStatus.HEALTHY,
                source="system"
            ),

            LogEvent(
                delay=1,
                level=LogLevel.WARN,
                message="NTP offset grew beyond 5 seconds.",
                status_after=SystemStatus.DEGRADED,
                source="system"
            ),

            LogEvent(
                delay=2,
                level=LogLevel.ERROR,
                message="Clock skew detected against NTP server.",
                status_after=SystemStatus.FAILED,
                source="system"
            ),

            LogEvent(
                delay=3,
                level=LogLevel.ERROR,
                message="Token expiry check rejecting valid sessions.",
                status_after=SystemStatus.FAILED,
                source="auth"
            ),

            LogEvent(
                delay=4,
                level=LogLevel.ERROR,
                message="Scheduled settlement batch skipped its window.",
                status_after=SystemStatus.FAILED,
                source="order-api"
            ),
        ]

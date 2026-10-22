from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class ConfigurationMismatchScenario(Scenario):

    stop_after_failure = False

    def events(self):
        return [
            LogEvent(
                delay=0,
                level=LogLevel.WARN,
                message="Deployed configuration differs from the approved version.",
                status_after=SystemStatus.DEGRADED,
                source="config-validator"
            ),
            LogEvent(
                delay=1,
                level=LogLevel.ERROR,
                message="Configuration mismatch detected for order processing.",
                status_after=SystemStatus.FAILED,
                source="order-api"
            ),
            LogEvent(
                delay=2,
                level=LogLevel.WARN,
                message="Operator review required; no registered remediation script is available.",
                status_after=SystemStatus.FAILED,
                source="config-validator"
            ),
        ]

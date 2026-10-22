from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class CustomErrorScenario(Scenario):
    stop_after_failure = False

    def __init__(self, error_code):
        self.error_code = error_code

    def events(self):
        return [LogEvent(
            delay=0,
            level=LogLevel.ERROR,
            message=f"[{self.error_code}] New application error; no registered remediation script.",
            status_after=SystemStatus.FAILED,
            source="custom-scenario",
        )]

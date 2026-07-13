
from .scenario import Scenario
from .log_event import LogEvent


class DNSFailureScenario(Scenario):

    def events(self):

        return [

            LogEvent(
                delay=0,
                level="WARN",
                message="DNS lookup timeout."
            ),

            LogEvent(
                delay=1,
                level="WARN",
                message="Retrying DNS resolution."
            ),

            LogEvent(
                delay=2,
                level="ERROR",
                message="Failed to resolve service endpoint."
            ),

            LogEvent(
                delay=3,
                level="ERROR",
                message="HTTP request aborted."
            ),

            LogEvent(
                delay=4,
                level="ERROR",
                message="Circuit breaker opened."
            ),
        ]
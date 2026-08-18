from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class AuthTokenValidationFailureScenario(Scenario):

    stop_after_failure = False

    def events(self):

        return [

            LogEvent(
                delay=0,
                level=LogLevel.WARN,
                message="Auth service response time degraded.",
                status_after=SystemStatus.DEGRADED,
                source="auth-service"
            ),

            LogEvent(
                delay=1,
                level=LogLevel.WARN,
                message="Token signing key rotation in progress.",
                status_after=SystemStatus.DEGRADED,
                source="auth-service"
            ),

            LogEvent(
                delay=2,
                level=LogLevel.ERROR,
                message="Failed to validate access token.",
                status_after=SystemStatus.FAILED,
                source="auth-service"
            ),

            LogEvent(
                delay=3,
                level=LogLevel.ERROR,
                message="User session authentication rejected.",
                status_after=SystemStatus.FAILED,
                source="auth-service"
            ),

            LogEvent(
                delay=4,
                level=LogLevel.ERROR,
                message="Protected endpoints returning 401.",
                status_after=SystemStatus.FAILED,
                source="api"
            ),
        ]

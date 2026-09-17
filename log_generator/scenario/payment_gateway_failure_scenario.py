from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class PaymentGatewayFailureScenario(Scenario):

    stop_after_failure = False

    def events(self):

        return [

            LogEvent(
                delay=0,
                level=LogLevel.WARN,
                message="Payment gateway response time degraded.",
                status_after=SystemStatus.DEGRADED,
                source="payment"
            ),

            LogEvent(
                delay=1,
                level=LogLevel.WARN,
                message="Payment approval success rate dropped below 95%.",
                status_after=SystemStatus.DEGRADED,
                source="payment"
            ),

            LogEvent(
                delay=2,
                level=LogLevel.ERROR,
                message="Payment authorization failed at gateway.",
                status_after=SystemStatus.FAILED,
                source="payment"
            ),

            LogEvent(
                delay=3,
                level=LogLevel.ERROR,
                message="Settlement callback not received for pending orders.",
                status_after=SystemStatus.FAILED,
                source="payment"
            ),

            LogEvent(
                delay=4,
                level=LogLevel.ERROR,
                message="Orders stuck in PENDING_PAYMENT state.",
                status_after=SystemStatus.FAILED,
                source="order-api"
            ),
        ]

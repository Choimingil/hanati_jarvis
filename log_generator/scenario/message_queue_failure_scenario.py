from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class MessageQueueFailureScenario(Scenario):

    stop_after_failure = False

    def events(self):

        return [

            LogEvent(
                delay=0,
                level=LogLevel.WARN,
                message="Kafka consumer lag increasing.",
                status_after=SystemStatus.DEGRADED,
                source="kafka-consumer"
            ),

            LogEvent(
                delay=1,
                level=LogLevel.WARN,
                message="Kafka broker heartbeat missed.",
                status_after=SystemStatus.DEGRADED,
                source="kafka-consumer"
            ),

            LogEvent(
                delay=2,
                level=LogLevel.ERROR,
                message="Kafka broker connection lost.",
                status_after=SystemStatus.FAILED,
                source="kafka-consumer"
            ),

            LogEvent(
                delay=3,
                level=LogLevel.ERROR,
                message="Failed to publish order event.",
                status_after=SystemStatus.FAILED,
                source="order-events"
            ),

            LogEvent(
                delay=4,
                level=LogLevel.ERROR,
                message="Order processing queue backed up.",
                status_after=SystemStatus.FAILED,
                source="queue"
            ),
        ]

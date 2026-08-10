from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class SSLCertificateExpiredScenario(Scenario):

    stop_after_failure = False

    def events(self):

        return [

            LogEvent(
                delay=0,
                level=LogLevel.WARN,
                message="TLS certificate expiring within 24 hours.",
                status_after=SystemStatus.DEGRADED,
                source="tls"
            ),

            LogEvent(
                delay=1,
                level=LogLevel.WARN,
                message="Certificate renewal job did not complete.",
                status_after=SystemStatus.DEGRADED,
                source="cert-manager"
            ),

            LogEvent(
                delay=2,
                level=LogLevel.ERROR,
                message="SSL certificate has expired.",
                status_after=SystemStatus.FAILED,
                source="tls"
            ),

            LogEvent(
                delay=3,
                level=LogLevel.ERROR,
                message="HTTPS handshake failed for incoming requests.",
                status_after=SystemStatus.FAILED,
                source="nginx"
            ),

            LogEvent(
                delay=4,
                level=LogLevel.ERROR,
                message="Client connections rejected due to invalid certificate.",
                status_after=SystemStatus.FAILED,
                source="gateway"
            ),
        ]

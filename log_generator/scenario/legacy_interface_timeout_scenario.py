from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class LegacyInterfaceTimeoutScenario(Scenario):
    """에러별 예외 처리(보류 + 알림) 검증용.

    대외기관 레거시 전문 연동 지연처럼 당장 해결하기 어려운 오류를 발생시킨다.
    기본 예외 처리 규칙(RULE-LEGACY-INTERFACE-TIMEOUT)에 의해 자동 보류되고, 같은
    오류가 다시 발생하면 보류를 유지한 채 알림만 생성되는지 확인한다.
    """

    stop_after_failure = False

    def events(self):
        return [
            LogEvent(
                delay=0,
                level=LogLevel.WARN,
                message="Legacy interface response delayed over 10 seconds.",
                status_after=SystemStatus.DEGRADED,
                source="legacy-gateway",
            ),
            LogEvent(
                delay=1,
                level=LogLevel.ERROR,
                message="Legacy interface timeout from external institution gateway.",
                status_after=SystemStatus.FAILED,
                source="legacy-gateway",
            ),
            LogEvent(
                delay=2,
                level=LogLevel.ERROR,
                message="Legacy interface timeout from external institution gateway.",
                status_after=SystemStatus.FAILED,
                source="legacy-gateway",
            ),
        ]

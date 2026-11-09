from scenario.scenario import Scenario
from scenario.log_event import LogEvent
from logger.log_constants import LogLevel, SystemStatus


class DiskFullRecurrenceScenario(Scenario):
    """장애 이력 확인 검증용.

    기존 DISK_FULL과 같은 오류 코드이지만 메시지가 달라 별도 장애로 생성된다.
    먼저 '디스크 부족 (DISK_FULL)'을 조치·완료한 뒤 실행하면 상세 화면의
    '과거 유사 장애 조치 이력'에 이전 조치 방법이 표시된다.
    """

    stop_after_failure = False

    def events(self):
        return [
            LogEvent(
                delay=0,
                level=LogLevel.WARN,
                message="Settlement batch disk usage exceeded 95%.",
                status_after=SystemStatus.DEGRADED,
                source="batch-storage",
            ),
            LogEvent(
                delay=1,
                level=LogLevel.ERROR,
                message="No space left on device while writing settlement batch file.",
                status_after=SystemStatus.FAILED,
                source="batch-storage",
            ),
        ]

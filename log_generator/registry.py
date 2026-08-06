"""장애 시나리오 key -> (클래스, 표시 라벨, 감지될 에러 코드) 매핑.

main.py(무한 루프로 랜덤 발생)와 trigger.py(웹 콘솔에서 특정 시나리오
1회 강제 실행) 양쪽이 이 목록을 공유한다. 에러 코드는
error_detector.ERROR_PATTERNS / config.ERROR_RULES와 1:1로 맞춰져 있다.
"""

from scenario.database_connection_failure_scenario import (
    DatabaseConnectionFailureScenario,
)
from scenario.disk_full_scenario import DiskFullScenario
from scenario.dns_failure_scenario import DNSFailureScenario
from scenario.external_api_failure_scenario import (
    ExternalAPIFailureScenario,
)
from scenario.memory_leak_scenario import MemoryLeakScenario
from scenario.redis_cache_failure_scenario import (
    RedisFailureScenario,
)


SCENARIO_REGISTRY = {
    "disk_full": (
        DiskFullScenario,
        "디스크 부족 (DISK_FULL)",
        "DISK_FULL",
    ),
    "dns_failure": (
        DNSFailureScenario,
        "DNS 해석 실패 (DNS_RESOLUTION_FAILURE)",
        "DNS_RESOLUTION_FAILURE",
    ),
    "db_connection_failure": (
        DatabaseConnectionFailureScenario,
        "DB 커넥션 실패 (DB_CONNECTION_FAILURE)",
        "DB_CONNECTION_FAILURE",
    ),
    "external_api_failure": (
        ExternalAPIFailureScenario,
        "외부 API 장애 (EXTERNAL_API_FAILURE)",
        "EXTERNAL_API_FAILURE",
    ),
    "memory_leak": (
        MemoryLeakScenario,
        "메모리 릭 (MEMORY_LEAK)",
        "MEMORY_LEAK",
    ),
    "redis_failure": (
        RedisFailureScenario,
        "Redis 연결 끊김 (REDIS_CONNECTION_FAILURE)",
        "REDIS_CONNECTION_FAILURE",
    ),
}

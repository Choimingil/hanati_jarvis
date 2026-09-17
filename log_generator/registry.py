"""장애 시나리오 key -> (클래스, 표시 라벨, 감지될 에러 코드) 매핑.

main.py(무한 루프로 랜덤 발생)와 trigger.py(웹 콘솔에서 특정 시나리오
1회 강제 실행) 양쪽이 이 목록을 공유한다. 에러 코드는
error_detector.ERROR_PATTERNS / config.ERROR_RULES와 1:1로 맞춰져 있다.
"""

from scenario.auth_token_validation_failure_scenario import (
    AuthTokenValidationFailureScenario,
)
from scenario.container_oom_killed_scenario import (
    ContainerOOMKilledScenario,
)
from scenario.database_connection_failure_scenario import (
    DatabaseConnectionFailureScenario,
)
from scenario.disk_full_scenario import DiskFullScenario
from scenario.dns_failure_scenario import DNSFailureScenario
from scenario.external_api_failure_scenario import (
    ExternalAPIFailureScenario,
)
from scenario.memory_leak_scenario import MemoryLeakScenario
from scenario.message_queue_failure_scenario import (
    MessageQueueFailureScenario,
)
from scenario.rate_limit_exceeded_scenario import (
    RateLimitExceededScenario,
)
from scenario.redis_cache_failure_scenario import (
    RedisFailureScenario,
)
from scenario.ssl_certificate_expired_scenario import (
    SSLCertificateExpiredScenario,
)
from scenario.thread_pool_exhausted_scenario import (
    ThreadPoolExhaustedScenario,
)
from scenario.database_deadlock_scenario import (
    DatabaseDeadlockScenario,
)
from scenario.connection_pool_exhausted_scenario import (
    ConnectionPoolExhaustedScenario,
)
from scenario.database_replication_lag_scenario import (
    DatabaseReplicationLagScenario,
)
from scenario.file_descriptor_exhausted_scenario import (
    FileDescriptorExhaustedScenario,
)
from scenario.upstream_gateway_timeout_scenario import (
    UpstreamGatewayTimeoutScenario,
)
from scenario.payment_gateway_failure_scenario import (
    PaymentGatewayFailureScenario,
)
from scenario.clock_skew_detected_scenario import (
    ClockSkewDetectedScenario,
)
from scenario.pod_crashloop_backoff_scenario import (
    PodCrashLoopBackOffScenario,
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
    "message_queue_failure": (
        MessageQueueFailureScenario,
        "메시지 큐 연결 끊김 (MESSAGE_QUEUE_CONNECTION_LOST)",
        "MESSAGE_QUEUE_CONNECTION_LOST",
    ),
    "ssl_certificate_expired": (
        SSLCertificateExpiredScenario,
        "SSL 인증서 만료 (SSL_CERTIFICATE_EXPIRED)",
        "SSL_CERTIFICATE_EXPIRED",
    ),
    "thread_pool_exhausted": (
        ThreadPoolExhaustedScenario,
        "스레드 풀 고갈 (THREAD_POOL_EXHAUSTED)",
        "THREAD_POOL_EXHAUSTED",
    ),
    "rate_limit_exceeded": (
        RateLimitExceededScenario,
        "레이트 리밋 초과 (RATE_LIMIT_EXCEEDED)",
        "RATE_LIMIT_EXCEEDED",
    ),
    "auth_token_validation_failure": (
        AuthTokenValidationFailureScenario,
        "인증 토큰 검증 실패 (AUTH_TOKEN_VALIDATION_FAILURE)",
        "AUTH_TOKEN_VALIDATION_FAILURE",
    ),
    "container_oom_killed": (
        ContainerOOMKilledScenario,
        "컨테이너 OOM Kill (CONTAINER_OOM_KILLED)",
        "CONTAINER_OOM_KILLED",
    ),
    "db_deadlock": (
        DatabaseDeadlockScenario,
        "DB 데드락 (DB_DEADLOCK)",
        "DB_DEADLOCK",
    ),
    "connection_pool_exhausted": (
        ConnectionPoolExhaustedScenario,
        "DB 커넥션 풀 고갈 (CONNECTION_POOL_EXHAUSTED)",
        "CONNECTION_POOL_EXHAUSTED",
    ),
    "db_replication_lag": (
        DatabaseReplicationLagScenario,
        "DB 복제 지연 (DB_REPLICATION_LAG)",
        "DB_REPLICATION_LAG",
    ),
    "file_descriptor_exhausted": (
        FileDescriptorExhaustedScenario,
        "파일 디스크립터 고갈 (FILE_DESCRIPTOR_EXHAUSTED)",
        "FILE_DESCRIPTOR_EXHAUSTED",
    ),
    "upstream_gateway_timeout": (
        UpstreamGatewayTimeoutScenario,
        "업스트림 게이트웨이 타임아웃 (UPSTREAM_GATEWAY_TIMEOUT)",
        "UPSTREAM_GATEWAY_TIMEOUT",
    ),
    "payment_gateway_failure": (
        PaymentGatewayFailureScenario,
        "결제 게이트웨이 장애 (PAYMENT_GATEWAY_FAILURE)",
        "PAYMENT_GATEWAY_FAILURE",
    ),
    "clock_skew_detected": (
        ClockSkewDetectedScenario,
        "시각 동기 이탈 (CLOCK_SKEW_DETECTED)",
        "CLOCK_SKEW_DETECTED",
    ),
    "pod_crashloop_backoff": (
        PodCrashLoopBackOffScenario,
        "컨테이너 재시작 루프 (POD_CRASHLOOP_BACKOFF)",
        "POD_CRASHLOOP_BACKOFF",
    ),
}

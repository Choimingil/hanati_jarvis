"""추천 조치를 스크립트 하나(script_id)가 아니라 Runbook 단위로 다루기
위한 운영 메타데이터.

config.REMEDIATION_SCRIPTS의 각 조치 스크립트에 대해, 운영자가 승인
여부를 판단하는 데 필요한 정보(장애 설명/조치 내용/예상 영향/실패 시
대응)를 붙인다. "과거 실행 성공/실패 횟수"는 여기 없다 - 정적으로
박아두면 바로 거짓말이 되므로, application-remediations 인덱스에서
실시간 집계한다 (ElasticLogRepository.remediation_history 참고).
"""

REMEDIATION_RUNBOOKS: dict[str, dict[str, str]] = {
    "update_jdbc_driver": {
        "incident": "order-api DB 인증 실패 (ORA-28040)",
        "action": "order-api 인스턴스의 JDBC 드라이버를 최신 버전으로 교체 후 재기동",
        "expected_impact": "교체 대상 인스턴스가 약 30초간 트래픽에서 제외됨",
        "rollback": "이전 버전 드라이버로 롤백하고 DBA에게 에스컬레이션",
    },
    "modify_sqlnet": {
        "incident": "order-api DB 인증 실패 (ORA-28040)",
        "action": "sqlnet.ora의 SQLNET.ALLOWED_LOGON_VERSION_SERVER 설정 수정 후 리스너 재기동",
        "expected_impact": "설정 반영 중 신규 DB 연결이 수 초간 지연됨",
        "rollback": "sqlnet.ora를 이전 설정으로 복원하고 DBA에게 에스컬레이션",
    },
    "compress_old_logs": {
        "incident": "order-api 디스크 사용량 포화 (DISK_FULL)",
        "action": "오래된 로그 파일을 압축해 디스크 공간 확보",
        "expected_impact": "압축 작업 중 해당 인스턴스 로그 쓰기가 일시적으로 지연될 수 있음",
        "rollback": "압축된 로그를 원복하고 인프라팀에게 에스컬레이션",
    },
    "cleanup_temp_files": {
        "incident": "order-api 디스크 사용량 포화 (DISK_FULL)",
        "action": "임시 파일을 정리해 디스크 공간 확보",
        "expected_impact": "정리 대상 임시 파일에 의존하는 작업이 있으면 일시적으로 실패할 수 있음",
        "rollback": "삭제된 임시 파일은 복구하지 않고 인프라팀에게 에스컬레이션",
    },
    "flush_dns_cache": {
        "incident": "order-api DNS 해석 실패 (DNS_RESOLUTION_FAILURE)",
        "action": "DNS 캐시 초기화",
        "expected_impact": "초기화 직후 DNS 조회가 일시적으로 느려질 수 있음",
        "rollback": "변경 사항 없음 - 네트워크팀에게 에스컬레이션",
    },
    "restart_dns_resolver": {
        "incident": "order-api DNS 해석 실패 (DNS_RESOLUTION_FAILURE)",
        "action": "DNS 리졸버 프로세스 재시작",
        "expected_impact": "재시작 중 수 초간 DNS 조회 실패 가능",
        "rollback": "리졸버를 이전 상태로 복구하고 네트워크팀에게 에스컬레이션",
    },
    "restart_db_connection_pool": {
        "incident": "order-api DB Connection Pool 100% 사용",
        "action": "order-api 인스턴스 6개 중 1개 재시작",
        "expected_impact": "해당 인스턴스가 약 20초간 트래픽에서 제외됨",
        "rollback": "인스턴스를 이전 상태로 복구하고 DBA에게 에스컬레이션",
    },
    "failover_database": {
        "incident": "order-api DB Connection Pool 100% 사용",
        "action": "예비(standby) DB로 페일오버 전환",
        "expected_impact": "전환 중 최대 수 초간 쓰기 요청이 지연됨",
        "rollback": "기존 primary DB로 되돌리고 DBA에게 에스컬레이션",
    },
    "enable_circuit_breaker": {
        "incident": "order-api 외부 API 장애 (EXTERNAL_API_FAILURE)",
        "action": "외부 API 호출 경로에 서킷 브레이커 활성화",
        "expected_impact": "서킷 브레이커가 열려있는 동안 해당 기능이 대체 응답(fallback)으로 처리됨",
        "rollback": "서킷 브레이커를 비활성화하고 API팀에게 에스컬레이션",
    },
    "switch_api_endpoint": {
        "incident": "order-api 외부 API 장애 (EXTERNAL_API_FAILURE)",
        "action": "예비 엔드포인트로 외부 API 호출 전환",
        "expected_impact": "전환 중 일부 요청이 수 초간 지연될 수 있음",
        "rollback": "기존 엔드포인트로 되돌리고 API팀에게 에스컬레이션",
    },
    "restart_application": {
        "incident": "order-api 메모리 릭 (MEMORY_LEAK)",
        "action": "order-api 인스턴스 6개 중 1개 재시작",
        "expected_impact": "해당 인스턴스가 약 20초간 트래픽에서 제외됨",
        "rollback": "재시작이 실패하면 인스턴스를 격리하고 인프라팀에게 에스컬레이션",
    },
    "increase_heap_size": {
        "incident": "order-api 메모리 릭 (MEMORY_LEAK)",
        "action": "JVM 힙 메모리 크기 증설 후 재기동",
        "expected_impact": "재기동 대상 인스턴스가 약 30초간 트래픽에서 제외됨",
        "rollback": "이전 힙 설정으로 되돌리고 인프라팀에게 에스컬레이션",
    },
    "restart_redis": {
        "incident": "order-api Redis 연결 끊김 (REDIS_CONNECTION_FAILURE)",
        "action": "Redis 인스턴스 재시작",
        "expected_impact": "재시작 중 수 초간 캐시 미스가 증가함",
        "rollback": "Redis를 이전 상태로 복구하고 인프라팀에게 에스컬레이션",
    },
    "clear_redis_cache": {
        "incident": "order-api Redis 연결 끊김 (REDIS_CONNECTION_FAILURE)",
        "action": "Redis 캐시 비우기",
        "expected_impact": "캐시 워밍업이 끝날 때까지 DB 부하가 일시적으로 증가함",
        "rollback": "변경 사항 없음 - 인프라팀에게 에스컬레이션",
    },
    "kill_blocking_session": {
        "incident": "order-api 주문 테이블 데드락 (DB_DEADLOCK)",
        "action": "데드락 그래프에서 차단 세션을 찾아 강제 종료",
        "expected_impact": "종료된 세션의 진행 중 트랜잭션이 롤백됨",
        "rollback": "롤백된 주문을 재처리하고 DBA에게 에스컬레이션",
    },
    "retry_failed_transactions": {
        "incident": "order-api 주문 테이블 데드락 (DB_DEADLOCK)",
        "action": "롤백된 주문 트랜잭션을 백오프를 두고 재시도",
        "expected_impact": "재시도 중 주문 처리 지연이 수 초간 발생함",
        "rollback": "재시도를 중단하고 수동 정산 후 DBA에게 에스컬레이션",
    },
    "increase_connection_pool_size": {
        "incident": "order-api DB 커넥션 풀 고갈 (CONNECTION_POOL_EXHAUSTED)",
        "action": "커넥션 풀 최대 크기를 상향하고 설정을 재적용",
        "expected_impact": "설정 반영 중 신규 연결이 수 초간 지연됨",
        "rollback": "이전 풀 크기로 되돌리고 DBA와 함께 쿼리 지연 원인을 조사",
    },
    "route_reads_to_primary": {
        "incident": "order-api 읽기 복제본 지연 (DB_REPLICATION_LAG)",
        "action": "복제 지연이 해소될 때까지 읽기 쿼리를 주 DB로 라우팅",
        "expected_impact": "주 DB 부하가 증가하고 쓰기 지연이 커질 수 있음",
        "rollback": "읽기 라우팅을 복제본으로 되돌리고 DBA에게 에스컬레이션",
    },
    "restart_replication": {
        "incident": "order-api 읽기 복제본 지연 (DB_REPLICATION_LAG)",
        "action": "복제본의 복제 스레드를 중지 후 재시작",
        "expected_impact": "재시작 중 복제본 조회가 수 초간 실패할 수 있음",
        "rollback": "복제를 중단하고 복제본을 재구축한 뒤 DBA에게 에스컬레이션",
    },
    "increase_fd_limit": {
        "incident": "order-api 파일 디스크립터 고갈 (FILE_DESCRIPTOR_EXHAUSTED)",
        "action": "프로세스 ulimit(nofile)을 상향하고 서비스를 재기동",
        "expected_impact": "재기동 중 해당 인스턴스가 약 30초간 트래픽에서 제외됨",
        "rollback": "이전 한도로 되돌리고 FD 누수 지점을 애플리케이션 팀과 조사",
    },
    "drain_unhealthy_upstream": {
        "incident": "order-api 업스트림 게이트웨이 타임아웃 (UPSTREAM_GATEWAY_TIMEOUT)",
        "action": "헬스체크에 실패한 업스트림 노드를 풀에서 드레인",
        "expected_impact": "남은 노드의 부하가 증가함",
        "rollback": "노드를 다시 투입하고 네트워크팀에게 에스컬레이션",
    },
    "increase_proxy_timeout": {
        "incident": "order-api 업스트림 게이트웨이 타임아웃 (UPSTREAM_GATEWAY_TIMEOUT)",
        "action": "리버스 프록시의 upstream read timeout을 상향하고 설정 재적용",
        "expected_impact": "느린 요청이 연결을 더 오래 점유해 동시성이 줄어듦",
        "rollback": "이전 타임아웃으로 복원하고 업스트림 지연 원인을 조사",
    },
    "switch_payment_provider": {
        "incident": "order-api 결제 승인 실패 (PAYMENT_GATEWAY_FAILURE)",
        "action": "결제 라우팅을 예비 PG사로 전환",
        "expected_impact": "전환 중 진행 중이던 결제 요청이 실패할 수 있음",
        "rollback": "주 PG사로 롤백하고 결제팀·PG사에 동시 에스컬레이션",
    },
    "enable_payment_retry_queue": {
        "incident": "order-api 결제 승인 실패 (PAYMENT_GATEWAY_FAILURE)",
        "action": "실패한 결제 요청을 재시도 큐에 적재해 지연 처리",
        "expected_impact": "고객에게 결제 완료 통보가 수 분 지연됨",
        "rollback": "큐를 비우고 수동 정산 후 결제팀에게 에스컬레이션",
    },
    "resync_ntp_time": {
        "incident": "order-api 노드 시각 동기 이탈 (CLOCK_SKEW_DETECTED)",
        "action": "NTP 서버와 시각을 강제로 재동기화",
        "expected_impact": "시각 점프로 진행 중인 타이머·세션이 영향을 받을 수 있음",
        "rollback": "수동으로 시각을 보정하고 인프라팀에게 에스컬레이션",
    },
    "restart_time_service": {
        "incident": "order-api 노드 시각 동기 이탈 (CLOCK_SKEW_DETECTED)",
        "action": "chronyd/ntpd 시각 동기 데몬을 재시작",
        "expected_impact": "재시작 직후 수 초간 시각 보정이 진행됨",
        "rollback": "데몬을 이전 설정으로 되돌리고 인프라팀에게 에스컬레이션",
    },
    "rollback_deployment": {
        "incident": "order-api Pod 재시작 루프 (POD_CRASHLOOP_BACKOFF)",
        "action": "마지막으로 정상이던 리비전으로 디플로이먼트를 롤백",
        "expected_impact": "롤백 중 롤링 업데이트로 일부 요청이 재시도됨",
        "rollback": "롤백을 중단하고 릴리스 담당자에게 에스컬레이션",
    },
    "increase_pod_resources": {
        "incident": "order-api Pod 재시작 루프 (POD_CRASHLOOP_BACKOFF)",
        "action": "Pod의 CPU/메모리 requests·limits를 상향하고 재배포",
        "expected_impact": "재배포 중 순차적으로 Pod가 교체됨",
        "rollback": "이전 리소스 설정으로 되돌리고 플랫폼팀에게 에스컬레이션",
    },
}

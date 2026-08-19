import os


API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8080"))

METRICS_API_URL = os.getenv(
    "METRICS_API_URL", "http://127.0.0.1:8080/api/v1/metrics"
)
METRICS_COLLECT_INTERVAL_SECONDS = int(
    os.getenv("METRICS_COLLECT_INTERVAL_SECONDS", "30")
)
METRICS_PROCESS_LIMIT = int(
    os.getenv("METRICS_PROCESS_LIMIT", "20")
)
METRICS_RETENTION_ENABLED = (
    os.getenv("METRICS_RETENTION_ENABLED", "true").lower()
    == "true"
)
METRICS_RETENTION_DAYS = int(
    os.getenv("METRICS_RETENTION_DAYS", "14")
)
METRICS_RETENTION_INTERVAL_SECONDS = int(
    os.getenv("METRICS_RETENTION_INTERVAL_SECONDS", "86400")
)
INCIDENT_COOLDOWN_MINUTES = int(
    os.getenv("INCIDENT_COOLDOWN_MINUTES", "5")
)
ANOMALY_MEMORY_PERCENT_THRESHOLD = float(
    os.getenv("ANOMALY_MEMORY_PERCENT_THRESHOLD", "90")
)
ANOMALY_MEMORY_GROWTH_THRESHOLD = float(
    os.getenv("ANOMALY_MEMORY_GROWTH_THRESHOLD", "10")
)
ANOMALY_DISK_PERCENT_THRESHOLD = float(
    os.getenv("ANOMALY_DISK_PERCENT_THRESHOLD", "90")
)
ANOMALY_CLOSE_WAIT_THRESHOLD = int(
    os.getenv("ANOMALY_CLOSE_WAIT_THRESHOLD", "100")
)
ANOMALY_NETWORK_ERROR_GROWTH_THRESHOLD = int(
    os.getenv("ANOMALY_NETWORK_ERROR_GROWTH_THRESHOLD", "20")
)
RESOURCE_CPU_PERCENT_THRESHOLD = float(
    os.getenv("RESOURCE_CPU_PERCENT_THRESHOLD", "90")
)
RESOURCE_FALLBACK_CONFIDENCE_THRESHOLD = float(
    os.getenv("RESOURCE_FALLBACK_CONFIDENCE_THRESHOLD", "60")
)

SCRIPT_TIMEOUT_SECONDS = int(
    os.getenv("SCRIPT_TIMEOUT_SECONDS", "30")
)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _runbook(name: str) -> str:
    return os.path.join(BASE_DIR, "test-runbooks", f"{name}.sh")


# log_generator가 발생시키는 각 장애 시나리오(+ 기존 ORA-28040)에 대한
# 진단/조치 규칙. error_detector.ERROR_PATTERNS의 코드와 1:1로 매핑된다.
ERROR_RULES = {
    "ORA-28040": {
        "diagnostic_scripts": [
            "check_jdbc_version",
            "check_sqlnet",
        ],
        "remediation_candidates": [
            "update_jdbc_driver",
            "modify_sqlnet",
        ],
        "auto_diagnose": True,
        "auto_remediate": False,
    },
    "DISK_FULL": {
        "diagnostic_scripts": [
            "check_disk_usage",
            "check_large_files",
        ],
        "remediation_candidates": [
            "compress_old_logs",
            "cleanup_temp_files",
        ],
        "auto_diagnose": True,
        "auto_remediate": False,
    },
    "DNS_RESOLUTION_FAILURE": {
        "diagnostic_scripts": [
            "check_dns_resolution",
        ],
        "remediation_candidates": [
            "flush_dns_cache",
            "restart_dns_resolver",
        ],
        "auto_diagnose": True,
        "auto_remediate": False,
    },
    "DB_CONNECTION_FAILURE": {
        "diagnostic_scripts": [
            "check_db_connection",
        ],
        "remediation_candidates": [
            "restart_db_connection_pool",
            "failover_database",
        ],
        "auto_diagnose": True,
        "auto_remediate": False,
    },
    "EXTERNAL_API_FAILURE": {
        "diagnostic_scripts": [
            "check_external_api",
        ],
        "remediation_candidates": [
            "enable_circuit_breaker",
            "switch_api_endpoint",
        ],
        "auto_diagnose": True,
        "auto_remediate": False,
    },
    "MEMORY_LEAK": {
        "diagnostic_scripts": [
            "check_memory_usage",
        ],
        "remediation_candidates": [
            "restart_application",
            "increase_heap_size",
        ],
        "auto_diagnose": True,
        "auto_remediate": False,
    },
    "REDIS_CONNECTION_FAILURE": {
        "diagnostic_scripts": [
            "check_redis_status",
        ],
        "remediation_candidates": [
            "restart_redis",
            "clear_redis_cache",
        ],
        "auto_diagnose": True,
        "auto_remediate": False,
    },
    "MESSAGE_QUEUE_CONNECTION_LOST": {
        "diagnostic_scripts": [
            "check_kafka_connection",
        ],
        "remediation_candidates": [
            "restart_kafka_consumer",
            "failover_message_broker",
        ],
        "auto_diagnose": True,
        "auto_remediate": False,
    },
    "SSL_CERTIFICATE_EXPIRED": {
        "diagnostic_scripts": [
            "check_ssl_certificate",
        ],
        "remediation_candidates": [
            "renew_ssl_certificate",
            "reload_tls_config",
        ],
        "auto_diagnose": True,
        "auto_remediate": False,
    },
    "THREAD_POOL_EXHAUSTED": {
        "diagnostic_scripts": [
            "check_thread_pool_usage",
        ],
        "remediation_candidates": [
            "increase_thread_pool_size",
            "restart_application",
        ],
        "auto_diagnose": True,
        "auto_remediate": False,
    },
    "RATE_LIMIT_EXCEEDED": {
        # 대응 스크립트 없음 - 감지되면 runbook 추천 대신
        # resource fallback(운영자 조사) 경로로 빠진다
        # (RecommendationQualityGate.requires_fallback의
        # "no_remediation_candidates").
        "diagnostic_scripts": [],
        "remediation_candidates": [],
        "auto_diagnose": True,
        "auto_remediate": False,
    },
    "AUTH_TOKEN_VALIDATION_FAILURE": {
        "diagnostic_scripts": [
            "check_auth_service_health",
        ],
        "remediation_candidates": [
            "rotate_signing_key",
            "restart_auth_service",
        ],
        "auto_diagnose": True,
        "auto_remediate": False,
    },
    "CONTAINER_OOM_KILLED": {
        "diagnostic_scripts": [
            "check_container_memory_limits",
        ],
        "remediation_candidates": [
            "increase_memory_limit",
            "restart_application",
        ],
        "auto_diagnose": True,
        "auto_remediate": False,
    },
}


# 각 스크립트 id에 대한 사람이 읽을 설명. 웹 UI 표시와 추천 사유 문구에 쓰인다.
SCRIPT_DESCRIPTIONS = {
    # 진단(diagnostic)
    "check_jdbc_version": "JDBC 드라이버 버전 점검",
    "check_sqlnet": "sqlnet.ora 설정 점검",
    "check_disk_usage": "디스크 사용량 점검",
    "check_large_files": "대용량 파일 탐색",
    "check_dns_resolution": "DNS 해석 상태 점검",
    "check_db_connection": "DB 연결 상태 점검",
    "check_external_api": "외부 API 헬스 점검",
    "check_memory_usage": "메모리 사용량 점검",
    "check_redis_status": "Redis 상태 점검",
    # 조치(remediation)
    "update_jdbc_driver": "JDBC 드라이버 최신 버전으로 업데이트",
    "modify_sqlnet": "sqlnet.ora 인증 설정 수정",
    "compress_old_logs": "오래된 로그 압축으로 디스크 확보",
    "cleanup_temp_files": "임시 파일 정리로 디스크 확보",
    "flush_dns_cache": "DNS 캐시 초기화",
    "restart_dns_resolver": "DNS 리졸버 재시작",
    "restart_db_connection_pool": "DB 커넥션 풀 재시작",
    "failover_database": "예비 DB로 페일오버 전환",
    "enable_circuit_breaker": "서킷 브레이커를 열어 장애 전파 차단",
    "switch_api_endpoint": "외부 API 예비 엔드포인트로 전환",
    "restart_application": "애플리케이션 재시작으로 메모리 회수",
    "increase_heap_size": "힙 메모리 증설 후 재기동",
    "restart_redis": "Redis 인스턴스 재시작",
    "clear_redis_cache": "Redis 캐시 비우기",
    "check_kafka_connection": "Kafka 브로커 연결 상태 점검",
    "restart_kafka_consumer": "Kafka 컨슈머 재시작",
    "failover_message_broker": "예비 메시지 브로커로 페일오버 전환",
    "check_ssl_certificate": "SSL 인증서 유효기간 점검",
    "renew_ssl_certificate": "SSL 인증서 갱신",
    "reload_tls_config": "TLS 설정 재적용",
    "check_thread_pool_usage": "스레드 풀 사용률 점검",
    "increase_thread_pool_size": "스레드 풀 크기 증설",
    "check_auth_service_health": "인증 서비스 상태 점검",
    "rotate_signing_key": "토큰 서명 키 로테이션",
    "restart_auth_service": "인증 서비스 재시작",
    "check_container_memory_limits": "컨테이너 메모리 제한(cgroup) 점검",
    "increase_memory_limit": "컨테이너 메모리 제한 증설",
}


# ERROR_RULES에 등장하는 모든 스크립트 id를 실제 파일 경로로 매핑.
# run_script()의 allowlist 역할을 한다 (여기 없는 id는 실행 불가).
DIAGNOSTIC_SCRIPTS = {
    script_id: _runbook(script_id)
    for rule in ERROR_RULES.values()
    for script_id in rule["diagnostic_scripts"]
}

# 운영자가 추천안 중 하나를 승인했을 때 실행되는 원격조치 스크립트.
REMEDIATION_SCRIPTS = {
    script_id: _runbook(script_id)
    for rule in ERROR_RULES.values()
    for script_id in rule["remediation_candidates"]
}


# "qdrant" / "elastic" / "hybrid" (기본값) 중 선택. mock 없음 - Qdrant/
# Elasticsearch가 꺼져 있으면 case_searcher 요청은 그대로 실패한다.
# - qdrant  : QdrantCaseSearcher (벡터 유사도 검색)
# - elastic : ElasticCaseSearcher (키워드 검색)
# - hybrid  : 위 둘을 함께 조회해서 병합 (Qdrant + Elasticsearch 모두 근거로 추천)
CASE_SEARCHER_BACKEND = os.getenv(
    "CASE_SEARCHER_BACKEND", "hybrid"
)

# scripts/dev_infra.sh가 띄우는 Qdrant 컨테이너 기본 주소.
# 반드시 실제 Qdrant 서버를 가리켜야 한다 (로컬 파일 fallback 없음).
QDRANT_URL = os.getenv(
    "QDRANT_URL", "http://localhost:6333"
)
QDRANT_COLLECTION = os.getenv(
    "QDRANT_COLLECTION", "incident_cases"
)

EMBEDDING_MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL_NAME", "BAAI/bge-m3"
)
# "BAAI/bge-m3" 모델의 임베딩 차원 수
EMBEDDING_VECTOR_SIZE = int(
    os.getenv("EMBEDDING_VECTOR_SIZE", "1024")
)


# LLMRecommendationGenerator. LLM(OpenAI 호환)에게 오류 원인과 추천
# 스크립트 랭킹을 물어본다. OPENAI_API_KEY가 없으면 llm_agent 쪽
# 결정론적 fallback 랭킹으로 동작한다 - 이건 mock이 아니라 LLM 자체의
# 내부 fallback이라 그대로 둔다.
RECOMMENDATION_BACKEND = "llm"


# repository는 항상 ElasticLogRepository. mock 없음 - Elasticsearch가
# 꺼져 있으면 로그/진단/추천 저장 요청이 그대로 실패한다.
LOG_REPOSITORY_BACKEND = "elastic"

# scripts/dev_infra.sh가 띄우는 Elasticsearch 컨테이너는 개발용으로
# xpack.security.enabled=false, 즉 http/무인증이라 기본값도 맞춰둔다.
ELASTICSEARCH_URL = os.getenv(
    "ELASTICSEARCH_URL", "http://localhost:9200"
)
ELASTICSEARCH_USER = os.getenv(
    "ELASTICSEARCH_USER", "elastic"
)
# 자격증명은 반드시 환경변수로 주입한다 (기본값 없음).
ELASTICSEARCH_PASSWORD = os.getenv(
    "ELASTICSEARCH_PASSWORD", ""
)
ELASTICSEARCH_VERIFY_CERTS = (
    os.getenv(
        "ELASTICSEARCH_VERIFY_CERTS", "false"
    ).lower()
    == "true"
)

ELASTIC_LOG_INDEX = os.getenv(
    "ELASTIC_LOG_INDEX", "application-logs"
)
ELASTIC_DIAGNOSIS_INDEX = os.getenv(
    "ELASTIC_DIAGNOSIS_INDEX",
    "application-diagnoses",
)
ELASTIC_RECOMMENDATION_INDEX = os.getenv(
    "ELASTIC_RECOMMENDATION_INDEX",
    "application-recommendations",
)
ELASTIC_REMEDIATION_INDEX = os.getenv(
    "ELASTIC_REMEDIATION_INDEX",
    "application-remediations",
)
ELASTIC_METRICS_INDEX = os.getenv(
    "ELASTIC_METRICS_INDEX", "application-system-metrics"
)
ELASTIC_RECOVERY_INDEX = os.getenv(
    "ELASTIC_RECOVERY_INDEX", "application-recovery-verifications"
)
ELASTIC_RESOURCE_GUIDANCE_INDEX = os.getenv(
    "ELASTIC_RESOURCE_GUIDANCE_INDEX", "application-resource-guidance"
)
ELASTIC_OPERATOR_FEEDBACK_INDEX = os.getenv(
    "ELASTIC_OPERATOR_FEEDBACK_INDEX", "application-operator-feedback"
)

# Qdrant의 incident_cases 컬렉션과 동일한 과거 대응 사례를
# 담아두는 Elasticsearch 인덱스 (incident_cases.py로 시딩).
ELASTIC_INCIDENT_CASES_INDEX = os.getenv(
    "ELASTIC_INCIDENT_CASES_INDEX", "incident-cases"
)

# 운영 중인 장애 상태. 검증된 과거 사례(incident-cases)와 분리한다.
ELASTIC_INCIDENT_INDEX = os.getenv(
    "ELASTIC_INCIDENT_INDEX", "application-incidents"
)
RECOMMENDATION_TTL_MINUTES = int(
    os.getenv("RECOMMENDATION_TTL_MINUTES", "30")
)

# 장애 분석(진단 스크립트 실행 + 과거 사례 검색 + LLM 추천 생성)을 HTTP 요청
# 처리 스레드에서 동기로 돌리지 않고 백그라운드 워커에서 비동기로 처리할지
# 여부. false로 두면 기존처럼 요청 스레드에서 끝까지 동기 처리한다.
INCIDENT_ANALYSIS_ASYNC = (
    os.getenv("INCIDENT_ANALYSIS_ASYNC", "true").lower() == "true"
)
# 비동기 분석을 처리하는 백그라운드 워커 스레드 수.
INCIDENT_ANALYSIS_WORKERS = max(
    1, int(os.getenv("INCIDENT_ANALYSIS_WORKERS", "2"))
)

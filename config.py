import os


API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8080"))

SCRIPT_TIMEOUT_SECONDS = int(
    os.getenv("SCRIPT_TIMEOUT_SECONDS", "30")
)


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
        ],
        "auto_diagnose": True,
        "auto_remediate": False,
    },
}

"""
DIAGNOSTIC_SCRIPTS = {
    "check_disk_usage": (
        "/opt/runbooks/diagnosis/check_disk_usage.sh"
    ),
    "check_large_files": (
        "/opt/runbooks/diagnosis/check_large_files.sh"
    ),
    "check_jdbc_version": (
        "/opt/runbooks/diagnosis/check_jdbc_version.sh"
    ),
    "check_sqlnet": (
        "/opt/runbooks/diagnosis/check_sqlnet.sh"
    ),
}
"""


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DIAGNOSTIC_SCRIPTS = {
    "check_disk_usage": os.path.join(
        BASE_DIR,
        "test-runbooks",
        "check_disk_usage.sh",
    ),
    "check_large_files": os.path.join(
        BASE_DIR,
        "test-runbooks",
        "check_large_files.sh",
    ),
    "check_jdbc_version": os.path.join(
        BASE_DIR,
        "test-runbooks",
        "check_jdbc_version.sh",
    ),
    "check_sqlnet": os.path.join(
        BASE_DIR,
        "test-runbooks",
        "check_sqlnet.sh",
    ),
}

# 운영자가 추천안 중 하나를 승인했을 때 실행되는 원격조치 스크립트.
# ERROR_RULES[...]["remediation_candidates"]에 등장하는 id와 매핑되어야 한다.
REMEDIATION_SCRIPTS = {
    "compress_old_logs": os.path.join(
        BASE_DIR,
        "test-runbooks",
        "compress_old_logs.sh",
    ),
    "update_jdbc_driver": os.path.join(
        BASE_DIR,
        "test-runbooks",
        "update_jdbc_driver.sh",
    ),
    "modify_sqlnet": os.path.join(
        BASE_DIR,
        "test-runbooks",
        "modify_sqlnet.sh",
    ),
}


# "mock" (기본값) / "qdrant" / "elastic" / "hybrid" 중 선택.
# - qdrant  : QdrantCaseSearcher (벡터 유사도 검색)
# - elastic : ElasticCaseSearcher (키워드 검색)
# - hybrid  : 위 둘을 함께 조회해서 병합 (Qdrant + Elasticsearch 모두 근거로 추천)
CASE_SEARCHER_BACKEND = os.getenv(
    "CASE_SEARCHER_BACKEND", "mock"
)

# QDRANT_URL이 설정되어 있으면 원격/Docker Qdrant 서버에
# 접속하고, 없으면 QDRANT_PATH 경로에 로컬 파일 기반으로 저장한다.
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_PATH = os.getenv(
    "QDRANT_PATH",
    os.path.join(BASE_DIR, "qdrant", "qdrant_data"),
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


# "mock" (기본값) 또는 "elastic" 중 선택. elastic로 두면
# repository가 ElasticLogRepository로 교체된다.
LOG_REPOSITORY_BACKEND = os.getenv(
    "LOG_REPOSITORY_BACKEND", "mock"
)

ELASTICSEARCH_URL = os.getenv(
    "ELASTICSEARCH_URL", "https://localhost:9200"
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

# Qdrant의 incident_cases 컬렉션과 동일한 과거 대응 사례를
# 담아두는 Elasticsearch 인덱스 (incident_cases.py로 시딩).
ELASTIC_INCIDENT_CASES_INDEX = os.getenv(
    "ELASTIC_INCIDENT_CASES_INDEX", "incident-cases"
)

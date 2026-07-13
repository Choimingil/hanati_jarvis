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


# "mock" (기본값) 또는 "qdrant" 중 선택. qdrant로 두면
# case_searcher가 QdrantCaseSearcher로 교체된다.
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

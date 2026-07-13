import os


API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "5001"))

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

from typing import Any

from config import DIAGNOSTIC_SCRIPTS, ERROR_RULES
from elastic_repository import save_document
from script_runner import run_script
from utils.time_utils import now_iso


def run_diagnostics(
    error_code: str,
    log: dict[str, Any],
) -> list[dict[str, Any]]:
    rule = ERROR_RULES[error_code]

    if not rule.get("auto_diagnose", False):
        return []

    results: list[dict[str, Any]] = []

    for script_id in rule["diagnostic_scripts"]:
        result = run_script(
            script_id,
            DIAGNOSTIC_SCRIPTS,
        )

        results.append(result)

        diagnosis_document = {
            "timestamp": now_iso(),
            "error_code": error_code,
            "message": log.get("message"),
            "host": log.get("host"),
            "service": log.get("service"),
            "script_id": script_id,
            "result": result,
        }

        save_document(
            "diagnosis-results",
            diagnosis_document,
        )

    return results

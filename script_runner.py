import os
import subprocess
from typing import Any

from config import SCRIPT_TIMEOUT_SECONDS


def run_script(
    script_id: str,
    script_map: dict[str, str],
) -> dict[str, Any]:
    if script_id not in script_map:
        return {
            "script_id": script_id,
            "status": "blocked",
            "reason": "not in allowlist",
        }

    script_path = script_map[script_id]

    if not os.path.isfile(script_path):
        return {
            "script_id": script_id,
            "status": "failed",
            "reason": "script file does not exist",
            "path": script_path,
        }

    if not os.access(script_path, os.X_OK):
        return {
            "script_id": script_id,
            "status": "failed",
            "reason": "script is not executable",
            "path": script_path,
        }

    try:
        result = subprocess.run(
            [script_path],
            capture_output=True,
            text=True,
            timeout=SCRIPT_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )

        status = (
            "success"
            if result.returncode == 0
            else "failed"
        )

        return {
            "script_id": script_id,
            "status": status,
            "path": script_path,
            "returncode": result.returncode,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
        }

    except subprocess.TimeoutExpired:
        return {
            "script_id": script_id,
            "status": "timeout",
            "path": script_path,
            "timeout_seconds": (
                SCRIPT_TIMEOUT_SECONDS
            ),
        }

    except OSError as exc:
        return {
            "script_id": script_id,
            "status": "failed",
            "path": script_path,
            "reason": str(exc),
        }

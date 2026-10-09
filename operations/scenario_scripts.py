"""Previously registered test scripts, bound only to log_generator incidents."""

import hashlib
import json
import os
from pathlib import Path
import subprocess

from config import ERROR_RULES

ROOT = Path(__file__).resolve().parent.parent
INSTANCE = "log-generator-scripts"


def catalog():
    return json.loads((ROOT / "test-runbooks/catalog.json").read_text())["scripts"]


def script_path(script_id, kind):
    item = catalog().get(script_id)
    if not item or item["kind"] != kind:
        raise ValueError("scenario script is not registered")
    path = ROOT / item["path"]
    if (
        path.is_symlink()
        or path.resolve().parent != (ROOT / "test-runbooks").resolve()
        or not path.is_file()
        or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
    ):
        raise ValueError("registered scenario script changed or missing")
    return path


def is_scenario_target(target):
    return isinstance(target, dict) and (
        target.get("environment") == "simulation"
        and target.get("service") == "order-api"
        and target.get("instance") == INSTANCE
        and isinstance(target.get("host"), str) and bool(target["host"])
    )


def targets_for_script(incident, script_id, kind="remediation"):
    rule = ERROR_RULES.get(incident.get("error_code"), {})
    allowed = rule.get("diagnostic_scripts" if kind == "diagnostic" else "remediation_candidates", [])
    if (
        incident.get("synthetic") is not True
        or incident.get("environment") != "simulation"
        or incident.get("service") != "order-api"
        or script_id not in allowed
    ):
        return []
    try:
        script_path(script_id, kind)
    except (ValueError, OSError):
        return []
    return [
        {"host": host, "environment": "simulation", "service": "order-api", "instance": INSTANCE}
        for host in incident.get("affected_hosts", [])
        if isinstance(host, str) and host
    ]


def runtime_for(target):
    if not is_scenario_target(target):
        raise ValueError("scenario scripts require a simulation target")
    from execution_agent.runtime import AgentRuntime

    actions = {
        script_id: {
            "enabled": True, "kind": item["kind"], "operation": "scenario_script",
            "script_id": script_id, "execution_mode": "simulation",
            "sha256": item["sha256"],
            "expected_impact": "기존 테스트용 스크립트의 메시지 출력 (실제 시스템 변경 없음)",
            "rollback_description": "테스트 출력만 수행하므로 시스템 복원 작업 없음",
        }
        for script_id, item in catalog().items()
    }
    manifest = {**target, "scope": "simulation", "actions": actions}
    state_dir = Path(os.getenv("SCENARIO_SCRIPT_STATE_DIR", str(ROOT / "scenario-script-state")))
    identity = hashlib.sha256(json.dumps(target, sort_keys=True).encode()).hexdigest()
    return AgentRuntime(manifest, state_dir / (identity + ".sqlite"), backend=ScenarioScriptBackend())


class ScenarioScriptBackend:
    def container(self, action):
        return script_path(action["script_id"], action["kind"])

    def prechecks(self, action):
        self.container(action)
        return [{"name": "registered_test_script", "passed": True}]

    def snapshot(self, action):
        self.container(action)
        return {"execution_mode": "simulation"}

    def perform(self, action):
        path = self.container(action)
        # No operator text, arguments, shell interpolation, inherited credentials
        # or real-host commands are accepted by this execution path.
        try:
            completed = subprocess.run(
                ["/bin/bash", str(path)], cwd=ROOT / "test-runbooks",
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                capture_output=True, text=True, timeout=10, check=False,
            )
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "execution_mode": "simulation"}
        return {
            "status": "success" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode, "stdout": completed.stdout[:8000],
            "stderr": completed.stderr[:8000], "execution_mode": "simulation",
            "script_path": action["script_id"] + ".sh",
            "message": "테스트용 셸 스크립트 실행 결과입니다. 실제 서비스의 복구 상태는 측정하지 않습니다.",
        }

    def rollback(self, action, before):
        return {"status": "success", "execution_mode": "simulation", "message": "테스트 출력만 수행하여 복원할 변경 없음"}

    def verify(self, action, execution_started_at=None):
        self.container(action)
        return [{"name": "registered_test_script", "passed": True}]

"""Immutable script attachments and exact, scoped reuse after confirmed recovery."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3

from utils.time_utils import now_iso

MAX_SCRIPT_BYTES = 64 * 1024
INSTANCE = "learned-scripts"


def scope_for(incident):
    code = incident.get("error_code")
    if not code or code == "UNKNOWN_ERROR":
        raise ValueError("a recognized error code is required to learn a script")
    scope = {key: incident.get(key) for key in ("environment", "service", "error_code")}
    if not all(isinstance(value, str) and value for value in scope.values()):
        raise ValueError("script scope requires environment, service and error code")
    # Synthetic scripts must never be reused for real incidents in the same environment.
    scope["synthetic"] = incident.get("synthetic") is True
    return scope


class ScriptLibrary:
    def __init__(self):
        directory = Path(os.getenv("LEARNED_SCRIPT_STATE_DIR", "learned-script-state"))
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "scripts.sqlite"
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS scripts (
                script_id TEXT PRIMARY KEY, scope TEXT NOT NULL, filename TEXT NOT NULL,
                content BLOB NOT NULL, sha256 TEXT NOT NULL, registered_at TEXT NOT NULL,
                source_incident_id TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0
            )""")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def attach(self, incident, filename, content):
        scope = json.dumps(scope_for(incident), sort_keys=True)
        if (not isinstance(filename, str) or not filename.endswith(".sh") or len(filename) > 128
            or len(filename) <= 3 or any(char in filename for char in ("/", "\\"))
            or any(ord(char) < 32 or ord(char) == 127 for char in filename)):
            raise ValueError("attach a .sh file with a simple filename")
        if not isinstance(content, bytes) or not 0 < len(content) <= MAX_SCRIPT_BYTES or b"\x00" in content:
            raise ValueError("script must be UTF-8 text between 1 and 65536 bytes")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("script must be UTF-8 text") from exc
        if not text.strip():
            raise ValueError("script must not be empty")
        digest = hashlib.sha256(content).hexdigest()
        script_id = "LEARNED-" + hashlib.sha256((scope + digest).encode()).hexdigest()
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO scripts VALUES (?,?,?,?,?,?,?,0)", (
                script_id, scope, filename, content, digest, now_iso(), incident["incident_id"],
            ))
        return self.get(script_id, incident)

    def get(self, script_id, incident=None, active=False):
        with self.connect() as db:
            row = db.execute("SELECT * FROM scripts WHERE script_id=?", (script_id,)).fetchone()
        if not row or (active and not row[7]):
            raise ValueError("learned script not found or not active")
        scope = json.loads(row[1])
        if incident is not None and scope != scope_for(incident):
            raise ValueError("learned script does not match incident scope")
        if hashlib.sha256(row[3]).hexdigest() != row[4]:
            raise ValueError("learned script integrity check failed")
        return {"script_id": row[0], "scope": scope, "filename": row[2], "content": row[3],
                "sha256": row[4], "registered_at": row[5], "source_incident_id": row[6], "active": bool(row[7])}

    def activate(self, script_id, incident):
        self.get(script_id, incident)
        with self.connect() as db:
            db.execute("UPDATE scripts SET active=1 WHERE script_id=?", (script_id,))

    def latest(self, incident):
        try:
            scope = json.dumps(scope_for(incident), sort_keys=True)
        except ValueError:
            return None
        with self.connect() as db:
            row = db.execute("SELECT script_id FROM scripts WHERE scope=? AND active=1 ORDER BY registered_at DESC, script_id DESC LIMIT 1", (scope,)).fetchone()
        return self.get(row[0], incident, active=True) if row else None


def metadata(script):
    return {key: script[key] for key in ("script_id", "filename", "sha256", "registered_at")}


def is_learned_target(target):
    return isinstance(target, dict) and target.get("instance") == INSTANCE


def targets_for(incident, script_id):
    script = ScriptLibrary().get(script_id, incident, active=True)
    # The generator's scripts run in an isolated sandbox, not on real hosts.
    if script["scope"]["synthetic"] is not True or incident.get("environment") != "simulation":
        return []
    return [{"host": host, "environment": incident["environment"], "service": incident["service"], "instance": INSTANCE}
            for host in incident.get("affected_hosts", []) if isinstance(host, str) and host]


def runtime_for(target):
    if not is_learned_target(target) or target.get("environment") != "simulation":
        raise ValueError("learned scripts require a simulation target")
    from execution_agent.runtime import AgentRuntime
    from operations.script_sandbox import SandboxBackend

    # Policy contains only active scripts for this service and environment.
    library = ScriptLibrary()
    with library.connect() as db:
        ids = [row[0] for row in db.execute("SELECT script_id FROM scripts WHERE active=1")]
    actions = {}
    for script_id in ids:
        script = library.get(script_id, active=True)
        scope = script["scope"]
        if scope["environment"] == target["environment"] and scope["service"] == target["service"] and scope["synthetic"]:
            actions[script_id] = {"enabled": True, "kind": "remediation", "operation": "learned_script",
                "script_id": script_id, "sha256": script["sha256"], "execution_mode": "simulation",
                "expected_impact": "첨부 스크립트를 격리된 테스트 컨테이너에서 실행",
                "rollback_description": "테스트 컨테이너를 삭제하며 실제 서비스는 변경하지 않음"}
    manifest = {**target, "scope": "simulation", "actions": actions}
    identity = hashlib.sha256(json.dumps(target, sort_keys=True).encode()).hexdigest()
    return AgentRuntime(manifest, library.path.parent / (identity + ".sqlite"), backend=SandboxBackend())

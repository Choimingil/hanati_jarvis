"""Compose-only execution with a durable at-most-once journal."""

import hashlib
import json
from pathlib import Path
import sqlite3
import time
from operations.docker_backend import DockerBackend
from operations.privacy import redact

IDENTITY_KEYS = ("host", "environment", "service", "instance")


def policy_digest(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


class AgentRuntime:
    def __init__(self, manifest, journal_path, backend=None):
        self.manifest = manifest
        self.digest = policy_digest(manifest)
        self.backend = backend or DockerBackend(manifest)
        self.path = str(journal_path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS executions (id TEXT PRIMARY KEY, fingerprint TEXT, result TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS active (singleton INTEGER PRIMARY KEY, execution_id TEXT)"
            )

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def identity(self):
        return {k: self.manifest[k] for k in IDENTITY_KEYS}

    def action(self, body):
        if body.get("target") != self.identity():
            raise ValueError("target identity mismatch")
        action = self.manifest.get("actions", {}).get(body.get("script_id"))
        if not action or action.get("enabled") is not True:
            raise ValueError("action not enabled in host manifest")
        if body.get("kind") != action.get("kind"):
            raise ValueError("action kind mismatch")
        if action.get("operation") not in {"inspect", "restart"}:
            raise ValueError("operation not allowed")
        if action["kind"] == "remediation" and (
            action["operation"] != "restart"
            or action.get("rollback") != "restore_runtime_state"
            or action.get("business_probe") not in {"jarvis_pipeline", "http_kpi"}
        ):
            raise ValueError("registered rollback and business verification required")
        if action.get("business_probe") == "http_kpi":
            from operations.business_probe import validate_probe

            policy = validate_probe(action.get("business_recovery"))
            if (
                policy["expected_service"] != self.manifest["service"]
                or policy["expected_environment"] != self.manifest["environment"]
            ):
                raise ValueError(
                    "business probe identity differs from execution target"
                )
        return action

    def preflight(self, body):
        action = self.action(body)
        self.backend.container(action)
        checks = (
            self.backend.prechecks(action) if action["kind"] == "remediation" else []
        )
        with self.connect() as db:
            active = db.execute(
                "SELECT execution_id FROM active WHERE singleton=1"
            ).fetchone()
        checks.append({"name": "host_idle", "passed": not active})
        return {
            "target": self.identity(),
            "policy_digest": self.digest,
            "checks": checks,
            "ready": all(c["passed"] for c in checks),
            "expected_impact": action.get("expected_impact", "not configured"),
            "rollback": action.get("rollback_description", "not configured"),
        }

    def result(self, execution_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT result FROM executions WHERE id=?", (execution_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def execute(self, body):
        # Look up the original receipt before validating a newly deployed policy.
        # A changed policy must not make an already executed ID executable again.
        execution_id = body.get("execution_id")
        if (
            not isinstance(execution_id, str)
            or not execution_id
            or len(execution_id) > 100
        ):
            raise ValueError("invalid execution id")
        fingerprint = hashlib.sha256(
            json.dumps(body, sort_keys=True).encode()
        ).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT fingerprint,result FROM executions WHERE id=?", (execution_id,)
            ).fetchone()
            if existing:
                if existing[0] != fingerprint:
                    raise ValueError("execution id reused with different request")
                return json.loads(existing[1])
            action = self.action(body)
            if body.get("policy_digest") != self.digest:
                raise ValueError("agent policy changed; repeat preflight")
            if db.execute("SELECT 1 FROM active").fetchone():
                raise ValueError("host has an active or unresolved execution")
            result = {
                "status": "running",
                "execution_id": execution_id,
                "target": self.identity(),
                "started_at": time.time(),
                "script_id": body["script_id"],
                "policy_digest": self.digest,
            }
            db.execute(
                "INSERT INTO executions VALUES (?,?,?)",
                (execution_id, fingerprint, json.dumps(result)),
            )
            db.execute("INSERT INTO active VALUES (1,?)", (execution_id,))
        before = None
        try:
            checks = (
                self.backend.prechecks(action)
                if action["kind"] == "remediation"
                else []
            )
            if not all(c["passed"] for c in checks):
                result.update(
                    status="blocked", reason="precheck failed", prechecks=checks
                )
            else:
                before = self.backend.snapshot(action)
                result.update(
                    self.backend.perform(action), prechecks=checks, before=before
                )
                if result["status"] != "success" and action["kind"] == "remediation":
                    result["rollback_result"] = self.backend.rollback(action, before)
                    if result["rollback_result"]["status"] != "success":
                        result["status"] = "rollback_failed"
        except ValueError as exc:
            result.update(
                status="blocked" if before is None else "unknown", reason=str(exc)
            )
        except Exception as exc:
            result.update(status="unknown", reason=type(exc).__name__)
        result = redact({**result, "finished_at": time.time()})
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE executions SET result=? WHERE id=?",
                (json.dumps(result), execution_id),
            )
            if result["status"] in {"success", "failed", "blocked", "timeout"}:
                db.execute("DELETE FROM active WHERE execution_id=?", (execution_id,))
        return result

    def verify(self, body):
        action = self.action(body)
        result = self.result(body.get("execution_id", ""))
        if (
            not result
            or result.get("status") != "success"
            or result.get("script_id") != body.get("script_id")
        ):
            raise ValueError("successful matching execution required")
        if result.get("policy_digest") != self.digest:
            raise ValueError("policy changed since execution")
        samples = []
        for index in range(2):
            if index:
                time.sleep(
                    min(
                        30,
                        max(
                            1, float(self.manifest.get("recovery_interval_seconds", 5))
                        ),
                    )
                )
            samples.append(
                self.backend.verify(action, execution_started_at=result["finished_at"])
            )
        checks = [
            {
                "name": c["name"],
                "passed": all(
                    any(v["name"] == c["name"] and v["passed"] for v in sample)
                    for sample in samples
                ),
            }
            for c in samples[0]
        ]
        return {
            "execution_id": body["execution_id"],
            "target": self.identity(),
            "checks": checks,
            "samples": samples,
            "recovered": bool(checks) and all(c["passed"] for c in checks),
            "verified_at": time.time(),
        }

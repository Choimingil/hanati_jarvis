"""Target-bound agent transport, approval proofs and durable distributed reservations."""

import hashlib
import json
import os
import uuid
from urllib.parse import urlparse
import httpx
from redis.exceptions import WatchError
from operations.privacy import redact
from operations.settings import registry, target_identity
from utils.time_utils import now_iso

TERMINAL = {"success", "failed", "timeout", "blocked"}


class ExecutionCoordinator:
    def __init__(self, redis, transport=None):
        self.redis = redis
        self.transport = transport or httpx.Client(
            timeout=250, follow_redirects=False, trust_env=False
        )

    def entry(self, target):
        entries = [e for e in registry() if target_identity(e) == target]
        if len(entries) != 1:
            raise ValueError("target not uniquely registered")
        entry = entries[0]
        url = urlparse(entry["url"])
        if url.scheme != "https" and not (
            url.scheme == "http"
            and (
                url.hostname in {"localhost", "127.0.0.1", "::1"}
                or (
                    url.hostname == "execution-agent"
                    and entry.get("scope") == "compose"
                )
            )
        ):
            raise ValueError("remote agent requires HTTPS")
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("invalid agent URL")
        token = os.environ.get(entry["token_env"], "")
        if len(token) < 32:
            raise ValueError("agent machine credential not configured")
        return entry, {"Authorization": "Bearer " + token}

    def call(self, target, path, body=None):
        entry, headers = self.entry(target)
        response = self.transport.request(
            "GET" if body is None else "POST",
            entry["url"].rstrip("/") + path,
            json=body,
            headers=headers,
        )
        if response.status_code in {401, 403}:
            raise ValueError("agent machine credential rejected")
        if path == "/preflight" and response.status_code == 409:
            blocked = response.json()
            if isinstance(blocked, dict) and blocked.get("status") == "blocked":
                raise ValueError(redact(blocked.get("reason") or "agent preflight blocked"))
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("invalid agent response")
        if "target" in result and result["target"] != target:
            raise ValueError("agent response identity mismatch")
        return result

    def prepare(self, context, target):
        if target not in context["recommendation"].get("targets", []):
            raise ValueError("target not bound to recommendation")
        host_key = "jarvis:host:" + hashlib.sha256(target["host"].encode()).hexdigest()
        if self.redis.get(host_key):
            raise ValueError(
                "host is executing or waiting for business recovery confirmation"
            )
        body = {
            "target": target,
            "script_id": context["script_id"],
            "kind": "remediation",
        }
        identity = self.call(target, "/identity")
        result = self.call(target, "/preflight", body)
        if (
            identity.get("target") != target
            or result.get("target") != target
            or identity.get("policy_digest") != result.get("policy_digest")
        ):
            raise ValueError("agent identity or policy mismatch")
        if not result.get("ready"):
            return {**result, "status": "blocked"}
        proof_id = uuid.uuid4().hex
        proof = {
            "incident_id": context["incident"]["incident_id"],
            "recommendation_id": context["recommendation"]["recommendation_id"],
            "incident_version": context["recommendation"]["incident_version"],
            "script_id": context["script_id"],
            "target": target,
            "policy_digest": result["policy_digest"],
        }
        self.redis.set("jarvis:preflight:" + proof_id, json.dumps(proof), ex=120)
        return {
            **result,
            "status": "ready",
            "preflight_id": proof_id,
            "expires_in_seconds": 120,
        }

    def validate_proof(self, body, context):
        raw = self.redis.get("jarvis:preflight:" + str(body.get("preflight_id", "")))
        if not raw:
            raise ValueError("preflight expired or missing")
        proof = json.loads(raw)
        expected = {
            "incident_id": body["incident_id"],
            "recommendation_id": body["recommendation_id"],
            "incident_version": body["incident_version"],
            "script_id": context["script_id"],
            "target": body.get("target"),
        }
        if any(proof.get(k) != v for k, v in expected.items()):
            raise ValueError("preflight does not match approval")
        if proof["target"] not in context["recommendation"].get("targets", []):
            raise ValueError("target no longer bound to recommendation")
        self.entry(proof["target"])
        return proof

    def reserve(self, execution_id, body, context, proof):
        key = "jarvis:execution:" + execution_id
        locks = [
            "jarvis:action:" + body["recommendation_id"],
            "jarvis:host:"
            + hashlib.sha256(proof["target"]["host"].encode()).hexdigest(),
            "jarvis:decision:" + body["recommendation_id"] + ":" + body["action_id"],
        ]
        # Reservations have no TTL: a crash or ambiguous transport result cannot
        # reopen a host for another command. Reconcile using the agent journal.
        for _ in range(5):
            with self.redis.pipeline() as pipe:
                try:
                    pipe.watch(key, *locks)
                    existing = pipe.get(key)
                    if existing:
                        return json.loads(existing), False
                    if any(pipe.get(k) for k in locks):
                        raise ValueError("recommendation or host already reserved")
                    agent_body = {
                        "execution_id": execution_id,
                        "target": proof["target"],
                        "script_id": context["script_id"],
                        "kind": "remediation",
                        "policy_digest": proof["policy_digest"],
                    }
                    record = {
                        "execution_id": execution_id,
                        "incident_id": body["incident_id"],
                        "recommendation_id": body["recommendation_id"],
                        "action_id": body["action_id"],
                        "script_id": context["script_id"],
                        "error_code": context["error_code"],
                        "target": proof["target"],
                        "approved_by": body["approved_by"],
                        "approved_at": now_iso(),
                        "agent_body": agent_body,
                        "locks": locks,
                        "result": {"status": "reserved"},
                    }
                    pipe.multi()
                    pipe.set(key, json.dumps(record))
                    for lock in locks:
                        pipe.set(lock, execution_id)
                    pipe.xadd(
                        "jarvis:audit",
                        {
                            "event": "reserved",
                            "execution_id": execution_id,
                            "target": json.dumps(proof["target"]),
                        },
                    )
                    pipe.execute()
                    return record, True
                except WatchError:
                    continue
        raise ValueError("concurrent approval; retry with fresh preflight")

    def get(self, execution_id):
        value = self.redis.get("jarvis:execution:" + execution_id)
        return json.loads(value) if value else None

    def dispatch(self, record):
        try:
            result = self.call(record["target"], "/execute", record["agent_body"])
            if (
                result.get("execution_id") != record["execution_id"]
                or result.get("target") != record["target"]
            ):
                raise ValueError("execution response mismatch")
        except Exception as exc:
            result = {
                "status": "unknown",
                "reason": "agent response unavailable; inspect journal before another action",
                "error": type(exc).__name__,
            }
        record["result"] = redact(result)
        self.redis.set("jarvis:execution:" + record["execution_id"], json.dumps(record))
        return record

    def reconcile(self, record):
        if record["result"].get("status") not in TERMINAL:
            try:
                result = self.call(
                    record["target"], "/executions/" + record["execution_id"]
                )
                if (
                    result.get("execution_id") != record["execution_id"]
                    or result.get("target") != record["target"]
                ):
                    raise ValueError("journal identity mismatch")
                record["result"] = redact(result)
                self.redis.set(
                    "jarvis:execution:" + record["execution_id"], json.dumps(record)
                )
            except Exception:
                pass  # no execute retry, no lock release on unknown outcome
        return record

    def release_host(self, record):
        if record["result"].get("status") not in TERMINAL:
            return
        if record["result"]["status"] == "success" and not record.get(
            "recovery_verified"
        ):
            return  # observation is part of the protected execution window
        key = record["locks"][1]
        with self.redis.pipeline() as pipe:
            pipe.watch(key)
            if pipe.get(key) != record["execution_id"]:
                return
            pipe.multi()
            pipe.delete(key)
            pipe.xadd(
                "jarvis:audit",
                {
                    "event": "execution_recorded",
                    "execution_id": record["execution_id"],
                    "status": record["result"]["status"],
                },
            )
            pipe.execute()

    def reject(self, execution_id, body):
        key = "jarvis:decision:" + body["recommendation_id"] + ":" + body["action_id"]
        recommendation_lock = "jarvis:action:" + body["recommendation_id"]
        with self.redis.pipeline() as pipe:
            pipe.watch(key, recommendation_lock)
            existing = pipe.get(key)
            if existing and existing != execution_id:
                raise ValueError("action already reserved")
            if pipe.get(recommendation_lock):
                raise ValueError("recommendation already approved")
            pipe.multi()
            pipe.set(key, execution_id)
            pipe.xadd(
                "jarvis:audit", {"event": "rejected", "execution_id": execution_id}
            )
            pipe.execute()

    def diagnose(self, target, script_id):
        body = {"target": target, "script_id": script_id, "kind": "diagnostic"}
        preflight = self.call(target, "/preflight", body)
        if not preflight.get("ready") or preflight.get("target") != target:
            return {"status": "blocked", "reason": "diagnostic preflight failed"}
        return self.call(
            target,
            "/execute",
            {
                **body,
                "execution_id": "DIAG-" + uuid.uuid4().hex,
                "policy_digest": preflight["policy_digest"],
            },
        )

    def verify(self, record):
        result = self.call(record["target"], "/verify", record["agent_body"])
        if (
            result.get("execution_id") != record["execution_id"]
            or result.get("target") != record["target"]
        ):
            raise ValueError("verification response mismatch")
        return result

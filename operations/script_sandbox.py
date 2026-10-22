"""Execute uploaded scripts in disposable containers via a separate Redis worker.

The API never runs attachment text in its own process or container.
"""

import base64
import hashlib
import json
import os
import time

from operations.learned_scripts import ScriptLibrary
from operations.privacy import redact
from operations.redis_store import client

QUEUE = "jarvis:script-sandbox:queue"
PREFIX = "jarvis:script-sandbox:"


class SandboxBackend:
    def container(self, action):
        script = ScriptLibrary().get(action["script_id"], active=True)
        if script["sha256"] != action["sha256"]:
            raise ValueError("learned script integrity check failed")
        return script

    def prechecks(self, action):
        self.container(action)
        return [{"name": "sandbox_executor_available", "passed": bool(client().get(PREFIX + "heartbeat"))}]

    def snapshot(self, action):
        self.container(action)
        return {"execution_mode": "simulation"}

    def perform(self, action):
        script = self.container(action)
        redis = client()
        # AgentRuntime supplies its durable execution ID, never an operator-controlled filename.
        job_id = action["execution_id"]
        key = PREFIX + job_id
        job = {"execution_id": job_id, "sha256": script["sha256"],
               "content": base64.b64encode(script["content"]).decode()}
        redis.eval("""
            if redis.call('SET', KEYS[1], ARGV[1], 'NX') then
                redis.call('RPUSH', KEYS[2], ARGV[2])
                return 1
            end
            return 0
        """, 2, key + ":submitted", QUEUE, json.dumps(job), job_id)
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            raw = redis.get(key + ":result")
            if raw:
                return json.loads(raw)
            time.sleep(0.1)
        return {"status": "unknown", "execution_mode": "simulation",
                "reason": "sandbox response pending; do not execute again"}

    def result(self, execution_id):
        raw = client().get(PREFIX + execution_id + ":result")
        return json.loads(raw) if raw else None

    def rollback(self, action, before):
        return {"status": "success", "execution_mode": "simulation"}

    def verify(self, action, execution_started_at=None):
        self.container(action)
        return [{"name": "attachment_integrity", "passed": True}]


def execute_job(job, docker_client):
    from operations.learned_scripts import MAX_SCRIPT_BYTES
    content = base64.b64decode(job["content"], validate=True)
    if not 0 < len(content) <= MAX_SCRIPT_BYTES or hashlib.sha256(content).hexdigest() != job["sha256"]:
        raise ValueError("invalid sandbox script")
    script = content.decode("utf-8")
    image = os.getenv("SCRIPT_SANDBOX_IMAGE", "hanati-script-sandbox:local")
    container = docker_client.containers.create(
        image, command=["/usr/bin/timeout", "--kill-after=2s", "20s", "/bin/bash", "-c", script], user="65534:65534",
        network_disabled=True, read_only=True, cap_drop=["ALL"],
        security_opt=["no-new-privileges:true"], pids_limit=32,
        mem_limit="64m", memswap_limit="64m", nano_cpus=250000000,
        tmpfs={"/tmp": "rw,noexec,nosuid,size=8m"}, working_dir="/tmp",
        environment={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        log_config={"type": "json-file", "config": {"max-size": "16k", "max-file": "1"}},
        labels={"jarvis.script.execution": job["execution_id"]},
    )
    try:
        container.start()
        try:
            result = container.wait(timeout=25)
        except Exception:
            container.kill()
            return {"status": "timeout", "execution_mode": "simulation"}
        return redact({"status": "success" if result["StatusCode"] == 0 else "timeout" if result["StatusCode"] in {124, 137} else "failed",
            "returncode": result["StatusCode"], "execution_mode": "simulation",
            "stdout": container.logs(stdout=True, stderr=False, tail=100).decode("utf-8", "replace")[:8000],
            "stderr": container.logs(stdout=False, stderr=True, tail=100).decode("utf-8", "replace")[:8000],
            "message": "첨부 스크립트를 격리된 테스트 컨테이너에서 실행했습니다. 실제 서비스 복구는 별도 확인이 필요합니다."})
    finally:
        container.remove(force=True)


def main():
    import docker
    redis = client()
    docker_client = docker.from_env()
    while True:
        redis.set(PREFIX + "heartbeat", "ready", ex=45)
        item = redis.blpop(QUEUE, timeout=5)
        if not item:
            continue
        job_id = item[1]
        key = PREFIX + job_id
        # Never replay a job after an executor crash or an ambiguous Docker result.
        if not redis.set(key + ":started", "1", nx=True):
            continue
        try:
            job = json.loads(redis.get(key + ":submitted"))
            result = execute_job(job, docker_client)
        except Exception as exc:
            result = {"status": "unknown", "reason": type(exc).__name__, "execution_mode": "simulation"}
        redis.set(key + ":result", json.dumps(result))


if __name__ == "__main__":
    main()

import base64
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import fakeredis
from flask import Flask

from aiops.manual_remediation_service import ManualRemediationService
from aiops.operational_incident_service import OperationalIncidentService
from error_detector import detect_error_code
from log_processor import LogProcessor
from operations.execution import ExecutionCoordinator
from operations.learned_scripts import MAX_SCRIPT_BYTES, ScriptLibrary, runtime_for
from operations.script_sandbox import execute_job, PREFIX, QUEUE, SandboxBackend
from operations.settings import bind_recommendation, manual_action_available
from routes import log_generator_routes, remediation_routes
from support import MemoryRepository


class Repository(MemoryRepository):
    def save_log(self, document):
        pass

    def save_recommendation(self, document):
        rec = document["recommendation"]
        self.recommendations[rec["recommendation_id"]] = rec


class LearnedScriptTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        env = patch.dict(os.environ, {"LEARNED_SCRIPT_STATE_DIR": self.directory.name})
        env.start(); self.addCleanup(env.stop)
        targets = patch("operations.settings.registry", return_value=[])
        targets.start(); self.addCleanup(targets.stop)
        self.repo = Repository()
        self.service = OperationalIncidentService(self.repo)
        self.searcher, self.generator = Mock(), Mock()
        self.processor = LogProcessor(self.repo, self.searcher, self.generator, incident_service=self.service)
        self.log = {"level": "ERROR", "message": "Configuration mismatch detected for order processing.",
                    "environment": "simulation", "service": "order-api", "host": "web01", "synthetic": True}
        result = self.processor.process(self.log)
        self.incident = self.repo.get_operational_incident(result["recommendation"]["incident_id"])
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self.transport = Mock()
        self.manager = ExecutionCoordinator(self.redis, self.transport)
        for module in (remediation_routes, log_generator_routes):
            p = patch.object(module, "repository", self.repo); p.start(); self.addCleanup(p.stop)
        for name, value in (("operational_incident_service", self.service), ("coordinator", lambda: self.manager)):
            p = patch.object(remediation_routes, name, value); p.start(); self.addCleanup(p.stop)
        self.repo.recent_incident_logs = lambda *args, **kwargs: []
        app = Flask(__name__)
        app.register_blueprint(remediation_routes.remediation_blueprint)
        app.register_blueprint(log_generator_routes.log_generator_blueprint)
        self.api = app.test_client()
        self.body = {"incident_id": self.incident["incident_id"], "incident_version": self.incident["version"],
                     "registration_id": "MANUAL-upload-test", "operator": "tester", "method": "승인된 설정으로 복원",
                     "performed": True, "recovered": True}
        self.content = b'#!/bin/bash\nprintf "learned-action\\n"\n'

    def upload(self, body=None, content=None, filename="restore_config.sh"):
        return self.api.post("/api/v1/remediations/manual", data={
            "metadata": json.dumps(body or self.body),
            "script": (BytesIO(self.content if content is None else content), filename),
        })

    def test_no_script_scenario_has_manual_panel_without_resource_analysis(self):
        self.assertEqual(self.incident["latest_recommendation"]["status"], "manual_required")
        self.assertTrue(manual_action_available(self.incident))
        self.searcher.search.assert_not_called()
        self.generator.generate.assert_not_called()

    def test_upload_persists_original_bytes_idempotently_and_downloads_after_restart(self):
        with patch("subprocess.run", side_effect=AssertionError("upload must not execute")):
            response = self.upload()
        self.assertEqual(response.status_code, 201, response.get_json())
        attachment = response.get_json()["manual_action"]["attachment"]
        self.assertNotIn("content", attachment)
        self.assertEqual(ScriptLibrary().get(attachment["script_id"])["content"], self.content)
        self.assertEqual(self.upload().status_code, 200)
        self.assertEqual(len(self.repo.get_operational_incident(self.incident["incident_id"])["manual_actions"]), 1)
        path = "/api/v1/remediations/scripts/" + attachment["script_id"] + "?incident_id=" + self.incident["incident_id"]
        downloaded = self.api.get(path)
        self.assertEqual(downloaded.data, self.content)
        self.assertIn("attachment", downloaded.headers["Content-Disposition"])
        self.assertEqual(self.upload(content=b"echo changed").status_code, 409)

    def test_korean_attachment_filename_is_preserved(self):
        result = self.upload(filename="설정_복원.sh")
        self.assertEqual(result.status_code, 201, result.get_json())
        self.assertEqual(result.get_json()["manual_action"]["attachment"]["filename"], "설정_복원.sh")

    def test_only_confirmed_recovery_activates_attachment_and_followup_can_promote(self):
        response = self.upload({**self.body, "recovered": False})
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(ScriptLibrary().latest(self.incident))
        pending = response.get_json()["incident"]
        confirmation = {**self.body, "incident_version": pending["version"], "registration_id": "MANUAL-confirm-upload"}
        result = self.api.post("/api/v1/remediations/manual", json=confirmation)
        self.assertEqual(result.status_code, 201, result.get_json())
        self.assertIsNotNone(ScriptLibrary().latest(self.incident))

    def test_recurrence_loads_same_script_and_requires_approval_before_sandbox_execution(self):
        response = self.upload()
        script_id = response.get_json()["manual_action"]["attachment"]["script_id"]
        with patch("operations.script_sandbox.SandboxBackend.perform") as perform:
            rec = self.processor.process(self.log)["recommendation"]
            perform.assert_not_called()
        self.assertEqual(rec["status"], "learned_script")
        self.assertEqual(rec["actions"][0]["script_id"], script_id)
        incident = self.repo.get_operational_incident(rec["incident_id"])
        body = {"incident_id": incident["incident_id"], "incident_version": incident["version"],
                "recommendation_id": rec["recommendation_id"], "action_id": rec["actions"][0]["action_id"],
                "approved_by": "tester", "target": rec["targets"][0]}
        self.redis.set(PREFIX + "heartbeat", "ready")
        with patch("operations.script_sandbox.client", return_value=self.redis), patch(
            "operations.script_sandbox.SandboxBackend.perform", return_value={"status": "success", "execution_mode": "simulation", "stdout": "learned-action"}
        ) as perform:
            result = self.api.post("/api/v1/remediations/approve", json=body)
            self.assertEqual(result.status_code, 200, result.get_json())
            self.assertEqual(perform.call_count, 1)
            self.assertEqual(perform.call_args.args[0]["script_id"], script_id)
            again = self.api.post("/api/v1/remediations/approve", json=body)
            self.assertTrue(again.get_json()["duplicate"])
            self.assertEqual(perform.call_count, 1)
            verified = self.api.post("/api/v1/remediations/verify", json={"execution_id": result.get_json()["execution_id"]})
            self.assertTrue(verified.get_json()["recovered"])
            self.assertEqual(verified.get_json()["execution_mode"], "simulation")
        self.transport.request.assert_not_called()

    def test_attachment_is_not_reused_for_other_error_service_environment_or_real_logs(self):
        self.upload()
        for changes in ({"error_code": "RATE_LIMIT_EXCEEDED"}, {"service": "payment-api"},
                        {"environment": "production"}, {"synthetic": False}):
            self.assertIsNone(ScriptLibrary().latest({**self.incident, **changes}))

    def test_invalid_files_and_oversize_requests_do_not_change_incident(self):
        for filename, content in (("../bad.sh", b"echo hi"), ("bad.py", b"print(1)"),
                                  ("bad.sh", b""), ("bad.sh", b"\xff"), ("bad.sh", b"\x00"),
                                  ("large.sh", b"x" * (MAX_SCRIPT_BYTES + 1))):
            with self.subTest(filename=filename, size=len(content)):
                self.assertEqual(self.upload(filename=filename, content=content).status_code, 409)
        self.assertEqual(self.upload(content=b"x" * (MAX_SCRIPT_BYTES + 32769)).status_code, 413)
        self.assertEqual(self.repo.get_operational_incident(self.incident["incident_id"])["version"], self.incident["version"])

    def test_conflicting_incident_save_never_activates_attachment(self):
        with patch.object(self.repo, "update_operational_incident", side_effect=RuntimeError("version conflict")):
            self.assertEqual(self.upload().status_code, 409)
        self.assertIsNone(ScriptLibrary().latest(self.incident))

    def test_old_resource_guidance_for_no_script_scenario_is_hidden(self):
        old = bind_recommendation(self.incident, {"status": "resource_guidance", "runbooks": []})
        self.assertEqual(old["status"], "manual_required")
        self.assertEqual(old["runbooks"], [])

    def test_missing_executor_blocks_before_running_any_script(self):
        self.upload()
        rec = self.processor.process(self.log)["recommendation"]
        target = rec["targets"][0]
        with patch("operations.script_sandbox.client", return_value=self.redis):
            result = runtime_for(target).preflight({"target": target, "script_id": rec["actions"][0]["script_id"], "kind": "remediation"})
        self.assertFalse(result["ready"])

    def test_sandbox_queue_submission_is_atomic_and_reuses_receipt(self):
        import threading

        self.upload()
        script = ScriptLibrary().latest(self.incident)
        action = {"script_id": script["script_id"], "sha256": script["sha256"], "execution_id": "EXEC-queued"}
        received = []
        def executor():
            item = self.redis.blpop(QUEUE, timeout=3)
            if item:
                received.append(json.loads(self.redis.get(PREFIX + item[1] + ":submitted")))
                self.redis.set(PREFIX + item[1] + ":result", json.dumps({"status": "success", "stdout": "queued file ran"}))
        thread = threading.Thread(target=executor)
        thread.start()
        try:
            with patch("operations.script_sandbox.client", return_value=self.redis):
                backend = SandboxBackend()
                self.assertEqual(backend.perform(action)["status"], "success")
                self.assertEqual(backend.perform(action)["status"], "success")
        finally:
            thread.join(timeout=4)
        self.assertEqual(len(received), 1)
        self.assertEqual(base64.b64decode(received[0]["content"]), self.content)
        self.assertEqual(self.redis.llen(QUEUE), 0)

    def test_late_sandbox_receipt_reconciles_durable_journal_without_reexecution(self):
        self.upload()
        rec = self.processor.process(self.log)["recommendation"]
        target = rec["targets"][0]
        runtime = runtime_for(target)
        body = {"execution_id": "EXEC-late", "target": target, "script_id": rec["actions"][0]["script_id"],
                "kind": "remediation", "policy_digest": runtime.digest}
        self.redis.set(PREFIX + "heartbeat", "ready")
        with patch("operations.script_sandbox.client", return_value=self.redis), patch.object(
            runtime.backend, "perform", return_value={"status": "unknown"}
        ) as perform:
            self.assertEqual(runtime.execute(body)["status"], "unknown")
            self.redis.set(PREFIX + "EXEC-late:result", json.dumps({"status": "success", "stdout": "late result"}))
            self.assertEqual(runtime.result("EXEC-late")["status"], "success")
            self.assertEqual(runtime.execute(body)["status"], "success")
            self.assertEqual(perform.call_count, 1)

    def test_sandbox_container_has_no_network_secrets_or_host_mounts_and_is_removed(self):
        import hashlib
        docker = Mock()
        container = docker.containers.create.return_value
        container.wait.return_value = {"StatusCode": 0}
        container.logs.return_value = b"learned-action"
        job = {"execution_id": "EXEC-test", "content": base64.b64encode(self.content).decode(), "sha256": hashlib.sha256(self.content).hexdigest()}
        result = execute_job(job, docker)
        self.assertEqual(result["status"], "success")
        opts = docker.containers.create.call_args.kwargs
        self.assertEqual(opts["command"], ["/usr/bin/timeout", "--kill-after=2s", "20s", "/bin/bash", "-c", self.content.decode()])
        self.assertTrue(opts["network_disabled"])
        self.assertTrue(opts["read_only"])
        self.assertEqual(opts["user"], "65534:65534")
        self.assertNotIn("volumes", opts)
        self.assertEqual(set(opts["environment"]), {"PATH", "LANG"})
        container.remove.assert_called_once_with(force=True)
        container.wait.side_effect = TimeoutError
        self.assertEqual(execute_job(job, docker)["status"], "timeout")
        container.kill.assert_called_once()


if __name__ == "__main__":
    unittest.main()

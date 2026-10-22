"""Exercise emitted generator logs through analysis, approval and actual scenario scripts."""

from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import fakeredis
from flask import Flask

from aiops.operational_incident_service import OperationalIncidentService
from aiops.recommendation_quality_gate import RecommendationQualityGate
from config import ERROR_RULES
from log_processor import LogProcessor
from operations.custom_scenarios import CustomScenarioStore
from operations.execution import ExecutionCoordinator
from operations.learned_scripts import ScriptLibrary
from operations.script_sandbox import PREFIX
from registry import SCENARIO_REGISTRY
from routes import remediation_routes
import trigger
from support import MemoryRepository


class Repository(MemoryRepository):
    def save_diagnosis(self, document):
        pass

    def save_log(self, document):
        pass

    def save_recommendation(self, document):
        rec = document["recommendation"]
        self.recommendations[rec["recommendation_id"]] = rec


class GeneratorApprovalFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "application.log"
        self.repo = Repository()
        self.service = OperationalIncidentService(self.repo)
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self.manager = ExecutionCoordinator(self.redis, Mock())
        generator = Mock()
        generator.generate.side_effect = lambda **kwargs: {
            "error_code": kwargs["error_code"], "cause": "scenario log",
            "runbooks": [{"script_id": script_id, "confidence": 90}
                         for script_id in kwargs["remediation_candidates"]],
        }
        self.processor = LogProcessor(self.repo, Mock(search=Mock(return_value=[])), generator,
                                      quality_gate=RecommendationQualityGate(), incident_service=self.service)
        patches = [patch.dict(os.environ, {
            "LEARNED_SCRIPT_STATE_DIR": str(Path(self.temp.name) / "learned"),
            "SCENARIO_SCRIPT_STATE_DIR": str(Path(self.temp.name) / "registered"),
        }), patch.object(trigger, "FLUENTBIT_LOG_PATH", self.path), patch("scenario.scenario_runner.time.sleep"),
            patch("builtins.print"), patch("operations.settings.registry", return_value=[]),
            patch.object(remediation_routes, "repository", self.repo),
            patch.object(remediation_routes, "operational_incident_service", self.service),
            patch.object(remediation_routes, "coordinator", return_value=self.manager),
            patch("operations.script_sandbox.client", return_value=self.redis),
            patch("operations.script_sandbox.SandboxBackend.perform", side_effect=self.learned_perform)]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        app = Flask(__name__)
        app.register_blueprint(remediation_routes.remediation_blueprint)
        self.api = app.test_client()
        self.redis.set(PREFIX + "heartbeat", "ready")
        self.attachment = b"#!/bin/bash\necho uploaded-recovery\n"

    def learned_perform(self, action):
        self.assertEqual(ScriptLibrary().get(action["script_id"], active=True)["content"], self.attachment)
        return {"status": "success", "execution_mode": "simulation", "stdout": "uploaded-recovery"}

    def emit_and_analyze(self, key):
        offset = self.path.stat().st_size if self.path.exists() else 0
        result = trigger.run_scenario(key)
        with self.path.open() as stream:
            stream.seek(offset)
            logs = [json.loads(line) for line in stream]
        results = [self.processor.process(log) for log in logs]
        recommendations = [item["recommendation"] for item in results if item.get("recommendation")]
        self.assertEqual(len(recommendations), 1, key)
        return result["error_code"], recommendations[0]

    def register_attachment(self, rec):
        incident = self.repo.get_operational_incident(rec["incident_id"])
        body = {"incident_id": incident["incident_id"], "incident_version": incident["version"],
                "registration_id": "MANUAL-" + incident["incident_id"], "operator": "tester",
                "method": "수동 복구 확인", "performed": True, "recovered": True}
        response = self.api.post("/api/v1/remediations/manual", data={
            "metadata": json.dumps(body), "script": (BytesIO(self.attachment), "recover.sh"),
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["incident"]["status"], "RESOLVED")

    def approve(self, rec, script_id):
        incident = self.repo.get_operational_incident(rec["incident_id"])
        action = next(item for item in rec["actions"] if item["script_id"] == script_id)
        self.assertTrue(action["targets"], script_id)
        body = {"incident_id": incident["incident_id"], "incident_version": incident["version"],
                "recommendation_id": rec["recommendation_id"], "action_id": action["action_id"],
                "approved_by": "tester", "target": action["targets"][0]}
        response = self.api.post("/api/v1/remediations/approve", json=body)
        result = response.get_json()
        self.assertEqual(response.status_code, 200, result)
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(result["execution_mode"], "simulation")
        self.assertEqual(self.repo.get_operational_incident(incident["incident_id"])["status"], "RESOLVED")
        self.assertIsNone(self.redis.get(self.manager.host_lock_key(body["target"])))
        duplicate = self.api.post("/api/v1/remediations/approve", json=body).get_json()
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["execution_id"], result["execution_id"])
        return result

    def test_every_generator_error_and_each_registered_action_approves_without_manual_verification(self):
        registered, manual = 0, 0
        for key, (_, _, expected_code) in SCENARIO_REGISTRY.items():
            candidates = ERROR_RULES[expected_code]["remediation_candidates"]
            if candidates:
                for script_id in candidates:
                    with self.subTest(scenario=key, script_id=script_id):
                        code, rec = self.emit_and_analyze(key)
                        self.assertEqual(code, expected_code)
                        result = self.approve(rec, script_id)
                        self.assertIn("component=" + script_id, result["stdout"])
                registered += 1
            else:
                with self.subTest(scenario=key):
                    _, rec = self.emit_and_analyze(key)
                    self.assertEqual(rec["status"], "manual_required")
                    self.register_attachment(rec)
                    _, learned = self.emit_and_analyze(key)
                    self.assertEqual(learned["status"], "learned_script")
                    self.approve(learned, learned["actions"][0]["script_id"])
                manual += 1
        self.assertEqual(registered, 19)
        self.assertEqual(manual, 1)
        # Repeating an earlier scenario after the entire sequence must remain actionable.
        _, rec = self.emit_and_analyze("disk_full")
        self.approve(rec, "compress_old_logs")

    def test_newly_created_error_can_learn_and_approve_its_attachment(self):
        item = CustomScenarioStore().create()
        _, rec = self.emit_and_analyze(item["key"])
        self.assertEqual(rec["status"], "manual_required")
        self.register_attachment(rec)
        _, rec = self.emit_and_analyze(item["key"])
        self.assertEqual(self.approve(rec, rec["actions"][0]["script_id"])["stdout"], "uploaded-recovery")


if __name__ == "__main__":
    unittest.main()

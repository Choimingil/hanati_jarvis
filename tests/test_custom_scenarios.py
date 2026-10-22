import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

import fakeredis
from flask import Flask

from aiops.manual_remediation_service import ManualRemediationService
from aiops.operational_incident_service import OperationalIncidentService
from error_detector import detect_error_code
from log_processor import LogProcessor
from operations.custom_scenarios import CustomScenarioStore
from operations.execution import ExecutionCoordinator
from operations.learned_scripts import ScriptLibrary
from operations.script_sandbox import PREFIX
from operations.settings import manual_action_available
from routes import log_generator_routes, remediation_routes
from routes.web_routes import web_blueprint
from registry import SCENARIO_REGISTRY, get_scenarios
from scenario.scenario_runner import ScenarioRunner
import trigger
from support import MemoryRepository


class Repository(MemoryRepository):
    def save_log(self, document):
        pass

    def save_recommendation(self, document):
        rec = document["recommendation"]
        self.recommendations[rec["recommendation_id"]] = rec


class CustomScenarioTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "application.log"
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self.repo = Repository()
        self.service = OperationalIncidentService(self.repo)
        self.manager = ExecutionCoordinator(self.redis, Mock())
        patches = [patch("builtins.print"), patch.dict(os.environ, {"LEARNED_SCRIPT_STATE_DIR": self.directory.name}),
                   patch.object(trigger, "FLUENTBIT_LOG_PATH", self.path),
                   patch("routes.log_generator_routes.redis_client", return_value=self.redis),
                   patch("operations.settings.registry", return_value=[]),
                   patch.object(log_generator_routes, "repository", self.repo),
                   patch.object(remediation_routes, "repository", self.repo),
                   patch.object(remediation_routes, "operational_incident_service", self.service),
                   patch.object(remediation_routes, "coordinator", return_value=self.manager)]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        self.repo.recent_incident_logs = lambda *args, **kwargs: []
        app = Flask(__name__)
        app.register_blueprint(log_generator_routes.log_generator_blueprint)
        app.register_blueprint(remediation_routes.remediation_blueprint)
        app.register_blueprint(web_blueprint)
        self.api = app.test_client()

    def create(self, **kwargs):
        return self.api.post("/api/v1/log-generator/scenarios/new", json=kwargs)

    def test_creation_persists_scenario_emits_detectable_log_and_replays_after_reopen(self):
        response = self.create()
        self.assertEqual(response.status_code, 200, response.get_json())
        data = response.get_json()
        self.assertEqual(data["status"], "triggered")
        item = data["scenario"]
        first = [json.loads(line) for line in self.path.read_text().splitlines()]
        errors = [log for log in first if log["level"] == "ERROR"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(detect_error_code(errors[0]["message"]), item["error_code"])
        self.assertTrue(errors[0]["synthetic"])
        self.assertEqual(errors[0]["environment"], "simulation")
        self.assertIn(item["key"], get_scenarios())
        self.assertEqual(CustomScenarioStore().list()[0]["error_code"], item["error_code"])
        self.assertIn(item["key"], {entry["key"] for entry in self.api.get("/api/v1/log-generator/scenarios").get_json()})
        self.assertEqual(self.api.get("/api/v1/log-generator/scenarios").headers["Cache-Control"], "no-store")
        replay = self.api.post("/api/v1/log-generator/run", json={"scenario": item["key"]})
        self.assertEqual(replay.get_json()["error_code"], item["error_code"])
        self.assertEqual(len(self.path.read_text().splitlines()), 2 * len(first))
        shared = self.api.get("/api/v1/log-generator/latest-run").get_json()["run"]
        self.assertEqual(shared["scenario"], item["key"])
        self.assertEqual(shared["phase"], "completed")

    def test_clicks_create_distinct_errors_and_request_retry_does_not_duplicate_scenario(self):
        first = self.create(request_id="12345678-1234-4234-8234-123456789abc").get_json()["scenario"]
        again = self.create(request_id="12345678-1234-4234-8234-123456789abc").get_json()["scenario"]
        second = self.create().get_json()["scenario"]
        self.assertEqual(first, again)
        self.assertNotEqual(first["error_code"], second["error_code"])
        self.assertEqual(len(CustomScenarioStore().list()), 2)
        self.assertEqual(self.create(request_id="bad").status_code, 400)

    def test_removed_configuration_scenario_is_not_selectable(self):
        self.assertNotIn("configuration_mismatch", SCENARIO_REGISTRY)
        response = self.api.post("/api/v1/log-generator/run", json={"scenario": "configuration_mismatch"})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("설정 불일치", str(self.api.get("/api/v1/log-generator/scenarios").get_json()))

    def test_generator_picks_up_newly_registered_scenarios_without_restart(self):
        runner = ScenarioRunner(Mock(), Mock(), SimpleNamespace(failure_behavior=SimpleNamespace(scenarios=[])))
        # Normal configured generators always have static scenarios; use one harmless factory here.
        runner.system.failure_behavior.scenarios = [SimpleNamespace(scenario=SCENARIO_REGISTRY["disk_full"][0]())]
        initial = runner._get_configured_scenarios()
        item = self.create().get_json()["scenario"]
        updated = runner._get_configured_scenarios()
        self.assertEqual(len(updated), len(initial) + 1)
        self.assertTrue(any(detect_error_code(event.message) == item["error_code"] for scenario in updated for event in scenario.events()))

    def test_new_error_uses_manual_flow_then_learned_script_on_recurrence_without_manual_form(self):
        created = self.create().get_json()
        log = [json.loads(line) for line in self.path.read_text().splitlines() if json.loads(line)["level"] == "ERROR"][0]
        searcher, generator = Mock(), Mock()
        processor = LogProcessor(self.repo, searcher, generator, incident_service=self.service)
        first = processor.process(log)["recommendation"]
        self.assertEqual(first["status"], "manual_required")
        incident = self.repo.get_operational_incident(first["incident_id"])
        self.assertTrue(manual_action_available(incident))
        ManualRemediationService(self.repo).submit({"incident_id": incident["incident_id"], "incident_version": incident["version"],
            "registration_id": "MANUAL-new-error", "operator": "tester", "method": "복구 완료", "performed": True, "recovered": True},
            attachment=("recover.sh", b"#!/bin/bash\necho recovered\n"))
        rec = processor.process(log)["recommendation"]
        self.assertEqual(rec["status"], "learned_script")
        incident = self.repo.get_operational_incident(rec["incident_id"])
        self.assertFalse(manual_action_available(incident))
        detail = self.api.get("/api/v1/log-generator/incidents/" + incident["incident_id"]).get_json()
        self.assertFalse(detail["manual_action_available"])
        body = {"incident_id": incident["incident_id"], "incident_version": incident["version"],
                "recommendation_id": rec["recommendation_id"], "action_id": rec["actions"][0]["action_id"],
                "approved_by": "tester", "target": rec["targets"][0]}
        self.redis.set(PREFIX + "heartbeat", "ready")
        with patch("operations.script_sandbox.client", return_value=self.redis), patch(
            "operations.script_sandbox.SandboxBackend.perform", return_value={"status": "success", "execution_mode": "simulation"}
        ):
            approved = self.api.post("/api/v1/remediations/approve", json=body)
            self.assertEqual(approved.status_code, 200, approved.get_json())
            diagnosis = self.api.post("/api/v1/remediations/diagnose", json=body)
            # The initial approval changed its version/status; it must not accept stale requests.
            self.assertEqual(diagnosis.status_code, 409)
        searcher.search.assert_not_called()
        generator.generate.assert_not_called()

    def test_create_button_exists_only_in_admin_html(self):
        self.assertIn('id="create-error"', self.api.get("/admin").get_data(as_text=True))
        self.assertNotIn('id="create-error"', self.api.get("/client").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()

import copy
import hashlib
import os
import tempfile
import unittest
from unittest.mock import patch, Mock

import fakeredis
from flask import Flask

from aiops.manual_remediation_service import ManualRemediationService
from aiops.operational_incident_service import OperationalIncidentService
from config import ERROR_RULES
from operations.execution import ExecutionCoordinator
from operations.scenario_scripts import catalog, runtime_for, script_path, ScenarioScriptBackend
from operations.settings import bind_recommendation, manual_action_available
from routes import remediation_routes, log_generator_routes
from support import MemoryRepository


class RegisteredScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {"SCENARIO_SCRIPT_STATE_DIR": self.temp.name})
        env.start(); self.addCleanup(env.stop)
        registry = patch("operations.settings.registry", return_value=[])
        registry.start(); self.addCleanup(registry.stop)
        self.repo = MemoryRepository()
        self.service = OperationalIncidentService(self.repo)
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self.transport = Mock()
        self.manager = ExecutionCoordinator(self.redis, self.transport)
        for name, value in (("repository", self.repo), ("operational_incident_service", self.service), ("coordinator", lambda: self.manager)):
            p = patch.object(remediation_routes, name, value)
            p.start(); self.addCleanup(p.stop)
        app = Flask(__name__); app.register_blueprint(remediation_routes.remediation_blueprint)
        self.api = app.test_client()

    def incident(self, code="MEMORY_LEAK", **extra):
        incident = self.service.start({"host": "web01", "service": "order-api", "environment": "simulation", "synthetic": True, "message": code, **extra}, code)
        candidates = ERROR_RULES[code]["remediation_candidates"]
        recommendation, incident = self.service.complete_analysis(incident, {"runbooks": [{"script_id": candidates[0], "confidence": 80}] if candidates else []})
        self.repo.recommendations[recommendation["recommendation_id"]] = recommendation
        return incident, recommendation

    def approval(self, incident, recommendation):
        action = recommendation["actions"][0]
        return {"incident_id": incident["incident_id"], "incident_version": incident["version"], "recommendation_id": recommendation["recommendation_id"], "action_id": action["action_id"], "approved_by": "tester", "target": action["targets"][0]}

    def test_catalog_restores_every_previously_registered_script_and_executes_exact_file(self):
        ids = {script for rule in ERROR_RULES.values() for key in ("diagnostic_scripts", "remediation_candidates") for script in rule[key]}
        self.assertEqual(set(catalog()), ids)
        self.assertEqual(len(ids), 58)
        backend = ScenarioScriptBackend()
        for script_id, item in catalog().items():
            with self.subTest(script_id=script_id):
                path = script_path(script_id, item["kind"])
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"])
                result = backend.perform({"script_id": script_id, "kind": item["kind"]})
                self.assertEqual(result["status"], "success")
                if item["kind"] == "remediation":
                    self.assertIn("[" + script_id + "]", result["stdout"])
                else:
                    self.assertIn("TEST_", result["stdout"])
                self.assertEqual(result["execution_mode"], "simulation")

    def test_every_supported_generator_error_approves_and_verifies_with_original_script(self):
        supported = 0
        for scenario, (_, _, code) in log_generator_routes.SCENARIO_REGISTRY.items():
            if not ERROR_RULES[code]["remediation_candidates"]:
                continue
            with self.subTest(scenario=scenario):
                incident, rec = self.incident(code)
                body = self.approval(incident, rec)
                response = self.api.post("/api/v1/remediations/approve", json=body)
                result = response.get_json()
                self.assertEqual(response.status_code, 200, result)
                self.assertEqual(result["execution_mode"], "simulation")
                self.assertIn(rec["actions"][0]["script_id"], result["stdout"])
                self.assertEqual(self.repo.incidents[incident["incident_id"]]["status"], "MONITORING")
                receipt = self.api.post("/api/v1/remediations/approve", json=body).get_json()
                self.assertTrue(receipt["duplicate"])
                verified = self.api.post("/api/v1/remediations/verify", json={"execution_id": result["execution_id"]}).get_json()
                self.assertTrue(verified["recovered"])
                self.assertEqual(verified["execution_mode"], "simulation")
                self.assertEqual(self.repo.incidents[incident["incident_id"]]["recovery_confirmation"], "simulation")
                supported += 1
        self.assertEqual(supported, 19)
        self.transport.request.assert_not_called()

    def test_rate_limit_without_script_offers_manual_registration(self):
        incident, rec = self.incident("RATE_LIMIT_EXCEEDED")
        self.assertEqual(rec["targets"], [])
        self.assertTrue(manual_action_available(incident))

    def test_separate_api_sessions_share_execution_and_verified_completion(self):
        incident, rec = self.incident()
        self.repo.recent_incident_logs = lambda *args, **kwargs: []
        app = Flask(__name__)
        app.register_blueprint(log_generator_routes.log_generator_blueprint)
        app.register_blueprint(remediation_routes.remediation_blueprint)
        observer = app.test_client()
        path = "/api/v1/log-generator/incidents/" + incident["incident_id"]
        with patch.object(log_generator_routes, "repository", self.repo):
            self.assertEqual(observer.get(path).get_json()["processing"]["state"], "open")
            executed = self.api.post("/api/v1/remediations/approve", json=self.approval(incident, rec)).get_json()
            self.assertEqual(executed["status"], "success")
            pending = observer.get(path).get_json()
            self.assertEqual(pending["processing"]["state"], "action_completed")
            self.assertEqual(pending["execution"]["execution_id"], executed["execution_id"])
            verified = observer.post("/api/v1/remediations/verify", json={"execution_id": executed["execution_id"]}).get_json()
            self.assertTrue(verified["recovered"])
            self.assertEqual(verified["processing"]["state"], "completed")
            # A newly opened session reads the same durable record and history.
            completed = app.test_client().get(path).get_json()
            self.assertEqual(completed["processing"]["state"], "completed")
            self.assertEqual(completed["incident"]["recovered_at"], verified["incident"]["recovered_at"])
            self.assertEqual(completed["decisions"][0]["execution_id"], executed["execution_id"])

    def test_real_and_unbound_simulation_targets_never_use_test_scripts(self):
        for extra in ({"synthetic": False}, {"environment": "prod"}, {"service": "payment-api"}):
            incident, rec = self.incident(**extra)
            self.assertEqual(rec["targets"], [])
        incident, rec = self.incident()
        body = self.approval(incident, rec)
        body["target"]["host"] = "different-host"
        self.assertEqual(self.api.post("/api/v1/remediations/approve", json=body).status_code, 409)

    def test_resource_fallback_still_exposes_registered_simulation_actions(self):
        incident = self.service.start({"host": "web01", "environment": "simulation", "service": "order-api", "synthetic": True, "message": "OutOfMemoryError"}, "MEMORY_LEAK")
        rec, incident = self.service.complete_analysis(incident, {"status": "resource_guidance", "summary": "low confidence", "runbooks": []}, status="INVESTIGATING")
        self.repo.recommendations[rec["recommendation_id"]] = rec
        self.assertEqual(len(rec["actions"]), 2)
        self.assertEqual(self.api.post("/api/v1/remediations/approve", json=self.approval(incident, rec)).status_code, 200)

    def test_older_recommendation_with_empty_targets_is_rebound_without_new_analysis(self):
        incident, rec = self.incident()
        original_id = rec["recommendation_id"]
        for action in rec["actions"]: action.pop("targets", None)
        rec["targets"] = []
        self.repo.recommendations[original_id] = rec
        bound = bind_recommendation(incident, rec)
        self.assertEqual(bound["recommendation_id"], original_id)
        self.assertEqual(self.api.post("/api/v1/remediations/approve", json=self.approval(incident, bound)).status_code, 200)

    def test_script_missing_or_modified_is_not_offered_or_run(self):
        incident, rec = self.incident()
        with patch("operations.scenario_scripts.script_path", side_effect=ValueError("changed")):
            self.assertEqual(bind_recommendation(incident, rec)["targets"], [])
        real = catalog()
        altered = copy.deepcopy(real); altered["restart_application"]["sha256"] = "bad-hash"
        with patch("operations.scenario_scripts.catalog", return_value=altered):
            with self.assertRaisesRegex(ValueError, "changed or missing"):
                script_path("restart_application", "remediation")
        with self.assertRaises(ValueError): script_path("../../arbitrary", "remediation")

    def test_subprocess_receives_no_operator_arguments_or_credentials(self):
        from types import SimpleNamespace
        with patch("operations.scenario_scripts.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="ok", stderr="")) as run:
            ScenarioScriptBackend().perform({"script_id": "restart_application", "kind": "remediation", "method": "$(touch /tmp/forbidden)"})
        self.assertEqual(len(run.call_args.args[0]), 2)
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertEqual(set(run.call_args.kwargs["env"]), {"PATH", "LANG"})
        self.assertEqual(run.call_args.kwargs["timeout"], 10)

    def test_journal_survives_new_runtime_and_does_not_execute_same_id_again(self):
        incident, rec = self.incident()
        target = rec["targets"][0]
        runtime = runtime_for(target)
        body = {"target": target, "script_id": "restart_application", "kind": "remediation", "execution_id": "EXEC-RESTART", "policy_digest": runtime.digest}
        runtime.execute(body)
        with patch.object(ScenarioScriptBackend, "perform", side_effect=AssertionError("must not rerun")):
            self.assertEqual(runtime_for(target).execute(body)["status"], "success")

    def test_changed_action_binding_is_rechecked_even_if_other_actions_keep_the_target(self):
        incident, rec = self.incident()
        body = self.approval(incident, rec)
        context = {"incident": incident, "recommendation": rec, "action": rec["actions"][0], "script_id": rec["actions"][0]["script_id"]}
        prepared = self.manager.prepare(context, body["target"])
        body["preflight_id"] = prepared["preflight_id"]
        context["action"] = {**context["action"], "targets": []}
        with self.assertRaisesRegex(ValueError, "no longer bound"):
            self.manager.validate_proof(body, context)
        self.assertEqual(self.repo.executions, {})


class ManualActionTests(unittest.TestCase):
    def setUp(self):
        self.repo = MemoryRepository()
        self.repo.incidents["INC-MANUAL"] = {
            "incident_id": "INC-MANUAL", "version": 2, "status": "INVESTIGATING",
            "environment": "prod", "service": "orders", "affected_hosts": ["orders-01"],
            "error_code": "UNKNOWN_ERROR", "latest_recommendation": {"actions": [], "targets": []},
        }
        self.body = {"incident_id": "INC-MANUAL", "incident_version": 2, "registration_id": "MANUAL-unique-request", "operator": "operator", "method": "서비스 밖에서 설정 수정 후 서비스 재기동", "performed": True, "recovered": False}
        self.service = ManualRemediationService(self.repo)
        registry = patch("operations.settings.registry", return_value=[])
        registry.start(); self.addCleanup(registry.stop)
        app = Flask(__name__); app.register_blueprint(remediation_routes.remediation_blueprint)
        app.register_blueprint(log_generator_routes.log_generator_blueprint)
        self.api = app.test_client()
        self.repo.recent_incident_logs = lambda *args, **kwargs: []
        for module in (remediation_routes, log_generator_routes):
            p = patch.object(module, "repository", self.repo); p.start(); self.addCleanup(p.stop)

    def test_registration_persists_service_method_operator_and_pending_recovery(self):
        result = self.service.submit(self.body)
        stored = self.repo.get_operational_incident("INC-MANUAL")
        self.assertEqual(stored["status"], "MONITORING")
        self.assertEqual(stored["version"], 3)
        record = result["manual_action"]
        self.assertEqual(record["service"], "orders")
        self.assertEqual(record["affected_hosts"], ["orders-01"])
        self.assertEqual(record["operator"], "operator")
        self.assertEqual(record["method"], self.body["method"])
        self.assertTrue(manual_action_available(stored))
        detail = self.api.get("/api/v1/log-generator/incidents/INC-MANUAL").get_json()
        self.assertEqual(detail["incident"]["manual_actions"][0]["method"], self.body["method"])
        self.assertTrue(detail["manual_action_available"])

    def test_operator_confirmed_recovery_is_explicit_and_not_an_automatic_probe(self):
        result = self.service.submit({**self.body, "recovered": True})
        self.assertEqual(result["incident"]["status"], "RESOLVED")
        self.assertEqual(result["incident"]["recovery_confirmation"], "operator_report")
        self.assertEqual(self.repo.verifications, [])

    def test_lost_response_retry_survives_service_restart_without_duplicate_history(self):
        self.service.submit(self.body)
        result = ManualRemediationService(self.repo).submit(self.body)
        self.assertTrue(result["duplicate"])
        self.assertEqual(len(self.repo.incidents["INC-MANUAL"]["manual_actions"]), 1)
        self.assertEqual(self.repo.incidents["INC-MANUAL"]["version"], 3)
        with self.assertRaisesRegex(ValueError, "reused"):
            self.service.submit({**self.body, "method": "different"})

    def test_followup_registration_can_record_operator_recovery(self):
        self.service.submit(self.body)
        result = self.service.submit({**self.body, "incident_version": 3, "registration_id": "MANUAL-followup", "recovered": True, "method": "재기동 후 주문 요청 정상 처리 확인"})
        self.assertEqual(result["incident"]["status"], "RESOLVED")
        self.assertEqual(len(result["incident"]["manual_actions"]), 2)

    def test_invalid_or_stale_registration_never_changes_incident(self):
        for changes in ({"method": " "}, {"method": "a" * 8001}, {"performed": False}, {"operator": ""}, {"recovered": "false"}, {"incident_version": True}, {"incident_version": 1}, {"registration_id": "bad"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.api.post("/api/v1/remediations/manual", json={**self.body, **changes}).status_code, 409)
                self.assertEqual(self.repo.incidents["INC-MANUAL"]["version"], 2)
        self.assertEqual(self.api.post("/api/v1/remediations/manual", json={**self.body, "incident_id": "missing"}).status_code, 404)

    def test_analyzing_or_automated_execution_cannot_be_bypassed_by_manual_registration(self):
        for status in ("ANALYZING", "REMEDIATING", "RESOLVED", "MONITORING"):
            self.repo.incidents["INC-MANUAL"]["status"] = status
            with self.assertRaisesRegex(ValueError, "unavailable"):
                self.service.submit(self.body)
        self.repo.incidents["INC-MANUAL"].update(status="INVESTIGATING", active_execution_id="EXEC-ACTIVE")
        with self.assertRaises(ValueError): self.service.submit(self.body)

    def test_target_available_blocks_manual_registration(self):
        incident = self.repo.incidents["INC-MANUAL"]
        incident["latest_recommendation"] = {"actions": [{"script_id": "restart_application"}]}
        with patch("operations.settings.registry", return_value=[{"host": "orders-01", "environment": "prod", "service": "orders", "instance": "one"}]):
            with self.assertRaises(ValueError): self.service.submit(self.body)

    def test_registration_keeps_text_as_data_redacts_and_never_runs_a_command(self):
        method = '<script>alert(1)</script> $(touch /tmp/never) password=private'
        with patch("subprocess.run", side_effect=AssertionError("must not run")):
            response = self.api.post("/api/v1/remediations/manual", json={**self.body, "method": method})
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("private", response.get_data(as_text=True))
        self.assertIn("$(touch /tmp/never)", response.get_json()["manual_action"]["method"])

    def test_concurrent_registration_cas_failure_reports_conflict_without_overwrite(self):
        with patch.object(self.repo, "update_operational_incident", side_effect=RuntimeError("version conflict")):
            response = self.api.post("/api/v1/remediations/manual", json=self.body)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("manual_actions", self.repo.incidents["INC-MANUAL"])


if __name__ == "__main__":
    unittest.main()

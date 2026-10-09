import unittest
from unittest.mock import patch

from flask import Flask

from operations.incident_presentation import processing_summary
from routes import log_generator_routes
from routes.web_routes import web_blueprint
from support import MemoryRepository


class IncidentCompletionTests(unittest.TestCase):
    def setUp(self):
        self.repo = MemoryRepository()
        self.repo.incidents["INC-COMPLETE"] = {
            "incident_id": "INC-COMPLETE", "version": 5, "status": "RESOLVED",
            "service": "payment-api", "environment": "prod", "affected_hosts": ["payment-01"],
            "error_code": "MEMORY_LEAK", "latest_recommendation_id": "REC-COMPLETE",
            "recovered_at": "2026-10-09T17:00:00+00:00", "recovery_confirmation": "business_probe",
            "last_execution_id": "EXEC-COMPLETE", "latest_recommendation": {"actions": []},
        }
        self.repo.executions["EXEC-COMPLETE"] = {
            "execution_id": "EXEC-COMPLETE", "incident_id": "INC-COMPLETE",
            "recommendation_id": "REC-COMPLETE", "action_id": "ACTION-1", "script_id": "restart_application",
            "approved_by": "operator-one", "approved_at": "2026-10-09T16:58:00+00:00",
            "result": {"status": "success", "finished_at": 1791565200, "stdout": "password=private restarted"},
        }
        self.repo.recent_incident_logs = lambda *args, **kwargs: []
        self.repo.list_operational_incidents = lambda minutes: list(self.repo.incidents.values())
        p = patch.object(log_generator_routes, "repository", self.repo)
        p.start(); self.addCleanup(p.stop)
        app = Flask(__name__)
        app.register_blueprint(log_generator_routes.log_generator_blueprint)
        app.register_blueprint(web_blueprint)
        self.api = app.test_client()

    def detail(self):
        response = self.api.get("/api/v1/log-generator/incidents/INC-COMPLETE")
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_resolved_detail_restores_completed_status_timestamp_operator_and_execution(self):
        data = self.detail()
        self.assertEqual(data["processing"]["state"], "completed")
        self.assertEqual(data["processing"]["label"], "처리 완료")
        self.assertEqual(data["processing"]["completed_at"], self.repo.incidents["INC-COMPLETE"]["recovered_at"])
        self.assertEqual(data["processing"]["operator"], "operator-one")
        self.assertEqual(data["processing"]["method"], "restart_application")
        self.assertEqual(data["execution"]["execution_id"], "EXEC-COMPLETE")
        self.assertEqual(data["decisions"][0]["execution_id"], "EXEC-COMPLETE")
        self.assertEqual(data["decisions"][0]["result"]["execution_id"], "EXEC-COMPLETE")
        self.assertNotIn("private", str(data))

    def test_command_success_without_recovery_remains_pending_confirmation(self):
        self.repo.incidents["INC-COMPLETE"].update(status="MONITORING", recovery_confirmation="pending_execution")
        data = self.detail()
        self.assertEqual(data["processing"]["state"], "action_completed")
        self.assertEqual(data["processing"]["label"], "조치 완료 · 복구 확인 대기")
        self.assertEqual(data["processing"]["operator"], "operator-one")

    def test_old_resolved_incident_without_execution_or_recommendation_is_completed(self):
        self.repo.incidents["INC-COMPLETE"] = {"incident_id": "INC-COMPLETE", "status": "RESOLVED"}
        data = self.detail()
        self.assertEqual(data["processing"]["state"], "completed")
        self.assertEqual(data["decisions"], [])
        self.assertIsNone(data["execution"])

    def test_execution_query_failure_keeps_stored_completed_status_and_summary(self):
        self.repo.incidents["INC-COMPLETE"]["last_execution"] = {"operator": "stored-operator", "script_id": "restart_application"}
        with patch.object(self.repo, "find_remediation_executions", side_effect=ConnectionError):
            data = self.detail()
        self.assertEqual(data["executions_status"], "unavailable")
        self.assertEqual(data["processing"]["state"], "completed")
        self.assertEqual(data["processing"]["operator"], "stored-operator")

    def test_unrelated_execution_is_not_displayed_for_selected_incident(self):
        self.repo.executions["EXEC-COMPLETE"]["incident_id"] = "INC-OTHER"
        self.repo.incidents["INC-COMPLETE"]["latest_recommendation_id"] = None
        data = self.detail()
        self.assertIsNone(data["execution"])
        self.assertIsNone(data["processing"]["operator"])

    def test_manual_completion_has_operator_method_and_explicit_confirmation(self):
        incident = self.repo.incidents["INC-COMPLETE"]
        incident.update(recovery_confirmation="operator_report", last_manual_action_id="MANUAL-DONE", manual_actions=[{
            "registration_id": "MANUAL-DONE", "operator": "manual-operator", "method": "설정 변경 후 주문 성공 확인",
            "registered_at": "2026-10-09T17:00:00+00:00", "recovered": True,
        }])
        data = self.detail()
        self.assertEqual(data["processing"]["operator"], "manual-operator")
        self.assertEqual(data["processing"]["method"], "설정 변경 후 주문 성공 확인")
        self.assertEqual(data["processing"]["confirmation"], "operator_report")

    def test_new_execution_is_not_described_using_an_old_manual_action(self):
        incident = self.repo.incidents["INC-COMPLETE"]
        incident.update(last_manual_action_id="MANUAL-OLD", manual_actions=[{
            "registration_id": "MANUAL-OLD", "operator": "previous-operator", "method": "old-method",
        }])
        data = self.detail()
        self.assertEqual(data["processing"]["operator"], "operator-one")
        self.assertEqual(data["processing"]["method"], "restart_application")

    def test_reopened_or_failed_incident_does_not_show_completed_from_old_receipt(self):
        incident = self.repo.incidents["INC-COMPLETE"]
        for status in ("REOPENED", "ACTION_REQUIRED", "REMEDIATING", "INVESTIGATING", "ANALYZING"):
            with self.subTest(status=status):
                incident["status"] = status
                self.assertEqual(self.detail()["processing"]["state"], "open")

    def test_list_preserves_completed_status_and_both_pages_use_operational_wording(self):
        data = self.api.get("/api/v1/log-generator/incidents").get_json()
        self.assertEqual(data["incidents"][0]["processing"]["state"], "completed")
        for mode in ("admin", "client"):
            html = self.api.get("/" + mode).get_data(as_text=True)
            self.assertIn('id="incident-processing"', html)
            self.assertIn('id="completed-incidents"', html)
            self.assertIn("처리 완료", html)
            self.assertNotIn("모의", html)


if __name__ == "__main__":
    unittest.main()

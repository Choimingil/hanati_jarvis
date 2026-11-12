"""결재·보류(킵)·에러별 예외 처리·장애 이력 기능을 log_generator 시나리오로 검증한다."""

from datetime import UTC, datetime, timedelta
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
from log_processor import LogProcessor
from operations.execution import ExecutionCoordinator
from operations.incident_workflow import WorkflowStore
from operations.privacy import redact
from routes import log_generator_routes, remediation_routes, workflow_routes  # adds log_generator to sys.path
from registry import SCENARIO_REGISTRY, VERIFICATION_SCENARIOS, get_scenarios  # noqa: E402
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

    def search_similar_incidents(self, error_code, normalized_message=None, limit=50):
        return [dict(item) for item in self.incidents.values() if item.get("error_code") == error_code][:limit]

    def list_operational_incidents(self, minutes=10):
        return [dict(item) for item in self.incidents.values()]

    def list_held_incidents(self):
        return [dict(item) for item in self.incidents.values() if item.get("status") == "ON_HOLD"]

    def recent_incident_logs(self, incident_id, minutes=10):
        return []


class IncidentWorkflowTests(unittest.TestCase):
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
        patches = [
            patch.dict(os.environ, {
                "LEARNED_SCRIPT_STATE_DIR": str(Path(self.temp.name) / "learned"),
                "SCENARIO_SCRIPT_STATE_DIR": str(Path(self.temp.name) / "registered"),
                "NOTIFICATION_WEBHOOK_URL": "",
            }),
            patch.object(trigger, "FLUENTBIT_LOG_PATH", self.path),
            patch("scenario.scenario_runner.time.sleep"), patch("builtins.print"),
            patch("operations.settings.registry", return_value=[]),
            patch.object(remediation_routes, "repository", self.repo),
            patch.object(remediation_routes, "operational_incident_service", self.service),
            patch.object(remediation_routes, "coordinator", return_value=self.manager),
            patch.object(workflow_routes, "repository", self.repo),
            patch.object(workflow_routes, "operational_incident_service", self.service),
            patch.object(log_generator_routes, "repository", self.repo),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        app = Flask(__name__)

        # app.py와 같이 모든 JSON 응답을 마스킹한다.
        @app.after_request
        def redact_json_output(response):
            if response.is_json:
                response.set_data(app.json.dumps(redact(response.get_json())))
            return response

        app.register_blueprint(remediation_routes.remediation_blueprint)
        app.register_blueprint(workflow_routes.workflow_blueprint)
        app.register_blueprint(log_generator_routes.log_generator_blueprint)
        self.api = app.test_client()

    # ------------------------------------------------------------ helpers
    def emit(self, key):
        offset = self.path.stat().st_size if self.path.exists() else 0
        trigger.run_scenario(key)
        with self.path.open() as stream:
            stream.seek(offset)
            logs = [json.loads(line) for line in stream]
        return [self.processor.process(log) for log in logs]

    def emit_and_analyze(self, key):
        results = self.emit(key)
        recommendations = [item["recommendation"] for item in results if item.get("recommendation")]
        self.assertEqual(len(recommendations), 1, results)
        return recommendations[0]

    def request_body(self, rec, script_id):
        incident = self.repo.get_operational_incident(rec["incident_id"])
        action = next(item for item in rec["actions"] if item["script_id"] == script_id)
        return {"incident_id": incident["incident_id"], "incident_version": incident["version"],
                "recommendation_id": rec["recommendation_id"], "action_id": action["action_id"],
                "requested_by": "operator", "target": action["targets"][0]}

    def request_approval(self, rec, script_id="compress_old_logs"):
        response = self.api.post("/api/v1/approvals", json=self.request_body(rec, script_id))
        self.assertIn(response.status_code, (200, 201), response.get_json())
        return response.get_json()["approval"]

    def approve(self, approval_id, approver="admin"):
        return self.api.post(f"/api/v1/approvals/{approval_id}/approve", json={"approver": approver})

    # -------------------------------------------------------------- 결재
    def test_approval_request_does_not_execute_until_admin_approves(self):
        rec = self.emit_and_analyze("disk_full")
        approval = self.request_approval(rec)
        self.assertEqual(approval["status"], "PENDING")
        incident = self.repo.get_operational_incident(rec["incident_id"])
        self.assertNotIn(incident["status"], {"REMEDIATING", "MONITORING", "RESOLVED"})
        self.assertFalse(self.repo.executions)

        again = self.api.post("/api/v1/approvals", json=self.request_body(rec, "cleanup_temp_files"))
        self.assertEqual(again.get_json()["status"], "already_pending")
        self.assertEqual(again.get_json()["approval"]["approval_id"], approval["approval_id"])

        listed = self.api.get("/api/v1/approvals?status=PENDING").get_json()["approvals"]
        self.assertEqual([item["approval_id"] for item in listed], [approval["approval_id"]])
        incidents = self.api.get("/api/v1/log-generator/incidents").get_json()["incidents"]
        self.assertTrue(next(i for i in incidents if i["incident_id"] == rec["incident_id"])["pending_approval"])

        response = self.approve(approval["approval_id"])
        result = response.get_json()
        self.assertEqual(response.status_code, 200, result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["approval"]["status"], "APPROVED")
        self.assertEqual(result["approval"]["execution_id"], result["execution_id"])
        self.assertEqual(self.repo.get_operational_incident(rec["incident_id"])["status"], "RESOLVED")
        self.assertEqual(self.approve(approval["approval_id"]).status_code, 409)
        self.assertEqual(len(self.repo.executions), 1)
        kinds = [item["kind"] for item in WorkflowStore().list_notifications()[0]]
        self.assertIn("approval_requested", kinds)
        self.assertIn("approval_decided", kinds)

    def test_digit_heavy_approval_id_survives_response_redaction(self):
        # 무작위 hex ID에 숫자가 13자리 이상 이어지면 카드번호로 마스킹되던 문제.
        rec = self.emit_and_analyze("disk_full")
        with patch("operations.incident_workflow.uuid.uuid4",
                   return_value=Mock(hex="5454640746474091ffff")):
            approval = self.request_approval(rec)
        self.assertEqual(approval["approval_id"], "APR-5454640746474091")
        listed = self.api.get("/api/v1/approvals?status=PENDING").get_json()["approvals"]
        self.assertEqual(listed[0]["approval_id"], "APR-5454640746474091")
        result = self.approve(listed[0]["approval_id"]).get_json()
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(result["approval"]["approval_id"], "APR-5454640746474091")

    def test_rejected_approval_never_executes_and_can_be_requested_again(self):
        rec = self.emit_and_analyze("disk_full")
        approval = self.request_approval(rec)
        response = self.api.post(f"/api/v1/approvals/{approval['approval_id']}/reject",
                                 json={"approver": "admin", "reason": "작업 시간 외"})
        self.assertEqual(response.get_json()["approval"]["status"], "REJECTED")
        self.assertEqual(response.get_json()["approval"]["decision_reason"], "작업 시간 외")
        self.assertEqual(self.approve(approval["approval_id"]).status_code, 409)
        self.assertFalse(self.repo.executions)
        second = self.request_approval(rec)
        self.assertNotEqual(second["approval_id"], approval["approval_id"])

    def test_reanalysis_expires_pending_approval_so_new_runbook_can_be_chosen(self):
        rec = self.emit_and_analyze("disk_full")
        approval = self.request_approval(rec)
        incident = self.repo.get_operational_incident(rec["incident_id"])
        # 같은 오류가 다시 발생해 재분석되면 이전 회차의 결재 대기는 실행하지 않고 만료한다.
        newer, _ = self.service.complete_analysis(incident, {"error_code": "DISK_FULL", "cause": "re-analysis",
                                                             "runbooks": [{"script_id": "compress_old_logs"}]})
        self.repo.recommendations[newer["recommendation_id"]] = newer
        detail = self.api.get(f"/api/v1/log-generator/incidents/{rec['incident_id']}").get_json()
        self.assertEqual([item["status"] for item in detail["approvals"]], ["EXPIRED"])
        incidents = self.api.get("/api/v1/log-generator/incidents").get_json()["incidents"]
        self.assertFalse(next(i for i in incidents if i["incident_id"] == rec["incident_id"])["pending_approval"])
        response = self.approve(approval["approval_id"])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["approval"]["status"], "EXPIRED")
        self.assertFalse(self.repo.executions)
        # 새 분석의 조치는 다시 선택해 결재를 요청할 수 있다.
        second = self.request_approval(newer)
        self.assertEqual(second["status"], "PENDING")
        self.assertEqual(second["recommendation_id"], newer["recommendation_id"])
        result = self.approve(second["approval_id"]).get_json()
        self.assertEqual(result["status"], "success", result)

    def test_rerun_after_executed_approval_does_not_show_previous_execution_result(self):
        rec = self.emit_and_analyze("disk_full")
        approval = self.request_approval(rec)
        self.assertEqual(self.approve(approval["approval_id"]).get_json()["status"], "success")
        detail = self.api.get(f"/api/v1/log-generator/incidents/{rec['incident_id']}").get_json()
        self.assertIsNotNone(detail["execution"])
        self.emit("disk_full")
        detail = self.api.get(f"/api/v1/log-generator/incidents/{rec['incident_id']}").get_json()
        self.assertNotEqual(detail["incident"]["latest_recommendation_id"], rec["recommendation_id"])
        self.assertIsNone(detail["execution"])
        self.assertEqual(detail["decisions"], [])

    def test_rerun_of_same_scenario_does_not_inherit_old_pending_approval(self):
        rec = self.emit_and_analyze("disk_full")
        stale = self.request_approval(rec)
        incident = self.repo.get_operational_incident(rec["incident_id"])
        # 이전 회차 결재가 남은 상태에서 장애가 다른 경로로 처리 완료된 뒤 같은 시나리오를 다시 발생시킨다.
        self.repo.update_operational_incident(incident["incident_id"], {"status": "RESOLVED"}, incident["version"])
        self.emit("disk_full")
        reopened = self.repo.get_operational_incident(rec["incident_id"])
        self.assertNotEqual(reopened["latest_recommendation_id"], rec["recommendation_id"])
        pending = self.api.get("/api/v1/approvals?status=PENDING").get_json()["approvals"]
        self.assertEqual(pending, [])
        self.assertEqual(WorkflowStore().get_approval(stale["approval_id"])["status"], "EXPIRED")

    def test_expired_recommendation_closes_the_approval_without_execution(self):
        rec = self.emit_and_analyze("disk_full")
        approval = self.request_approval(rec)
        stored = self.repo.recommendations[rec["recommendation_id"]]
        stored["expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        response = self.approve(approval["approval_id"])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["approval"]["status"], "FAILED")
        self.assertEqual(response.get_json()["approval"]["last_error"], "expired recommendation")
        self.assertFalse(self.repo.executions)

    def test_approval_request_requires_bound_target(self):
        rec = self.emit_and_analyze("disk_full")
        body = self.request_body(rec, "compress_old_logs")
        body["target"] = {**body["target"], "host": "other-host"}
        response = self.api.post("/api/v1/approvals", json=body)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["reason"], "target not bound to recommendation")

    # ---------------------------------------------------------- 보류(킵)
    def test_hold_keeps_incident_aggregates_without_reanalysis_and_release_restores_action(self):
        rec = self.emit_and_analyze("disk_full")
        before = self.repo.get_operational_incident(rec["incident_id"])
        held = self.api.post(f"/api/v1/incidents/{rec['incident_id']}/hold",
                             json={"operator": "operator", "reason": "변경 작업 일정 대기"}).get_json()
        self.assertEqual(held["incident"]["status"], "ON_HOLD")
        self.assertEqual(held["incident"]["version"], before["version"])
        self.assertEqual(held["incident"]["hold"]["previous_status"], before["status"])

        results = self.emit("disk_full")
        self.assertIn("held", [item["status"] for item in results])
        after = self.repo.get_operational_incident(rec["incident_id"])
        self.assertEqual(after["status"], "ON_HOLD")
        self.assertGreater(after["occurrence_count"], before["occurrence_count"])
        self.assertEqual(after["latest_recommendation_id"], rec["recommendation_id"])

        blocked = self.api.post("/api/v1/approvals", json=self.request_body(rec, "compress_old_logs"))
        self.assertEqual(blocked.get_json()["reason"], "incident is not actionable")
        detail = self.api.get(f"/api/v1/log-generator/incidents/{rec['incident_id']}").get_json()
        self.assertEqual(detail["processing"]["state"], "on_hold")
        incidents = self.api.get("/api/v1/log-generator/incidents").get_json()["incidents"]
        self.assertIn(rec["incident_id"], [item["incident_id"] for item in incidents])

        released = self.api.post(f"/api/v1/incidents/{rec['incident_id']}/release",
                                 json={"operator": "operator"}).get_json()["incident"]
        self.assertEqual(released["status"], before["status"])
        self.assertTrue(released["hold_history"][-1]["released_at"])
        result = self.approve(self.request_approval(rec)["approval_id"]).get_json()
        self.assertEqual(result["status"], "success", result)

    def test_new_occurrence_after_quiet_period_releases_manual_hold_by_default(self):
        rec = self.emit_and_analyze("disk_full")
        self.api.post(f"/api/v1/incidents/{rec['incident_id']}/hold",
                      json={"operator": "operator", "reason": "변경 작업 일정 대기"})
        incident = self.repo.get_operational_incident(rec["incident_id"])
        # 마지막 발생 후 조용한 시간이 지나 같은 오류가 다시 발생하면 보류가 풀린 상태로 새로 분석한다.
        old = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        self.repo.incidents[rec["incident_id"]] = {**incident, "last_seen": old}
        results = self.emit("disk_full")
        self.assertNotIn("held", [item["status"] for item in results])
        after = self.repo.get_operational_incident(rec["incident_id"])
        self.assertNotEqual(after["status"], "ON_HOLD")
        self.assertIsNone(after.get("hold"))
        self.assertEqual(after["hold_history"][-1]["released_by"], "recurrence")
        self.assertNotEqual(after["latest_recommendation_id"], rec["recommendation_id"])

    def test_hold_is_blocked_while_approval_is_pending(self):
        rec = self.emit_and_analyze("disk_full")
        self.request_approval(rec)
        response = self.api.post(f"/api/v1/incidents/{rec['incident_id']}/hold",
                                 json={"operator": "operator", "reason": "보류"})
        self.assertEqual(response.status_code, 409)
        self.assertNotEqual(self.repo.get_operational_incident(rec["incident_id"])["status"], "ON_HOLD")

    # ------------------------------------------------------ 에러별 예외 처리
    def test_errors_are_not_held_by_default(self):
        self.assertEqual(WorkflowStore().list_rules(), [])
        results = self.emit("legacy_interface_timeout")
        self.assertNotIn("held", [item["status"] for item in results])
        incident = next(iter(self.repo.incidents.values()))
        self.assertNotEqual(incident["status"], "ON_HOLD")

    def test_exception_rule_holds_legacy_timeout_and_throttles_notifications(self):
        WorkflowStore().create_rule({"rule_id": None, "error_code": "LEGACY_INTERFACE_TIMEOUT", "environment": "simulation",
                                     "reason": "대외기관 개선 전까지 즉시 조치 불가", "notify_interval_seconds": 60,
                                     "created_by": "admin"})
        results = self.emit("legacy_interface_timeout")
        self.assertEqual([item["status"] for item in results if item["status"] != "ignored"], ["recommended", "held"])
        incident = next(iter(self.repo.incidents.values()))
        self.assertEqual(incident["error_code"], "LEGACY_INTERFACE_TIMEOUT")
        self.assertEqual(incident["status"], "ON_HOLD")
        self.assertEqual(incident["hold"]["source"], "exception_rule")
        self.assertTrue(incident["hold"]["rule_id"].startswith("RULE-"))
        kinds = [item["kind"] for item in WorkflowStore().list_notifications()[0]]
        self.assertEqual(sorted(kinds), ["exception_hold", "exception_occurrence"])
        # 알림 간격(60초) 안에 다시 발생하면 보류를 유지하고 알림은 늘지 않는다.
        self.emit("legacy_interface_timeout")
        self.assertEqual(len(WorkflowStore().list_notifications()[0]), 2)
        self.assertEqual(self.repo.get_operational_incident(incident["incident_id"])["occurrence_count"], 4)

    def test_rule_registered_from_incident_holds_it_and_applies_to_future_detection(self):
        rec = self.emit_and_analyze("dns_failure")
        response = self.api.post("/api/v1/exception-rules", json={
            "error_code": "DNS_RESOLUTION_FAILURE", "service": "order-api", "environment": "simulation",
            "reason": "DNS 이중화 작업 전까지 보류", "notify_interval_seconds": 0, "created_by": "admin",
            "incident_id": rec["incident_id"],
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["held_incidents"], [rec["incident_id"]])
        self.assertEqual(self.repo.get_operational_incident(rec["incident_id"])["status"], "ON_HOLD")
        self.emit("dns_failure")
        occurrences = [item for item in WorkflowStore().list_notifications()[0] if item["kind"] == "exception_occurrence"]
        self.assertEqual(len(occurrences), 1)
        duplicate = self.api.post("/api/v1/exception-rules", json={
            "error_code": "DNS_RESOLUTION_FAILURE", "service": "order-api", "environment": "simulation",
            "reason": "중복", "notify_interval_seconds": 0, "created_by": "admin"})
        self.assertEqual(duplicate.get_json()["status"], "exists")
        rule_id = response.get_json()["rule"]["rule_id"]
        self.assertEqual(self.api.delete(f"/api/v1/exception-rules/{rule_id}").status_code, 200)
        self.assertNotIn(rule_id, [r["rule_id"] for r in self.api.get("/api/v1/exception-rules").get_json()["rules"]])

    def test_invalid_rule_is_rejected(self):
        response = self.api.post("/api/v1/exception-rules", json={"error_code": "BAD CODE!", "reason": "x", "created_by": "a"})
        self.assertEqual(response.status_code, 400)

    # ---------------------------------------------------------- 장애 이력
    def test_recurrence_scenario_shows_how_the_previous_disk_full_was_resolved(self):
        rec = self.emit_and_analyze("disk_full")
        result = self.approve(self.request_approval(rec)["approval_id"]).get_json()
        self.assertEqual(result["status"], "success", result)
        recurrence = self.emit_and_analyze("disk_full_recurrence")
        self.assertNotEqual(recurrence["incident_id"], rec["incident_id"])
        detail = self.api.get(f"/api/v1/log-generator/incidents/{recurrence['incident_id']}").get_json()
        entries = detail["history"]["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["incident_id"], rec["incident_id"])
        self.assertEqual(entries[0]["script_id"], "compress_old_logs")
        self.assertEqual(entries[0]["method_type"], "script")
        self.assertEqual(entries[0]["operator"], "admin")
        self.assertFalse(entries[0]["same_incident"])
        self.assertEqual(detail["history"]["summary"]["resolved_count"], 1)
        history = self.api.get(f"/api/v1/incidents/{recurrence['incident_id']}/history").get_json()
        self.assertEqual(history["entries"], entries)

    def test_manual_resolution_and_hold_appear_in_history(self):
        rec = self.emit_and_analyze("rate_limit_exceeded")
        incident = self.repo.get_operational_incident(rec["incident_id"])
        self.api.post(f"/api/v1/incidents/{incident['incident_id']}/hold", json={"operator": "op", "reason": "대외 협의"})
        self.api.post(f"/api/v1/incidents/{incident['incident_id']}/release", json={"operator": "op"})
        incident = self.repo.get_operational_incident(rec["incident_id"])
        response = self.api.post("/api/v1/remediations/manual", json={
            "incident_id": incident["incident_id"], "incident_version": incident["version"],
            "registration_id": "MANUAL-history-test", "operator": "tester",
            "method": "클라이언트 호출량 제한 상향", "performed": True, "recovered": True})
        self.assertEqual(response.status_code, 201, response.get_json())
        entries = self.api.get(f"/api/v1/incidents/{incident['incident_id']}/history").get_json()["entries"]
        self.assertEqual([item["kind"] for item in entries], ["resolution", "hold"])
        self.assertEqual(entries[0]["method"], "클라이언트 호출량 제한 상향")
        self.assertEqual(entries[0]["method_type"], "manual")
        self.assertTrue(entries[0]["same_incident"])

    # ----------------------------------------------------------- 시나리오
    def test_verification_scenarios_are_runnable_but_separate_from_default_registry(self):
        self.assertEqual(len(SCENARIO_REGISTRY), 20)
        scenarios = get_scenarios()
        for key in VERIFICATION_SCENARIOS:
            self.assertIn(key, scenarios)
            self.assertNotIn(key, SCENARIO_REGISTRY)
        labels = self.api.get("/api/v1/log-generator/scenarios").get_json()
        self.assertIn("legacy_interface_timeout", [item["key"] for item in labels])


if __name__ == "__main__":
    unittest.main()

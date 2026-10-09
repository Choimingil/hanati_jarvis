"""Shared durable completion state across independent API clients."""

import copy
import unittest
from unittest.mock import Mock, patch

from flask import Flask

from adapters.elastic_adapters import ElasticLogRepository
from routes import log_generator_routes, remediation_routes
from support import MemoryRepository


def api_client():
    app = Flask(__name__)
    app.register_blueprint(log_generator_routes.log_generator_blueprint)
    app.register_blueprint(remediation_routes.remediation_blueprint)
    return app.test_client()


class CompletionSyncTests(unittest.TestCase):
    def setUp(self):
        self.repo = MemoryRepository()
        self.repo.incidents["INC-SHARED"] = {
            "incident_id": "INC-SHARED", "version": 2, "status": "INVESTIGATING",
            "environment": "prod", "service": "orders", "affected_hosts": ["orders-01"],
            "error_code": "UNKNOWN_ERROR", "latest_recommendation": {"actions": [], "targets": []},
        }
        self.repo.recent_incident_logs = lambda *args, **kwargs: []
        self.repo.list_operational_incidents = lambda minutes: copy.deepcopy(list(self.repo.incidents.values()))
        for module in (log_generator_routes, remediation_routes):
            p = patch.object(module, "repository", self.repo)
            p.start(); self.addCleanup(p.stop)
        self.first, self.second = api_client(), api_client()

    def detail(self, client):
        response = client.get("/api/v1/log-generator/incidents/INC-SHARED")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        return response.get_json()

    def test_other_api_instance_reads_manual_completion_and_history(self):
        before = self.detail(self.second)
        self.assertEqual(before["processing"]["state"], "open")
        response = self.first.post("/api/v1/remediations/manual", json={
            "incident_id": "INC-SHARED", "incident_version": 2,
            "registration_id": "MANUAL-shared-session", "operator": "first-operator",
            "method": "설정 변경 후 주문 처리 정상 확인", "performed": True, "recovered": True,
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        after = self.detail(self.second)
        self.assertEqual(after["incident"]["version"], 3)
        self.assertEqual(after["processing"]["state"], "completed")
        self.assertEqual(after["processing"]["operator"], "first-operator")
        self.assertEqual(after["processing"]["method"], "설정 변경 후 주문 처리 정상 확인")
        self.assertFalse(after["manual_action_available"])
        self.assertEqual(self.detail(api_client())["processing"], after["processing"])
        response = self.second.get("/api/v1/log-generator/incidents?minutes=10")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.get_json()["incidents"][0]["processing"]["state"], "completed")

    def test_detail_reads_shared_completion_when_recent_list_expires_or_fails(self):
        self.repo.incidents["INC-SHARED"].update(status="RESOLVED", version=3)
        self.repo.list_operational_incidents = lambda minutes: []
        self.assertEqual(self.second.get("/api/v1/log-generator/incidents").get_json()["incidents"], [])
        self.assertEqual(self.detail(self.second)["processing"]["state"], "completed")
        with patch.object(self.repo, "list_operational_incidents", side_effect=ConnectionError):
            self.assertEqual(self.second.get("/api/v1/log-generator/incidents").status_code, 503)
            self.assertEqual(self.detail(self.second)["processing"]["state"], "completed")

    def test_state_update_waits_for_search_visibility_but_occurrences_do_not(self):
        repo = ElasticLogRepository.__new__(ElasticLogRepository)
        repo.client = Mock()
        repo.client.update.return_value = {"result": "updated", "get": {"_source": {"version": 3}}}
        repo.update_operational_incident("INC-SHARED", {"status": "RESOLVED", "version": 3}, 2)
        self.assertEqual(repo.client.update.call_args.kwargs["refresh"], "wait_for")
        self.assertEqual(repo.client.update.call_args.kwargs["script"]["params"]["expected"], 2)
        repo.client.get.assert_not_called()
        repo.record_incident_occurrence("INC-SHARED", {"occurrence_count": 5}, 3, 4)
        self.assertIs(repo.client.update.call_args.kwargs["refresh"], False)


if __name__ == "__main__":
    unittest.main()

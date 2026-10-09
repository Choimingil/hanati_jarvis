import copy
import unittest
from unittest.mock import Mock, patch

import fakeredis
from flask import Flask

from aiops.operational_incident_service import OperationalIncidentService
from error_detector import SCENARIO_CONTEXT_MESSAGES, detect_error_code, is_context_only_error
from log_processor import LogProcessor
from routes.log_generator_routes import SCENARIO_REGISTRY, log_generator_blueprint
from support import MemoryRepository


class LogRepository(MemoryRepository):
    def __init__(self):
        super().__init__()
        self.logs = []

    def save_log(self, document):
        self.logs.append(copy.deepcopy(document))

    def save_recommendation(self, document):
        recommendation = document["recommendation"]
        self.recommendations[recommendation["recommendation_id"]] = copy.deepcopy(recommendation)


class ContextErrorFilterTests(unittest.TestCase):
    def setUp(self):
        self.repository = LogRepository()
        self.searcher = Mock(search=Mock(return_value=[]))
        self.generator = Mock(generate=Mock(return_value={"cause": "primary error", "runbooks": []}))
        self.processor = LogProcessor(
            self.repository, self.searcher, self.generator,
            incident_service=OperationalIncidentService(self.repository),
        )
        self.processor._run_diagnostics = Mock(return_value=[])

    def log(self, message, synthetic=False):
        return {
            "level": "ERROR", "message": message, "host": "web01", "service": "order-api",
            "environment": "simulation" if synthetic else "production", "synthetic": synthetic,
        }

    def test_all_scenarios_create_only_the_primary_incident_and_recommendation(self):
        context_messages = set()
        log_count = 0
        for _, (scenario, _, expected_code) in SCENARIO_REGISTRY.items():
            with self.subTest(code=expected_code):
                results = []
                for event in scenario().events():
                    if event.level != "ERROR":
                        continue
                    log_count += 1
                    if detect_error_code(event.message) is None:
                        context_messages.add(event.message)
                    results.append(self.processor.process(
                        self.log(event.message, synthetic=True), ingestion_id="job-" + str(log_count)
                    ))
                self.assertEqual(sum(result["status"] == "recommended" for result in results), 1)
                self.assertTrue(all(result["status"] in {"recommended", "ignored"} for result in results))
        self.assertEqual(context_messages, SCENARIO_CONTEXT_MESSAGES)
        self.assertEqual(len(context_messages), 39)
        self.assertEqual(len(self.repository.incidents), len(SCENARIO_REGISTRY))
        self.assertEqual(len(self.repository.recommendations), len(SCENARIO_REGISTRY))
        self.assertEqual(len(self.repository.logs), log_count)
        self.assertNotIn("UNKNOWN_ERROR", {doc["error_code"] for doc in self.repository.incidents.values()})
        excluded = [log for log in self.repository.logs if log.get("ignored_reason") == "scenario_context"]
        self.assertEqual(len(excluded), 39)
        self.assertTrue(all(log["incident_id"] is None for log in excluded))

    def test_reported_messages_are_ignored_without_old_synthetic_flag(self):
        for message in ("Unable to write application data.", "Service entering read-only mode."):
            result = self.processor.process(self.log(message), ingestion_id="old-log")
            self.assertEqual(result["status"], "ignored")
        self.assertFalse(self.repository.incidents)
        self.searcher.search.assert_not_called()
        self.generator.generate.assert_not_called()
        self.assertEqual(len(self.repository.logs), 2)
        self.assertTrue(all(log["ingestion_id"] == "old-log" for log in self.repository.logs))

    def test_case_whitespace_variants_are_excluded_but_primary_errors_are_kept(self):
        self.assertTrue(is_context_only_error("  SERVICE  entering READ-ONLY mode  "))
        self.assertTrue(is_context_only_error("unable to write APPLICATION data"))
        self.assertFalse(is_context_only_error("No space left on device. Unable to write application data.", True))
        self.assertFalse(is_context_only_error("ORA-28040: No matching authentication protocol", True))

    def test_new_unmapped_synthetic_followup_is_stored_without_analysis(self):
        result = self.processor.process(self.log("Another synthetic follow-up state", True))
        self.assertEqual(result["status"], "ignored")
        self.assertFalse(self.repository.incidents)
        self.generator.generate.assert_not_called()
        self.assertEqual(self.repository.logs[0]["message"], "Another synthetic follow-up state")

    def test_unrelated_real_unknown_error_retains_resource_analysis(self):
        with patch.object(self.processor, "_resource_fallback", return_value={"status": "resource_guidance"}) as fallback:
            result = self.processor.process(self.log("Unexpected database checksum mismatch"))
        self.assertEqual(result["status"], "resource_guidance")
        fallback.assert_called_once()
        self.assertEqual(len(self.repository.incidents), 1)
        self.assertEqual(next(iter(self.repository.incidents.values()))["error_code"], "UNKNOWN_ERROR")

    def test_existing_context_incidents_disappear_without_deleting_stored_data(self):
        documents = [
            {"incident_id": "write", "error_code": "UNKNOWN_ERROR", "representative_message": "Unable to write application data."},
            {"incident_id": "readonly", "error_code": "UNKNOWN_ERROR", "latest_message": "Service entering read-only mode."},
            {"incident_id": "future", "error_code": "UNKNOWN_ERROR", "synthetic": True, "representative_message": "future follow-up"},
            {"incident_id": "primary", "error_code": "DISK_FULL", "representative_message": "No space left on device.", "synthetic": True},
            {"incident_id": "actual", "error_code": "UNKNOWN_ERROR", "representative_message": "Unexpected database checksum mismatch"},
            {"incident_id": "legacy-primary", "error_code": "UNKNOWN_ERROR", "representative_message": "OutOfMemoryError", "synthetic": True},
        ]
        before = copy.deepcopy(documents)
        app = Flask(__name__)
        app.register_blueprint(log_generator_blueprint)
        with patch("routes.log_generator_routes.repository") as repository:
            repository.list_operational_incidents.return_value = documents
            response = app.test_client().get("/api/v1/log-generator/incidents")
            repository.update_operational_incident.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["incident_id"] for item in response.get_json()["incidents"]], ["primary", "actual", "legacy-primary"])
        self.assertEqual(documents, before)

    def test_api_queue_worker_stores_followups_without_retry_or_extra_incident(self):
        from operations.queue import AnalysisQueue, GROUP, STREAM
        from operations.worker import handle
        from routes.log_routes import log_blueprint

        redis = fakeredis.FakeRedis(decode_responses=True)
        queue = AnalysisQueue(redis)
        queue.ensure_group()
        app = Flask(__name__)
        app.register_blueprint(log_blueprint)
        messages = ["No space left on device.", "Unable to write application data.", "Service entering read-only mode."]
        with patch("routes.log_routes.client", return_value=redis):
            response = app.test_client().post("/api/v1/logs", json=[self.log(message, True) for message in messages])
        self.assertEqual(response.status_code, 202)
        identifiers = response.get_json()["job_ids"]
        with patch("dependencies.log_processor", self.processor):
            for message_id, fields in redis.xreadgroup(GROUP, "test", {STREAM: ">"}, count=10)[0][1]:
                queue.process(message_id, fields, handle)
        receipts = [queue.get(identifier) for identifier in identifiers]
        self.assertTrue(all(receipt["status"] == "completed" for receipt in receipts))
        self.assertEqual([receipt["result"]["status"] for receipt in receipts], ["recommended", "ignored", "ignored"])
        self.assertEqual(len(self.repository.incidents), 1)
        self.assertEqual(len(self.repository.recommendations), 1)
        self.assertEqual(len(self.repository.logs), 3)
        self.assertEqual(redis.xlen("jarvis:dead-letter"), 0)


if __name__ == "__main__":
    unittest.main()

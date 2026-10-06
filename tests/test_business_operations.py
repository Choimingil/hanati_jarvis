import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
import httpx
from operations.business import business_priority
from operations.business_probe import validate_probe, verify_business
from operations.deployment_check import inspect_container
from aiops.operational_incident_service import OperationalIncidentService
from log_processor import LogProcessor
from support import MemoryRepository


class BusinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / "policy.json"
        self.file.write_text(
            json.dumps(
                {
                    "services": [
                        {
                            "environment": "prod",
                            "service": "payments",
                            "criticality": "tier1",
                        }
                    ]
                }
            )
        )
        self.patch = patch.dict(os.environ, {"BUSINESS_SERVICES_FILE": str(self.file)})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_priority_uses_service_and_business_impact(self):
        self.assertEqual(
            business_priority({"environment": "prod", "service": "payments"})[
                "priority"
            ],
            "P2",
        )
        self.assertEqual(
            business_priority({"business_impact": {"failed_transactions": 100}})[
                "priority"
            ],
            "P1",
        )
        self.assertEqual(
            business_priority({"business_impact": {"failure_rate": float("nan")}})[
                "priority"
            ],
            "P3",
        )
        self.assertEqual(
            business_priority({"business_impact": {"affected_customers": True}})[
                "priority"
            ],
            "P3",
        )

    def test_downtime_evidence_cannot_be_cleared_by_later_log(self):
        before = business_priority({"business_impact": {"service_available": False}})
        after = business_priority(
            {"business_impact": {"service_available": True}}, previous=before
        )
        self.assertEqual(after["priority"], "P1")
        self.assertFalse(after["business_impact"]["service_available"])

    def test_repeated_error_reuses_analysis_and_keeps_approval_version(self):
        repo = MemoryRepository()
        repo.save_log = lambda doc: None
        repo.save_diagnosis = lambda doc: None

        def save(doc):
            rec = doc["recommendation"]
            repo.recommendations[rec["recommendation_id"]] = rec

        repo.save_recommendation = save
        generator = types.SimpleNamespace(
            generate=lambda **kw: {"runbooks": [{"script_id": "restart_application"}]}
        )
        search = types.SimpleNamespace(search=lambda **kw: [])
        processor = LogProcessor(
            repo, search, generator, incident_service=OperationalIncidentService(repo)
        )
        log = {
            "level": "ERROR",
            "message": "OutOfMemoryError 123",
            "host": "one",
            "service": "payments",
            "environment": "prod",
        }
        with patch.object(generator, "generate", wraps=generator.generate) as generate:
            first = processor.process(log, ingestion_id="job-one")
            second = processor.process(log, ingestion_id="job-two")
            self.assertEqual(generate.call_count, 1)
            self.assertEqual(second["status"], "aggregated")
        incident = list(repo.incidents.values())[0]
        self.assertEqual(incident["occurrence_count"], 2)
        self.assertEqual(
            first["recommendation"]["incident_version"], incident["version"]
        )
        third = processor.process(
            {**log, "business_impact": {"service_available": False}},
            ingestion_id="job-three",
        )
        self.assertEqual(third["status"], "recommended")
        self.assertEqual(list(repo.incidents.values())[0]["priority"], "P1")

    def test_new_host_and_resolved_incident_trigger_new_analysis(self):
        repo = MemoryRepository()
        service = OperationalIncidentService(repo)
        log = {
            "message": "OutOfMemoryError",
            "host": "one",
            "service": "payments",
            "environment": "prod",
        }
        first = service.start(log, "MEMORY_LEAK")
        _, incident = service.complete_analysis(first, {"runbooks": []})
        other = service.start({**log, "host": "two"}, "MEMORY_LEAK")
        self.assertFalse(other["analysis_suppressed"])
        repo.incidents[incident["incident_id"]]["status"] = "RESOLVED"
        reopened = service.start(log, "MEMORY_LEAK")
        self.assertEqual(reopened["status"], "REOPENED")
        self.assertFalse(reopened["analysis_suppressed"])

    def test_container_check_detects_missing_limits_and_oom(self):
        c = types.SimpleNamespace(
            name="test",
            reload=lambda: None,
            attrs={
                "State": {"Running": True},
                "HostConfig": {
                    "Memory": 128 * 1024**2,
                    "MemorySwap": 128 * 1024**2,
                    "NanoCpus": 100000000,
                },
            },
        )
        self.assertTrue(inspect_container(c, 128)["passed"])
        c.attrs["State"]["OOMKilled"] = True
        self.assertFalse(inspect_container(c, 128)["passed"])


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(UTC)
        self.policy = {
            "url": "https://payments.invalid/status",
            "allowed_hosts": ["payments.invalid"],
            "expected_service": "payments",
            "expected_environment": "prod",
            "criteria": {
                "success_rate_min": 0.99,
                "failure_rate_max": 0.01,
                "p95_latency_ms_max": 1000,
                "transactions_min": 10,
            },
        }
        self.data = {
            "service": "payments",
            "environment": "prod",
            "sampled_at": self.now.isoformat(),
            "window_started_at": (self.now - timedelta(seconds=10)).isoformat(),
            "success_rate": 0.999,
            "failure_rate": 0.001,
            "p95_latency_ms": 100,
            "transactions": 100,
        }

    def checks(self, data):
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=data)
            )
        ) as client:
            return verify_business(
                self.policy,
                (self.now - timedelta(seconds=20)).timestamp(),
                http=client,
                now=self.now,
            )

    def test_fresh_business_kpis_pass(self):
        self.assertTrue(all(c["passed"] for c in self.checks(self.data)))

    def test_stale_pre_action_low_traffic_and_wrong_service_fail(self):
        for changes in [
            {"sampled_at": (self.now - timedelta(minutes=5)).isoformat()},
            {"window_started_at": (self.now - timedelta(minutes=1)).isoformat()},
            {"transactions": 0},
            {"service": "other"},
            {"success_rate": 0.5},
            {"failure_rate": 0.4},
            {"p95_latency_ms": 5000},
            {"success_rate": "0.999"},
        ]:
            self.assertFalse(
                all(c["passed"] for c in self.checks({**self.data, **changes})), changes
            )

    def test_missing_config_non_allowlisted_url_and_redirect_block(self):
        self.assertFalse(all(c["passed"] for c in verify_business(None, 0)))
        with self.assertRaises(ValueError):
            validate_probe({**self.policy, "url": "https://foreign.invalid/status"})
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    302, headers={"location": "https://foreign.invalid"}
                )
            ),
            follow_redirects=False,
        ) as client:
            self.assertFalse(
                all(c["passed"] for c in verify_business(self.policy, 0, http=client))
            )

    def test_probe_uses_get_only(self):
        requests = []

        def handle(request):
            requests.append(request.method)
            return httpx.Response(200, json=self.data)

        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            verify_business(self.policy, 0, http=client, now=self.now)
        self.assertEqual(requests, ["GET"])


if __name__ == "__main__":
    unittest.main()

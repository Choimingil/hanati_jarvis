"""Phase-one safety contracts, using a fake Docker backend and an in-process agent."""

import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import fakeredis
from flask import Flask
import httpx

from execution_agent.app import create_app as create_agent
from execution_agent.runtime import AgentRuntime
from operations.execution import ExecutionCoordinator
from operations.queue import AnalysisQueue, STREAM, GROUP
from operations.privacy import redact
from operations.health import service_status
from aiops.recovery_verifier import RecoveryVerifier
from aiops.operational_incident_service import OperationalIncidentService
from support import MemoryRepository


TARGET = {
    "host": "payment-01",
    "environment": "prod",
    "service": "payment-api",
    "instance": "one",
}
TOKEN = "test-machine-credential-32-characters-only"


class FakeDockerBackend:
    def __init__(self, counter):
        self.counter = counter
        self.ready = True
        self.fail = False
        self.rollback_fail = False
        self.recovered = True

    def container(self, action):
        return None

    def prechecks(self, action):
        return [
            {"name": name, "passed": self.ready}
            for name in ("redundancy", "maintenance", "rollback_ready")
        ]

    def snapshot(self, action):
        return {
            "running": True,
            "paused": False,
            "container_id": "container-one",
            "image_id": "image-one",
        }

    def perform(self, action):
        if action["operation"] == "inspect":
            return {"status": "success", "state": {"output": "password=secret"}}
        self.counter.write_text(
            self.counter.read_text() + "x" if self.counter.exists() else "x"
        )
        return {"status": "failed" if self.fail else "success"}

    def rollback(self, action, before):
        return {"status": "failed" if self.rollback_fail else "success"}

    def verify(self, action, execution_started_at=None):
        return [{"name": "pipeline", "passed": self.recovered}]


class AgentTransport:
    def __init__(self, agent):
        self.agent = agent.test_client()
        self.lose_execute_response = False

    def request(self, method, url, json=None, headers=None):
        path = httpx.URL(url).path
        response = self.agent.open(path, method=method, json=json, headers=headers)
        if path == "/execute" and self.lose_execute_response:
            raise httpx.ReadTimeout("simulated response loss")
        return httpx.Response(
            response.status_code,
            json=response.get_json(),
            request=httpx.Request(method, url),
        )


class AgentAndCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.counter = Path(self.temp.name) / "commands.txt"
        self.backend = FakeDockerBackend(self.counter)
        self.manifest = {
            **TARGET,
            "recovery_interval_seconds": 1,
            "actions": {
                "restart_application": {
                    "enabled": True,
                    "kind": "remediation",
                    "operation": "restart",
                    "rollback": "restore_runtime_state",
                    "business_probe": "jarvis_pipeline",
                },
                "check_memory_usage": {
                    "enabled": True,
                    "kind": "diagnostic",
                    "operation": "inspect",
                },
            },
        }
        self.agent = create_agent(
            self.manifest,
            Path(self.temp.name) / "journal.sqlite",
            TOKEN,
            backend=self.backend,
        )
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self.transport = AgentTransport(self.agent)
        self.manager = ExecutionCoordinator(self.redis, self.transport)
        self.registry_patch = patch(
            "operations.execution.registry",
            return_value=[
                {
                    **TARGET,
                    "url": "http://127.0.0.1:8090",
                    "token_env": "TEST_AGENT_SECRET",
                }
            ],
        )
        self.registry_patch.start()
        self.addCleanup(self.registry_patch.stop)
        self.env_patch = patch.dict(os.environ, {"TEST_AGENT_SECRET": TOKEN})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.context = {
            "incident": {"incident_id": "INC-1"},
            "recommendation": {
                "recommendation_id": "REC-1",
                "incident_version": 2,
                "targets": [TARGET],
            },
            "script_id": "restart_application",
            "error_code": "MEMORY_LEAK",
        }
        self.body = {
            "incident_id": "INC-1",
            "recommendation_id": "REC-1",
            "incident_version": 2,
            "action_id": "ACTION-1",
            "approved_by": "operator",
            "target": TARGET,
        }

    def reserve(self):
        preview = self.manager.prepare(self.context, TARGET)
        self.body["preflight_id"] = preview["preflight_id"]
        proof = self.manager.validate_proof(self.body, self.context)
        record, new = self.manager.reserve("EXEC-1", self.body, self.context, proof)
        self.assertTrue(new)
        return record

    def test_preflight_binds_identity_and_version(self):
        preview = self.manager.prepare(self.context, TARGET)
        self.body["preflight_id"] = preview["preflight_id"]
        self.body["incident_version"] = 3
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.manager.validate_proof(self.body, self.context)
        self.assertFalse(self.counter.exists())

    def test_missing_or_expired_preflight_blocks_execution(self):
        with self.assertRaises(ValueError):
            self.manager.validate_proof(self.body, self.context)
        preview = self.manager.prepare(self.context, TARGET)
        self.body["preflight_id"] = preview["preflight_id"]
        self.redis.delete("jarvis:preflight:" + preview["preflight_id"])
        with self.assertRaises(ValueError):
            self.manager.validate_proof(self.body, self.context)

    def test_foreign_target_not_bound_to_recommendation(self):
        with self.assertRaisesRegex(ValueError, "not bound"):
            self.manager.prepare(self.context, {**TARGET, "environment": "dev"})

    def test_agent_machine_credential_required(self):
        response = self.agent.test_client().get("/identity")
        self.assertEqual(response.status_code, 401)
        with self.assertRaises(ValueError):
            create_agent(self.manifest, Path(self.temp.name) / "other.sqlite", "short")

    def test_agent_target_mismatch_blocks(self):
        response = self.agent.test_client().post(
            "/preflight",
            json={
                "target": {**TARGET, "host": "other"},
                "script_id": "restart_application",
                "kind": "remediation",
            },
            headers={"Authorization": "Bearer " + TOKEN},
        )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.counter.exists())

    def test_disabled_action_and_missing_rollback_checks_block(self):
        runtime = self.agent.extensions["runtime"]
        runtime.manifest["actions"]["restart_application"]["enabled"] = False
        with self.assertRaises(ValueError):
            runtime.preflight(
                {
                    "target": TARGET,
                    "script_id": "restart_application",
                    "kind": "remediation",
                }
            )
        runtime.manifest["actions"]["restart_application"]["enabled"] = True
        runtime.manifest["actions"]["restart_application"]["rollback"] = None
        with self.assertRaises(ValueError):
            runtime.preflight(
                {
                    "target": TARGET,
                    "script_id": "restart_application",
                    "kind": "remediation",
                }
            )

    def test_two_coordinators_cannot_reserve_same_host(self):
        record = self.reserve()
        manager = ExecutionCoordinator(self.redis, self.transport)
        context = {
            **self.context,
            "recommendation": {
                **self.context["recommendation"],
                "recommendation_id": "REC-2",
            },
        }
        body = {**self.body, "recommendation_id": "REC-2"}
        with self.assertRaisesRegex(ValueError, "waiting for business"):
            manager.prepare(context, TARGET)
        with self.assertRaisesRegex(ValueError, "reserved"):
            manager.reserve(
                "EXEC-2",
                body,
                context,
                {
                    "target": TARGET,
                    "policy_digest": record["agent_body"]["policy_digest"],
                },
            )

    def test_durable_agent_journal_deduplicates_after_restart(self):
        record = self.reserve()
        result = self.manager.dispatch(record)
        self.assertEqual(result["result"]["status"], "success")
        runtime = AgentRuntime(
            self.manifest, Path(self.temp.name) / "journal.sqlite", backend=self.backend
        )
        duplicate = runtime.execute(record["agent_body"])
        self.assertEqual(duplicate["status"], "success")
        self.assertEqual(self.counter.read_text(), "x")

    def test_response_loss_retains_lock_and_reconciles_without_rerun(self):
        record = self.reserve()
        self.transport.lose_execute_response = True
        record = self.manager.dispatch(record)
        self.assertEqual(record["result"]["status"], "unknown")
        self.manager.release_host(record)
        self.assertEqual(self.redis.get(record["locks"][1]), "EXEC-1")
        record = self.manager.reconcile(record)
        self.assertEqual(record["result"]["status"], "success")
        self.manager.release_host(record)
        self.assertEqual(self.redis.get(record["locks"][1]), "EXEC-1")
        record["recovery_verified"] = True
        self.manager.release_host(record)
        self.assertIsNone(self.redis.get(record["locks"][1]))
        self.assertEqual(self.redis.get(record["locks"][0]), "EXEC-1")
        self.assertEqual(self.counter.read_text(), "x")

    def test_recheck_failure_does_not_run_command(self):
        record = self.reserve()
        runtime = self.agent.extensions["runtime"]
        self.backend.ready = False
        result = runtime.execute(record["agent_body"])
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(self.counter.exists())

    def test_policy_digest_change_blocks_before_command(self):
        record = self.reserve()
        body = {**record["agent_body"], "policy_digest": "wrong"}
        with self.assertRaisesRegex(ValueError, "policy changed"):
            self.agent.extensions["runtime"].execute(body)
        self.assertFalse(self.counter.exists())

    def test_failure_runs_rollback_but_does_not_report_recovered(self):
        runtime = self.agent.extensions["runtime"]
        self.backend.fail = True
        record = self.reserve()
        result = self.manager.dispatch(record)["result"]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["rollback_result"]["status"], "success")
        with self.assertRaises(ValueError):
            runtime.verify(record["agent_body"])

    def test_failed_rollback_keeps_host_journal_locked(self):
        runtime = self.agent.extensions["runtime"]
        self.backend.fail = True
        self.backend.rollback_fail = True
        record = self.reserve()
        record = self.manager.dispatch(record)
        self.assertEqual(record["result"]["status"], "rollback_failed")
        self.manager.release_host(record)
        self.assertEqual(self.redis.get(record["locks"][1]), "EXEC-1")
        with self.assertRaises(ValueError):
            runtime.execute({**record["agent_body"], "execution_id": "EXEC-NEW"})

    def test_successful_command_requires_business_verification(self):
        record = self.manager.dispatch(self.reserve())
        with patch("execution_agent.runtime.time.sleep"):
            verified = self.manager.verify(record)
        self.assertTrue(verified["recovered"])
        self.assertEqual(len(verified["samples"]), 2)
        self.backend.recovered = False
        with patch("execution_agent.runtime.time.sleep"):
            verified = self.manager.verify(record)
        self.assertFalse(verified["recovered"])

    def test_command_output_is_redacted(self):
        result = self.manager.diagnose(TARGET, "check_memory_usage")
        self.assertNotIn("secret", result["state"]["output"])
        self.assertIn("[REDACTED]", result["state"]["output"])

    def test_remote_plain_http_is_rejected(self):
        with patch(
            "operations.execution.registry",
            return_value=[
                {
                    **TARGET,
                    "url": "http://10.0.0.1:8090",
                    "token_env": "TEST_AGENT_SECRET",
                }
            ],
        ):
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                self.manager.entry(TARGET)


class QueueAndPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self.queue = AnalysisQueue(self.redis)
        self.queue.ensure_group()

    def delivery(self):
        return self.redis.xreadgroup(GROUP, "test", {STREAM: ">"}, count=1)[0][1][0]

    def test_receipt_survives_queue_instance_restart_and_redacts(self):
        job_id = self.queue.enqueue(
            "logs", {"message": "password=secret", "token": "credential"}
        )
        raw = json.loads(self.redis.get("jarvis:job:" + job_id))
        self.assertNotIn("secret", json.dumps(raw))
        self.assertNotIn("credential", json.dumps(raw))
        self.assertEqual(AnalysisQueue(self.redis).get(job_id)["status"], "queued")
        self.assertNotIn("payload", self.queue.get(job_id))

    def test_worker_acknowledges_and_removes_delivery_after_success(self):
        job_id = self.queue.enqueue("logs", {"message": "hello", "level": "INFO"})
        message_id, fields = self.delivery()
        self.queue.process(message_id, fields, lambda *args: {"status": "stored"})
        self.assertEqual(self.queue.get(job_id)["status"], "completed")
        self.assertEqual(self.redis.xpending(STREAM, GROUP)["pending"], 0)
        self.assertEqual(self.redis.xlen(STREAM), 0)
        self.assertGreater(self.redis.ttl("jarvis:job:" + job_id), 0)

    def test_failed_analysis_retries_then_dead_letters(self):
        job_id = self.queue.enqueue("logs", {"message": "hello"})
        message_id, fields = self.delivery()

        def failed(*args):
            raise RuntimeError("password=do-not-save")

        for attempt in range(3):
            self.queue.process(message_id, fields, failed)
        self.assertEqual(self.queue.get(job_id)["attempts"], 3)
        self.assertEqual(self.queue.get(job_id)["status"], "failed")
        self.assertNotIn("do-not-save", str(self.queue.get(job_id)))
        self.assertEqual(self.redis.xlen("jarvis:dead-letter"), 1)
        self.assertEqual(self.redis.xpending(STREAM, GROUP)["pending"], 0)

    def test_redelivery_of_completed_job_does_not_run_handler(self):
        self.queue.enqueue("logs", {"message": "hello"})
        message_id, fields = self.delivery()
        called = []
        self.queue.process(message_id, fields, lambda *args: called.append(1))
        self.queue.process(message_id, fields, lambda *args: called.append(1))
        self.assertEqual(called, [1])

    def test_batch_receipts_and_stream_entries_are_atomic(self):
        ids = self.queue.enqueue_many(
            "logs", [{"message": "first"}, {"message": "second"}]
        )
        self.assertEqual(len(ids), 2)
        self.assertEqual(self.redis.xlen(STREAM), 2)
        self.assertTrue(all(self.queue.get(i)["status"] == "queued" for i in ids))

    def test_nested_and_text_personal_data_are_masked(self):
        text = 'password=abc token=def "api_key": "ghi" 900101-1234567 4111-1111-1111-1111 person@example.com 010-1234-5678'
        masked = redact(
            {"authorization": "Bearer very-secret", "nested": {"message": text}}
        )
        output = json.dumps(masked)
        for value in [
            "abc",
            "def",
            "ghi",
            "900101",
            "4111",
            "person@example",
            "1234",
            "very-secret",
        ]:
            self.assertNotIn(value, output)

    def test_unknown_code_or_missing_metrics_never_mark_recovered(self):
        verifier = RecoveryVerifier()
        self.assertFalse(verifier.verify({"error_code": "UNKNOWN"}, [])["recovered"])
        self.assertFalse(
            verifier.verify(
                {"error_code": "UNKNOWN"}, [{"timestamp": "2026-10-01T00:00:00Z"}]
            )["recovered"]
        )

    def test_redis_down_returns_failure_instead_of_successful_receipt(self):
        from routes.log_routes import log_blueprint

        app = Flask(__name__)
        app.register_blueprint(log_blueprint)
        with patch("routes.log_routes.client", side_effect=ConnectionError):
            response = app.test_client().post(
                "/api/v1/logs", json={"level": "ERROR", "message": "failure"}
            )
        self.assertEqual(response.status_code, 503)

    def test_collection_health_reports_stale_host_and_missing_worker(self):
        old = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        self.redis.hset(
            "jarvis:metric-hosts",
            "payment-01",
            json.dumps({"timestamp": old, "connections_access_denied": True}),
        )
        es = types.SimpleNamespace(
            options=lambda **kwargs: types.SimpleNamespace(ping=lambda: True)
        )
        with (
            patch("operations.health.client", return_value=self.redis),
            patch("operations.health.get_client", return_value=es),
            patch(
                "operations.health.httpx.get",
                return_value=types.SimpleNamespace(status_code=200),
            ),
            patch("operations.health.registry", return_value=[TARGET]),
        ):
            status = service_status()
        self.assertEqual(status["status"], "degraded")
        self.assertEqual(status["hosts"][0]["status"], "stale")
        self.assertTrue(status["hosts"][0]["connections_access_denied"])
        self.assertFalse(status["components"]["analysis_workers"]["healthy"])

    def test_duplicate_ingestion_does_not_inflate_incident_count(self):
        repo = MemoryRepository()
        service = OperationalIncidentService(repo)
        log = {
            "host": "payment-01",
            "environment": "prod",
            "service": "payment-api",
            "message": "OutOfMemoryError",
        }
        first = service.start(log, "MEMORY_LEAK", ingestion_id="job-1")
        duplicate = service.start(log, "MEMORY_LEAK", ingestion_id="job-1")
        self.assertEqual(first["version"], duplicate["version"])
        self.assertEqual(duplicate["occurrence_count"], 1)


if __name__ == "__main__":
    unittest.main()


class RemediationApiTests(unittest.TestCase):
    reserve = AgentAndCoordinatorTests.reserve

    def setUp(self):
        AgentAndCoordinatorTests.setUp(self)
        from routes import remediation_routes as routes

        self.routes = routes
        self.repo = MemoryRepository()
        self.repo.incidents["INC-1"] = {
            "incident_id": "INC-1",
            "version": 2,
            "status": "ACTION_REQUIRED",
            "error_code": "MEMORY_LEAK",
            "latest_recommendation_id": "REC-1",
        }
        self.repo.recommendations["REC-1"] = {
            "incident_id": "INC-1",
            "recommendation_id": "REC-1",
            "incident_version": 2,
            "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            "actions": [{"action_id": "ACTION-1", "script_id": "restart_application"}],
            "targets": [TARGET],
        }
        for name, value in [
            ("repository", self.repo),
            ("operational_incident_service", OperationalIncidentService(self.repo)),
            ("coordinator", lambda: self.manager),
        ]:
            mock = patch.object(routes, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        app = Flask(__name__)
        app.register_blueprint(routes.remediation_blueprint)
        self.api = app.test_client()

    def preview(self):
        response = self.api.post("/api/v1/remediations/preflight", json=self.body)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.body["preflight_id"] = response.get_json()["preflight_id"]

    def test_approval_then_business_verification_closes_incident(self):
        self.preview()
        approved = self.api.post("/api/v1/remediations/approve", json=self.body)
        self.assertEqual(approved.status_code, 200, approved.get_json())
        identifier = approved.get_json()["execution_id"]
        self.assertEqual(self.repo.incidents["INC-1"]["status"], "MONITORING")
        duplicate = self.api.post("/api/v1/remediations/approve", json=self.body)
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.get_json()["duplicate"])
        self.assertEqual(self.counter.read_text(), "x")
        with patch("execution_agent.runtime.time.sleep"):
            response = self.api.post(
                "/api/v1/remediations/verify", json={"execution_id": identifier}
            )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()["recovered"])
        self.assertEqual(self.repo.incidents["INC-1"]["status"], "RESOLVED")
        self.assertIsNone(self.redis.get(self.manager.get(identifier)["locks"][1]))

    def test_stale_recommendation_blocks_without_execution(self):
        self.preview()
        self.repo.incidents["INC-1"]["version"] = 3
        response = self.api.post("/api/v1/remediations/approve", json=self.body)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.counter.exists())

    def test_missing_preflight_never_reserves_host(self):
        response = self.api.post("/api/v1/remediations/approve", json=self.body)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(list(self.redis.scan_iter("jarvis:host:*")))

    def test_rejection_blocks_same_action_even_with_existing_preflight(self):
        self.preview()
        response = self.api.post("/api/v1/remediations/reject", json=self.body)
        self.assertEqual(response.status_code, 200)
        response = self.api.post("/api/v1/remediations/approve", json=self.body)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.counter.exists())

    def test_persistence_failure_retains_reservation_and_recovers_on_poll(self):
        self.preview()
        with patch.object(
            self.repo, "save_remediation_execution", side_effect=ConnectionError
        ):
            response = self.api.post("/api/v1/remediations/approve", json=self.body)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.counter.read_text(), "x")
        identifier = list(self.redis.scan_iter("jarvis:execution:*"))[0].split(":")[-1]
        response = self.api.get("/api/v1/remediations/executions/" + identifier)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIn(identifier, self.repo.executions)
        self.assertEqual(self.counter.read_text(), "x")

    def test_invalid_action_version_or_body_is_rejected(self):
        for body in [
            None,
            {**self.body, "incident_version": "2"},
            {**self.body, "action_id": "UNKNOWN"},
        ]:
            response = self.api.post("/api/v1/remediations/approve", json=body)
            self.assertEqual(response.status_code, 409)
        self.assertFalse(self.counter.exists())


class OutboundPrivacyTests(unittest.TestCase):
    def test_external_llm_is_disableable_and_prompt_is_redacted(self):
        from llm_agent.services.llm_service import LLMService

        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(
                choices=[
                    types.SimpleNamespace(
                        message=types.SimpleNamespace(content="result")
                    )
                ]
            )

        service = LLMService(
            client=types.SimpleNamespace(
                chat=types.SimpleNamespace(
                    completions=types.SimpleNamespace(create=create)
                )
            )
        )
        with patch.dict(os.environ, {"LLM_EXTERNAL_ENABLED": "false"}):
            service.generate_text("password=secret")
        self.assertEqual(calls, [])
        with patch.dict(os.environ, {"LLM_EXTERNAL_ENABLED": "true"}):
            service.generate_text('password=secret "token":"credential"')
        sent = calls[0]["messages"][0]["content"]
        self.assertNotIn("secret", sent)
        self.assertNotIn("credential", sent)
        self.assertIn("비신뢰 데이터", sent)

    def test_elasticsearch_write_redacts_raw_fields(self):
        from adapters.elastic_adapters import ElasticLogRepository

        writes = []
        repo = ElasticLogRepository.__new__(ElasticLogRepository)
        repo.client = types.SimpleNamespace(
            index=lambda **kwargs: writes.append(kwargs)
        )
        repo.save_log(
            {
                "ingestion_id": "job-1",
                "raw": {"password": "secret"},
                "message": "token=credential",
            }
        )
        self.assertEqual(writes[0]["id"], "job-1")
        self.assertNotIn("secret", json.dumps(writes))
        self.assertNotIn("credential", json.dumps(writes))

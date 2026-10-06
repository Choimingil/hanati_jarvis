"""Container contracts without a daemon; local Qdrant is real, Redis/ES are doubles."""

import json
import sys
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import fakeredis
from flask import Flask
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from adapters.elastic_adapters import ElasticLogRepository
from adapters.qdrant_adapters import QdrantCaseSearcher
from aiops.incident_indexer import QdrantIncidentIndexer
from log_processor import LogProcessor
from operations.queue import AnalysisQueue, STREAM, METRIC_STREAM, GROUP
from operations.worker import handle
from routes.log_routes import log_blueprint
from routes.metrics_routes import metrics_blueprint
from routes.operations_routes import operations_blueprint
from collector.system_collector import SystemCollector
import yaml


class PipelineContractTests(unittest.TestCase):
    def setUp(self):
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self.queue = AnalysisQueue(self.redis)
        self.queue.ensure_group()
        self.repo = ElasticLogRepository.__new__(ElasticLogRepository)
        self.repo.client = Mock()
        self.processor = LogProcessor(self.repo, Mock(), Mock())
        app = Flask(__name__)
        app.register_blueprint(log_blueprint)
        app.register_blueprint(metrics_blueprint)
        app.register_blueprint(operations_blueprint)
        self.api = app.test_client()

    def drain(self, stream):
        import dependencies

        with (
            patch.object(dependencies, "log_processor", self.processor),
            patch.object(dependencies, "repository", self.repo),
            patch.object(dependencies, "metric_analysis_service") as analysis,
        ):
            analysis.analyze.return_value = []
            while True:
                batches = self.redis.xreadgroup(
                    GROUP, "contracts", {stream: ">"}, count=1
                )
                if not batches:
                    break
                for mid, fields in batches[0][1]:
                    self.queue.process(mid, fields, handle, stream=stream)

    def test_fluent_json_batch_to_api_queue_worker_and_storage_adapter(self):
        with patch.object(
            sys, "path", [str(Path("log_generator").resolve()), *sys.path]
        ):
            from logger.json_formatter import JsonFormatter

        system = types.SimpleNamespace(
            hostname="validation-host", application="validation-service"
        )
        raw = json.loads(
            JsonFormatter().format(
                "INFO", "password=secret integration contract", system
            )
        )
        raw.setdefault("application", "order-service")
        raw.setdefault("environment", "production")
        with patch("routes.log_routes.client", return_value=self.redis):
            response = self.api.post("/api/v1/logs", json=[raw, raw])
        self.assertEqual(response.status_code, 202)
        ids = response.get_json()["job_ids"]
        self.drain(STREAM)
        with patch("routes.operations_routes.client", return_value=self.redis):
            for identifier in ids:
                self.assertEqual(
                    self.api.get("/api/v1/analysis/jobs/" + identifier).get_json()[
                        "status"
                    ],
                    "completed",
                )
        writes = self.repo.client.index.call_args_list
        self.assertEqual(len(writes), 2)
        self.assertEqual({w.kwargs["id"] for w in writes}, set(ids))
        for write in writes:
            self.assertEqual(write.kwargs["index"], "application-logs")
            self.assertEqual(write.kwargs["document"]["host"], "validation-host")
            self.assertNotIn("secret", json.dumps(write.kwargs["document"]))

    def test_actual_collector_snapshot_to_metric_worker_and_adapter(self):
        payload = SystemCollector(2).collect()
        with patch("routes.metrics_routes.client", return_value=self.redis):
            response = self.api.post("/api/v1/metrics", json=payload)
        self.assertEqual(response.status_code, 202, response.get_json())
        identifier = response.get_json()["job_id"]
        self.drain(METRIC_STREAM)
        self.assertEqual(self.queue.get(identifier)["status"], "completed")
        write = self.repo.client.index.call_args.kwargs
        self.assertEqual(write["index"], "application-system-metrics")
        self.assertEqual(write["id"], identifier)

    def test_redis_outage_does_not_report_accepted(self):
        with patch("routes.log_routes.client", side_effect=ConnectionError):
            response = self.api.post(
                "/api/v1/logs", json={"level": "INFO", "message": "check"}
            )
        self.assertEqual(response.status_code, 503)


class LocalQdrantContracts(unittest.TestCase):
    def test_real_local_store_adapter_filter_redaction_and_reopen(self):
        vector = [1.0] + [0.0] * 383
        with tempfile.TemporaryDirectory() as path:
            client = QdrantClient(path=path)
            client.create_collection(
                "incident_cases",
                vectors_config=VectorParams(size=384, distance=Distance.COSINE),
            )
            incident = {
                "incident_id": "12345678-1234-4234-8234-123456789abc",
                "error_code": "MEMORY_LEAK",
                "summary": "local contract",
                "root_cause": "password=secret",
            }
            with (
                patch("aiops.incident_indexer.get_client", return_value=client),
                patch("aiops.incident_indexer.encode", return_value=vector),
            ):
                QdrantIncidentIndexer().index(incident)
            with (
                patch("adapters.qdrant_adapters.get_client", return_value=client),
                patch("adapters.qdrant_adapters.encode", return_value=vector),
            ):
                self.assertEqual(
                    len(QdrantCaseSearcher().search("MEMORY_LEAK", "test")), 1
                )
                self.assertEqual(QdrantCaseSearcher().search("DISK_FULL", "test"), [])
                self.assertNotIn(
                    "secret",
                    json.dumps(QdrantCaseSearcher().search("MEMORY_LEAK", "test")),
                )
            client.close()
            client = QdrantClient(path=path)
            self.assertEqual(client.get_collection("incident_cases").points_count, 1)
            client.close()


class ComposeContracts(unittest.TestCase):
    def test_shared_log_and_service_routes(self):
        compose = yaml.safe_load(Path("docker-compose.yml").read_text())
        services = compose["services"]
        self.assertIn("log-volume:/workspace/fluentbit", services["aiops"]["volumes"])
        self.assertIn(
            "log-volume:/workspace/fluentbit", services["log-generator"]["volumes"]
        )
        self.assertIn("log-volume:/var/log/app", services["fluent-bit"]["volumes"])
        conf = Path("fluentbit/fluent-bit.conf").read_text()
        self.assertIn("Host              aiops", conf)
        self.assertIn("URI               /api/v1/logs", conf)
        self.assertIn("Format            json", conf)
        for service in services.values():
            build = service.get("build")
            if build:
                self.assertTrue(Path(build["dockerfile"]).is_file())
        self.assertNotIn("llm-agent", services)

    def test_api_and_worker_wait_for_initial_log_mapping(self):
        services = yaml.safe_load(Path("docker-compose.yml").read_text())["services"]
        for name in ["aiops", "analysis-worker"]:
            self.assertEqual(
                services[name]["depends_on"].get("elastic-init"),
                {"condition": "service_completed_successfully"},
            )


if __name__ == "__main__":
    unittest.main()


class ElasticTransportContract(unittest.TestCase):
    def test_real_client_http_serialization_to_stub_server(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        from elasticsearch import Elasticsearch

        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_PUT(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append((self.path, body))
                result = json.dumps(
                    {
                        "_index": "application-logs",
                        "_id": "job-http",
                        "_version": 1,
                        "result": "created",
                        "_shards": {"total": 1, "successful": 1, "failed": 0},
                        "_seq_no": 0,
                        "_primary_term": 1,
                    }
                ).encode()
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.send_header("X-Elastic-Product", "Elasticsearch")
                self.send_header("Content-Length", str(len(result)))
                self.end_headers()
                self.wfile.write(result)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = Elasticsearch(
            "http://127.0.0.1:" + str(server.server_port),
            request_timeout=2,
            max_retries=0,
        )
        try:
            repo = ElasticLogRepository.__new__(ElasticLogRepository)
            repo.client = client
            repo.save_log(
                {"ingestion_id": "job-http", "message": "password=secret contract"}
            )
            self.assertTrue(
                received[0][0].startswith("/application-logs/_doc/job-http")
            )
            self.assertNotIn("secret", json.dumps(received[0][1]))
        finally:
            client.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

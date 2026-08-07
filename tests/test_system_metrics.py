import sys
import types
import unittest

from flask import Flask

from collector.system_collector import SystemCollector


class _Repository:
    def __init__(self) -> None:
        self.documents = []

    def save_metric(self, document):
        self.documents.append(document)


class SystemCollectorTest(unittest.TestCase):
    def test_snapshot_has_required_sections_and_process_limit(self):
        snapshot = SystemCollector(process_limit=2).collect()

        for field in (
            "timestamp", "host", "cpu", "memory", "disk", "network",
        ):
            self.assertIn(field, snapshot)
        self.assertLessEqual(snapshot["processes"]["returned"], 2)
        self.assertIn("connections", snapshot["network"])


class MetricsRouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = _Repository()
        dependencies = types.ModuleType("dependencies")
        dependencies.repository = cls.repository
        sys.modules["dependencies"] = dependencies

        from routes.metrics_routes import metrics_blueprint

        app = Flask(__name__)
        app.register_blueprint(metrics_blueprint)
        cls.client = app.test_client()

    def test_rejects_incomplete_snapshot(self):
        response = self.client.post(
            "/api/v1/metrics", json={"timestamp": "now"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("cpu", response.get_json()["missing"])

    def test_stores_complete_snapshot(self):
        snapshot = SystemCollector(process_limit=1).collect()
        response = self.client.post("/api/v1/metrics", json=snapshot)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["status"], "stored")
        self.assertEqual(self.repository.documents[-1]["host"], snapshot["host"])


if __name__ == "__main__":
    unittest.main()

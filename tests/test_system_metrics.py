import unittest
from unittest.mock import patch
import fakeredis
from flask import Flask
from collector.system_collector import SystemCollector
from operations.queue import AnalysisQueue
from routes.metrics_routes import metrics_blueprint

class SystemCollectorTest(unittest.TestCase):
    def test_snapshot_has_required_sections_and_process_limit(self):
        snapshot=SystemCollector(process_limit=2).collect()
        for field in ("timestamp","host","cpu","memory","disk","network"):
            self.assertIn(field,snapshot)
        self.assertLessEqual(snapshot["processes"]["returned"],2)
        self.assertIn("connections",snapshot["network"])

class MetricsRouteTest(unittest.TestCase):
    def setUp(self):
        app=Flask(__name__);app.register_blueprint(metrics_blueprint)
        self.client=app.test_client();self.redis=fakeredis.FakeRedis(decode_responses=True)
    def test_rejects_incomplete_snapshot(self):
        response=self.client.post("/api/v1/metrics",json={"timestamp":"now"})
        self.assertEqual(response.status_code,400)
        self.assertIn("cpu",response.get_json()["missing"])
    def test_enqueues_complete_snapshot_without_inline_analysis(self):
        snapshot=SystemCollector(process_limit=1).collect()
        with patch("routes.metrics_routes.client",return_value=self.redis):
            response=self.client.post("/api/v1/metrics",json=snapshot)
        self.assertEqual(response.status_code,202)
        body=response.get_json();self.assertEqual(body["status"],"accepted")
        job=AnalysisQueue(self.redis).get(body["job_id"])
        self.assertEqual(job["status"],"queued")
    def test_future_timestamp_is_rejected(self):
        snapshot=SystemCollector(process_limit=1).collect();snapshot["timestamp"]="2099-01-01T00:00:00Z"
        response=self.client.post("/api/v1/metrics",json=snapshot)
        self.assertEqual(response.status_code,400)

if __name__=="__main__": unittest.main()

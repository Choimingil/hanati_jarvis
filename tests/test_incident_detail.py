import unittest
from unittest.mock import Mock, patch

from flask import Flask

from adapters.elastic_adapters import ElasticLogRepository
from routes.log_generator_routes import log_generator_blueprint


class IncidentDetailTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(log_generator_blueprint)
        self.client = app.test_client()
        self.incident = {
            "incident_id": "INC-DETAIL", "service": "payments",
            "environment": "prod", "affected_hosts": ["payments-01"],
            "status": "ANALYZING", "representative_message": "password=secret timeout",
        }

    def test_default_list_window_is_ten_minutes(self):
        with patch("routes.log_generator_routes.repository") as repository:
            repository.list_operational_incidents.return_value = []
            response = self.client.get("/api/v1/log-generator/incidents")
            self.assertEqual(response.status_code, 200)
            repository.list_operational_incidents.assert_called_once_with(10)

    def test_detail_includes_system_and_logs_before_recommendation_exists(self):
        logs = [{"host": "payments-01", "message": "token=secret failed"}]
        with patch("routes.log_generator_routes.repository") as repository:
            repository.get_operational_incident.return_value = self.incident
            repository.recent_incident_logs.return_value = logs
            response = self.client.get("/api/v1/log-generator/incidents/INC-DETAIL")
            repository.get_operational_incident.assert_called_once_with("INC-DETAIL")
            repository.recent_incident_logs.assert_called_once_with("INC-DETAIL", minutes=10)
        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["incident"]["service"], "payments")
        self.assertEqual(data["logs"][0]["host"], "payments-01")
        self.assertEqual(data["logs_status"], "ready")
        self.assertNotIn("secret", response.get_data(as_text=True))

    def test_log_outage_keeps_incident_details_and_reports_partial_failure(self):
        with patch("routes.log_generator_routes.repository") as repository:
            repository.get_operational_incident.return_value = self.incident
            repository.recent_incident_logs.side_effect = ConnectionError
            response = self.client.get("/api/v1/log-generator/incidents/INC-DETAIL")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["logs_status"], "unavailable")
        self.assertEqual(response.get_json()["incident"]["service"], "payments")

    def test_missing_incident_and_storage_outage_are_distinct(self):
        with patch("routes.log_generator_routes.repository") as repository:
            repository.get_operational_incident.return_value = None
            self.assertEqual(self.client.get("/api/v1/log-generator/incidents/missing").status_code, 404)
            repository.recent_incident_logs.assert_not_called()
            repository.get_operational_incident.side_effect = ConnectionError
            self.assertEqual(self.client.get("/api/v1/log-generator/incidents/missing").status_code, 503)

    def test_related_logs_are_scoped_to_incident_and_recent_ingestion(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import json
        import threading
        from elasticsearch import Elasticsearch

        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                body = json.dumps({"hits": {"hits": [{"_source": {"message": "selected incident"}}]}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("X-Elastic-Product", "Elasticsearch")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = Elasticsearch(f"http://127.0.0.1:{server.server_port}")
        repository = ElasticLogRepository.__new__(ElasticLogRepository)
        repository.client = client
        try:
            self.assertEqual(repository.recent_incident_logs("INC-DETAIL")[0]["message"], "selected incident")
            filters = requests[0]["query"]["bool"]["filter"]
            self.assertEqual(filters[1]["range"]["received_at"]["gte"], "now-10m")
            self.assertEqual(filters[0]["bool"]["minimum_should_match"], 1)
            self.assertEqual(
                filters[0]["bool"]["should"],
                [{"term": {"incident_id": "INC-DETAIL"}}, {"term": {"incident_id.keyword": "INC-DETAIL"}}],
            )
            self.assertEqual(requests[0]["size"], 20)
            self.assertNotIn("raw", requests[0]["_source"])
        finally:
            client.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()

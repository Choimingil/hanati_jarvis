import unittest
from unittest.mock import patch

from flask import Flask

from routes.log_generator_routes import _es_since, log_generator_blueprint
from routes.web_routes import web_blueprint


class _ElasticClient:
    def __init__(self):
        self.last_search = None

    def search(self, **kwargs):
        self.last_search = kwargs
        return {
            "hits": {"hits": [{"_source": {
                "timestamp": "2026-08-07T12:00:01+09:00",
                "source": "resource_fallback",
                "guidance": {
                    "status": "resource_guidance",
                    "original_error_code": "MEMORY_LEAK",
                    "primary_problem_code": "MEMORY_LEAK_SUSPECTED",
                },
            }}]}
        }


class GuidanceWebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = Flask(__name__)
        app.register_blueprint(web_blueprint)
        app.register_blueprint(log_generator_blueprint)
        cls.client = app.test_client()

    def test_page_contains_guidance_and_feedback_panels(self):
        response = self.client.get("/")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="guidance-result"', html)
        self.assertIn('data-verdict="confirmed"', html)
        self.assertIn('id="feedback-root-cause"', html)
        self.assertIn("renderResourceGuidance", html)
        self.assertIn("for (let i = 0; i < 80; i++)", html)

    def test_polling_endpoint_returns_resource_guidance(self):
        with patch(
            "routes.log_generator_routes.get_client",
            return_value=_ElasticClient(),
        ):
            response = self.client.get(
                "/api/v1/log-generator/latest-recommendation"
                "?error_code=MEMORY_LEAK"
                "&since=2026-08-07T12:00:00%2B09:00"
            )

        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["status"], "ready")
        self.assertEqual(
            data["recommendation"]["status"], "resource_guidance"
        )

    def test_es_since_allows_unmapped_date_sort(self):
        client = _ElasticClient()
        with patch(
            "routes.log_generator_routes.get_client",
            return_value=client,
        ):
            _es_since("application-logs", "received_at", None)

        self.assertEqual(
            client.last_search["sort"],
            [{"received_at": {
                "order": "desc",
                "unmapped_type": "date",
            }}],
        )

if __name__ == "__main__":
    unittest.main()

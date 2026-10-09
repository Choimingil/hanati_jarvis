import json
import time
import unittest
from unittest.mock import patch

import fakeredis
from flask import Flask

from routes.log_generator_routes import (
    LATEST_RUN_KEY,
    LATEST_RUN_TTL,
    _finish_run,
    log_generator_blueprint,
)


def api_client():
    app = Flask(__name__)
    app.register_blueprint(log_generator_blueprint)
    return app.test_client()


class ScenarioSyncTest(unittest.TestCase):
    def setUp(self):
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self.client = api_client()
        self.redis_patch = patch(
            "routes.log_generator_routes.redis_client", return_value=self.redis
        )
        self.redis_patch.start()
        self.addCleanup(self.redis_patch.stop)

    def latest(self, client=None):
        return (client or self.client).get(
            "/api/v1/log-generator/latest-run"
        )

    def trigger(self):
        return self.client.post(
            "/api/v1/log-generator/run", json={"scenario": "disk_full"}
        )

    def test_publish_before_generation_and_read_from_another_api_instance(self):
        other_client = api_client()
        started_runs = []

        def generate(_key):
            response = self.latest(other_client)
            self.assertEqual(response.status_code, 200)
            started_runs.append(response.get_json()["run"])
            self.assertEqual(started_runs[0]["phase"], "running")
            self.assertEqual(started_runs[0]["error_code"], "DISK_FULL")
            return {"error_code": "DISK_FULL", "events": []}

        with patch("routes.log_generator_routes.run_scenario", side_effect=generate):
            response = self.trigger()
        self.assertEqual(response.status_code, 200)
        latest = self.latest(other_client).get_json()["run"]
        self.assertEqual(latest["run_id"], response.get_json()["run_id"])
        self.assertEqual(latest["run_id"], started_runs[0]["run_id"])
        self.assertEqual(latest["phase"], "completed")
        self.assertGreater(self.redis.ttl(LATEST_RUN_KEY), LATEST_RUN_TTL - 2)

    def test_latest_run_expires_with_ten_minute_window(self):
        with patch("routes.log_generator_routes.run_scenario", return_value={
            "error_code": "DISK_FULL", "events": [],
        }):
            self.assertEqual(self.trigger().status_code, 200)
        self.assertEqual(self.latest().get_json()["status"], "ready")
        with patch("time.time", return_value=time.time() + LATEST_RUN_TTL + 1):
            self.assertEqual(self.latest().get_json(), {"status": "none"})

    def test_older_completion_cannot_replace_newer_run(self):
        older = {"run_id": "older", "phase": "running"}
        newer = {"run_id": "newer", "phase": "running"}
        self.redis.set(LATEST_RUN_KEY, json.dumps(newer), ex=LATEST_RUN_TTL)
        _finish_run(older, "completed")
        self.assertEqual(json.loads(self.redis.get(LATEST_RUN_KEY)), newer)
        _finish_run(newer, "completed")
        self.assertEqual(self.latest().get_json()["run"]["phase"], "completed")

    def test_generation_failure_is_shared(self):
        with patch("routes.log_generator_routes.run_scenario", side_effect=OSError):
            response = self.trigger()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["status"], "failed")
        self.assertEqual(self.latest(api_client()).get_json()["run"]["phase"], "failed")

    def test_unavailable_sync_does_not_generate_untracked_errors(self):
        with (
            patch.object(self.redis, "set", side_effect=ConnectionError),
            patch("routes.log_generator_routes.run_scenario") as generate,
        ):
            response = self.trigger()
        self.assertEqual(response.status_code, 503)
        generate.assert_not_called()
        self.assertEqual(self.latest().get_json(), {"status": "none"})

    def test_unavailable_latest_run_does_not_look_like_no_run(self):
        with patch.object(self.redis, "get", side_effect=ConnectionError):
            response = self.latest()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["status"], "unavailable")

    def test_invalid_scenario_does_not_change_shared_state(self):
        self.redis.set(LATEST_RUN_KEY, json.dumps({"run_id": "existing"}))
        with patch("routes.log_generator_routes.run_scenario") as generate:
            response = self.client.post(
                "/api/v1/log-generator/run", json={"scenario": "unknown"}
            )
        self.assertEqual(response.status_code, 400)
        generate.assert_not_called()
        self.assertEqual(self.latest().get_json()["run"]["run_id"], "existing")


if __name__ == "__main__":
    unittest.main()

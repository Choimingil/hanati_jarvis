import json
import time
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import fakeredis
from flask import Flask

from operations.activity import (
    ACTIVITY_KEYS, recent_events, record, record_many, redis_activity, worker_activity,
)
from operations.queue import AnalysisQueue, GROUP, STREAM
from routes.log_generator_routes import log_generator_blueprint


class PipelineActivityTests(unittest.TestCase):
    def setUp(self):
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self.queue = AnalysisQueue(self.redis)
        self.queue.ensure_group()

    def deliver(self):
        return self.redis.xreadgroup(GROUP, "test-worker", {STREAM: ">"}, count=1)[0][1][0]

    def test_job_lifecycle_is_visible_after_receipt_and_queue_removal(self):
        job_id = self.queue.enqueue("logs", {
            "message": "disk full password=secret", "host": "web01", "service": "order-api",
        })
        message_id, fields = self.deliver()
        self.queue.process(message_id, fields, lambda *args: {
            "status": "recommended", "incident_id": "INC-1",
        }, "test-worker")
        redis_lines = "\n".join(redis_activity(self.redis))
        worker_lines = "\n".join(worker_activity(self.redis))
        self.assertIn("[접수]", redis_lines)
        self.assertIn("[처리 확인·큐 제거]", redis_lines)
        self.assertIn("[분석 시작]", worker_lines)
        self.assertIn("[처리 완료]", worker_lines)
        self.assertIn("result_status=recommended", worker_lines)
        self.assertIn("incident_id=INC-1", worker_lines)
        self.assertIn(job_id, redis_lines)
        self.assertIn("host=web01 service=order-api", worker_lines)
        self.assertNotIn("secret", redis_lines + worker_lines)
        self.assertEqual(self.redis.xlen(STREAM), 0)
        self.assertEqual(self.queue.get(job_id)["status"], "completed")

    def test_retries_and_dead_letters_are_traceable_without_exception_secrets(self):
        job_id = self.queue.enqueue("logs", {"message": "disk full"})
        message_id, fields = self.deliver()
        for _ in range(3):
            job = json.loads(self.redis.get("jarvis:job:" + job_id))
            job["next_attempt_at"] = 0
            self.redis.set("jarvis:job:" + job_id, json.dumps(job))
            self.queue.process(message_id, fields, Mock(side_effect=RuntimeError("token=secret")))
        redis_lines = "\n".join(redis_activity(self.redis))
        worker_lines = "\n".join(worker_activity(self.redis))
        self.assertIn("[재시도 대기]", redis_lines)
        self.assertIn("[실패 보관]", redis_lines)
        self.assertIn("최종 실패 보관: 1건", redis_lines)
        self.assertIn("[최종 분석 실패]", worker_lines)
        self.assertIn("error=RuntimeError", worker_lines)
        self.assertNotIn("secret", worker_lines)

    def test_observability_write_failure_cannot_fail_accepted_or_completed_job(self):
        original_pipeline = self.redis.pipeline

        def pipeline(transaction=True):
            if not transaction:
                return Mock(xadd=Mock(side_effect=ConnectionError))
            return original_pipeline(transaction=transaction)

        with patch.object(self.redis, "pipeline", side_effect=pipeline):
            job_id = self.queue.enqueue("logs", {"message": "info"})
            message_id, fields = self.deliver()
            self.queue.process(message_id, fields, lambda *args: {"status": "stored"})
        self.assertEqual(self.queue.get(job_id)["status"], "completed")
        self.assertEqual(self.redis.xlen(STREAM), 0)

    def test_recent_events_apply_timezone_aware_since_and_preserve_order(self):
        old = datetime.now(UTC) - timedelta(minutes=10)
        self.redis.xadd(ACTIVITY_KEYS["worker"], {"document": json.dumps({
            "timestamp": old.isoformat(), "event": "started", "consumer": "old-worker",
        })}, id=str(int(old.timestamp() * 1000)) + "-0")
        record(self.redis, "worker", "processing", job_id="one")
        record(self.redis, "worker", "completed", job_id="two")
        since = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        lines = recent_events(self.redis, "worker", since)
        self.assertEqual(len(lines), 2)
        self.assertIn("job_id=one", lines[0])
        self.assertIn("job_id=two", lines[1])
        self.assertNotIn("old-worker", str(lines))
        with self.assertRaises(ValueError):
            recent_events(self.redis, "worker", "2026-10-10T01:00:00")

    def test_activity_is_bounded_and_expires_independently_of_receipts(self):
        with patch("operations.activity.MAX_EVENTS", 3):
            record_many(self.redis, "worker", [{"event": "started", "consumer": str(i)} for i in range(5)])
        self.assertEqual(self.redis.xlen(ACTIVITY_KEYS["worker"]), 3)
        self.assertGreater(self.redis.ttl(ACTIVITY_KEYS["worker"]), 3598)
        self.assertIn("consumer=2", recent_events(self.redis, "worker")[0])
        record(self.redis, "worker", "started", message={"token": "secret", "details": "x" * 2000})
        document = json.loads(self.redis.xrevrange(ACTIVITY_KEYS["worker"], count=1)[0][1]["document"])
        self.assertLessEqual(len(document["message"]), 400)
        self.assertNotIn("secret", document["message"])

    def test_missing_payload_has_a_queue_failure_event(self):
        job_id = self.queue.enqueue("logs", {"message": "hello"})
        message_id, fields = self.deliver()
        self.redis.delete("jarvis:job:" + job_id)
        self.queue.process(message_id, fields, Mock())
        self.assertIn("[작업 본문 누락]", "\n".join(redis_activity(self.redis)))
        self.assertEqual(self.redis.xlen("jarvis:dead-letter"), 1)

    def test_worker_liveness_disappears_after_heartbeat_expiry(self):
        self.redis.set("jarvis:worker:test-worker", str(time.time()), ex=30)
        self.assertIn("Worker: 1개", worker_activity(self.redis)[0])
        with patch("time.time", return_value=time.time() + 31):
            self.assertIn("Worker: 0개", worker_activity(self.redis)[0])

    def test_activity_endpoint_keeps_other_sources_when_worker_read_fails(self):
        app = Flask(__name__)
        app.register_blueprint(log_generator_blueprint)
        with (
            patch("routes.log_generator_routes.redis_client", return_value=self.redis),
            patch("routes.log_generator_routes._received_logs", return_value=["fluent log"]),
            patch("routes.log_generator_routes._stored_analysis", return_value=["analysis log"]),
            patch("routes.log_generator_routes._qdrant_status", return_value=["qdrant log"]),
            patch("routes.log_generator_routes.worker_activity", side_effect=ConnectionError("token=secret")),
        ):
            response = app.test_client().get("/api/v1/log-generator/activity")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["fluentbit_log"], ["fluent log"])
        self.assertEqual(data["elasticsearch_log"], ["analysis log"])
        self.assertIn("Redis PING 정상", data["redis_log"][0])
        self.assertIn("Worker 조회 실패", data["worker_log"][0])
        self.assertNotIn("secret", data["worker_log"][0])


if __name__ == "__main__":
    unittest.main()

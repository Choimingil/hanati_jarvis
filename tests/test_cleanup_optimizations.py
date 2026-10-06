import time
import types
import unittest
from unittest.mock import Mock, patch
import fakeredis
from qdrant.seed import seed
from qdrant_client.models import Distance
from adapters.hybrid_adapters import HybridCaseSearcher
from adapters.elastic_adapters import ElasticLogRepository
from operations.queue import AnalysisQueue, STREAM, METRIC_STREAM, GROUP
from operations.maintenance import archive_stream


class CleanupTests(unittest.TestCase):
    def test_populated_qdrant_collection_preserved_without_embedding(self):
        client = Mock()
        client.collection_exists.return_value = True
        client.get_collection.return_value = types.SimpleNamespace(
            points_count=5,
            config=types.SimpleNamespace(
                params=types.SimpleNamespace(
                    vectors=types.SimpleNamespace(size=384, distance=Distance.COSINE)
                )
            ),
        )
        with (
            patch("qdrant.seed.get_client", return_value=client),
            patch("qdrant.seed.encode") as encode,
        ):
            seed()
            encode.assert_not_called()
        client.delete_collection.assert_not_called()
        client.upload_points.assert_not_called()

    def test_populated_elastic_case_index_is_not_deleted(self):
        from elastic.seed_cases import seed as elastic_seed

        client = Mock()
        client.indices.exists.return_value = True
        client.count.return_value = {"count": 4}
        with patch("elastic.seed_cases.get_client", return_value=client):
            elastic_seed()
        client.indices.delete.assert_not_called()
        client.index.assert_not_called()

    def test_wrong_existing_schema_is_not_deleted(self):
        client = Mock()
        client.collection_exists.return_value = True
        client.get_collection.return_value = types.SimpleNamespace(
            points_count=5,
            config=types.SimpleNamespace(
                params=types.SimpleNamespace(
                    vectors=types.SimpleNamespace(size=12, distance=Distance.COSINE)
                )
            ),
        )
        with patch("qdrant.seed.get_client", return_value=client):
            with self.assertRaises(ValueError):
                seed()
        client.delete_collection.assert_not_called()

    def test_hybrid_search_uses_surviving_backend(self):
        vector = Mock()
        vector.search.side_effect = ConnectionError
        keyword = Mock()
        keyword.search.return_value = [{"incident_id": "one", "score": 1}]
        self.assertEqual(
            HybridCaseSearcher(vector, keyword).search("ERROR", "message")[0][
                "incident_id"
            ],
            "one",
        )
        keyword.search.side_effect = ConnectionError
        with self.assertRaises(RuntimeError):
            HybridCaseSearcher(vector, keyword).search("ERROR", "message")

    def test_repository_does_not_hide_connection_failure(self):
        repo = ElasticLogRepository.__new__(ElasticLogRepository)
        repo.client = Mock()
        repo.client.get.side_effect = ConnectionError
        with self.assertRaises(ConnectionError):
            repo.get_operational_incident("one")

    def test_metric_and_log_streams_are_separate_and_receipts_complete(self):
        redis = fakeredis.FakeRedis(decode_responses=True)
        q = AnalysisQueue(redis)
        q.ensure_group()
        metric = q.enqueue("metrics", {"host": {"hostname": "one"}})
        log = q.enqueue("logs", {"message": "INFO"})
        for stream, identifier in [(METRIC_STREAM, metric), (STREAM, log)]:
            mid, fields = redis.xreadgroup(GROUP, "test", {stream: ">"}, count=1)[0][1][
                0
            ]
            q.process(mid, fields, lambda *args: {"status": "stored"}, stream=stream)
            self.assertEqual(q.get(identifier)["status"], "completed")
            self.assertEqual(redis.xlen(stream), 0)

    def test_retry_respects_backoff(self):
        redis = fakeredis.FakeRedis(decode_responses=True)
        q = AnalysisQueue(redis)
        q.ensure_group()
        identifier = q.enqueue("logs", {"message": "hello"})
        mid, fields = redis.xreadgroup(GROUP, "test", {STREAM: ">"})[0][1][0]
        handler = Mock(side_effect=ConnectionError)
        q.process(mid, fields, handler)
        q.process(mid, fields, handler)
        self.assertEqual(handler.call_count, 1)
        self.assertGreater(q.get(identifier)["next_attempt_at"], time.time())

    def test_archival_deletes_only_after_successful_store(self):
        redis = fakeredis.FakeRedis(decode_responses=True)
        redis.xadd("test-stream", {"event": "old"}, id="1000-0")
        es = Mock()
        es.index.side_effect = ConnectionError
        with self.assertRaises(ConnectionError):
            archive_stream(redis, es, "test-stream", "archive", 1, now=200000)
        self.assertEqual(redis.xlen("test-stream"), 1)
        es.index.side_effect = None
        self.assertEqual(
            archive_stream(redis, es, "test-stream", "archive", 1, now=200000), 1
        )
        self.assertEqual(redis.xlen("test-stream"), 0)

    def test_atomic_update_uses_returned_source_without_second_get(self):
        repo = ElasticLogRepository.__new__(ElasticLogRepository)
        repo.client = Mock()
        repo.client.update.return_value = {
            "result": "updated",
            "get": {"_source": {"version": 2}},
        }
        self.assertEqual(
            repo.update_operational_incident("one", {"version": 2}, 1), {"version": 2}
        )
        repo.client.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()

import threading
import time
import unittest

from aiops.incident_dispatcher import IncidentAnalysisDispatcher
from aiops.operational_incident_service import (
    OperationalIncidentService,
    build_fingerprint,
    build_incident_id,
)
from log_processor import LogProcessor


class FakeRepository:
    """OperationalIncidentService + LogProcessor가 쓰는 저장소를 흉내낸다."""

    def __init__(self):
        self.incidents = {}
        self.logs = []
        self.recommendations = []
        self._lock = threading.Lock()

    # --- LogRepository 계열 ---
    def save_log(self, document):
        with self._lock:
            self.logs.append(document)

    def save_recommendation(self, document):
        with self._lock:
            self.recommendations.append(document)

    def save_diagnosis(self, document):
        pass

    # --- OperationalIncident 계열 ---
    def get_operational_incident(self, incident_id):
        with self._lock:
            value = self.incidents.get(incident_id)
            return dict(value) if value else None

    def create_operational_incident(self, document):
        with self._lock:
            if document["incident_id"] in self.incidents:
                raise RuntimeError("conflict")
            self.incidents[document["incident_id"]] = dict(document)

    def update_operational_incident(
        self, incident_id, changes, expected_version
    ):
        with self._lock:
            current = self.incidents[incident_id]
            if current["version"] != expected_version:
                raise RuntimeError("incident version conflict")
            current.update(changes)
            return dict(current)


class _CaseSearcher:
    def search(self, **kwargs):
        return []


class _RecommendationGenerator:
    """호출 횟수를 세는 추천 생성기. 무거운 분석의 프록시로 쓴다."""

    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    def generate(self, **kwargs):
        with self._lock:
            self.calls += 1
        return {
            "error_code": kwargs["error_code"],
            "runbooks": [{"script_id": "restart_service"}],
        }


class DispatcherCoalescingTests(unittest.TestCase):

    def test_submit_coalesces_same_group_into_pending(self):
        seen = []
        gate = threading.Event()
        started = threading.Event()

        def worker(job):
            started.set()
            gate.wait(1)  # 첫 job을 붙잡아 두는 동안 나머지가 묶이도록 한다.
            seen.append(job["incident_id"])

        dispatcher = IncidentAnalysisDispatcher(worker, max_workers=1)
        self.addCleanup(dispatcher.shutdown)

        # 첫 건: 큐에 들어간다.
        self.assertEqual(
            dispatcher.submit({"incident_id": "INC-1", "n": 1}),
            "queued",
        )
        self.assertTrue(started.wait(1))

        # 처리 중 같은 그룹 3건이 더 들어오면 전부 묶인다(coalesced).
        for n in range(2, 5):
            self.assertEqual(
                dispatcher.submit({"incident_id": "INC-1", "n": n}),
                "coalesced",
            )

        gate.set()
        dispatcher.join(timeout=2)

        # 첫 실행 1회 + 처리 중 유입분 반영 재실행 1회 = 총 2회.
        # (개별 4회가 아니라 하나로 묶였음을 보장)
        self.assertEqual(seen.count("INC-1"), 2)

    def test_distinct_groups_run_independently(self):
        seen = []
        lock = threading.Lock()

        def worker(job):
            with lock:
                seen.append(job["incident_id"])

        dispatcher = IncidentAnalysisDispatcher(worker, max_workers=2)
        self.addCleanup(dispatcher.shutdown)

        for gid in ("INC-A", "INC-B", "INC-C"):
            self.assertEqual(
                dispatcher.submit({"incident_id": gid}), "queued"
            )

        dispatcher.join(timeout=2)
        self.assertEqual(sorted(seen), ["INC-A", "INC-B", "INC-C"])


class AsyncLogProcessorTests(unittest.TestCase):

    def setUp(self):
        self.repository = FakeRepository()
        self.generator = _RecommendationGenerator()
        self.incident_service = OperationalIncidentService(
            self.repository
        )
        self.processor = LogProcessor(
            repository=self.repository,
            case_searcher=_CaseSearcher(),
            recommendation_generator=self.generator,
            incident_service=self.incident_service,
        )
        self.dispatcher = IncidentAnalysisDispatcher(
            worker=self.processor._analyze, max_workers=1
        )
        self.processor.dispatcher = self.dispatcher
        self.addCleanup(self.dispatcher.shutdown)

    def _error_log(self, host="db-01"):
        return {
            "timestamp": "2026-08-19T09:00:00+09:00",
            "level": "ERROR",
            "message": "ORA-28040 authentication protocol mismatch",
            "host": host,
            "service": "payment-api",
            "environment": "prod",
        }

    def test_submit_returns_immediately_and_analyzes_async(self):
        result = self.processor.submit(self._error_log())

        # 접수만 하고 곧바로 반환한다(추천이 응답에 들어있지 않다).
        self.assertEqual(result["status"], "accepted")
        self.assertFalse(result["coalesced"])
        self.assertIn("incident_id", result)
        self.assertNotIn("recommendation", result)

        self.dispatcher.join(timeout=2)

        # 백그라운드에서 분석이 끝나 추천이 저장됐다.
        self.assertEqual(len(self.repository.recommendations), 1)
        incident = self.repository.get_operational_incident(
            result["incident_id"]
        )
        self.assertEqual(incident["status"], "ACTION_REQUIRED")

    def test_same_group_burst_analyzed_at_most_twice(self):
        # 같은 fingerprint 로그 10건을 몰아 넣는다.
        results = [self.processor.submit(self._error_log()) for _ in range(10)]

        incident_id = build_incident_id(
            build_fingerprint(self._error_log(), "ORA-28040")
        )
        self.assertTrue(all(r["status"] == "accepted" for r in results))
        # 최소 한 번은 묶였다(개별 10회 분석이 아니다).
        self.assertTrue(any(r["coalesced"] for r in results))

        self.dispatcher.join(timeout=2)

        # 집계는 10건 모두 반영된다.
        incident = self.repository.get_operational_incident(incident_id)
        self.assertEqual(incident["occurrence_count"], 10)
        # 무거운 분석(LLM 추천 생성)은 개별 10회가 아니라 소수 회만 실행됐다.
        self.assertLessEqual(self.generator.calls, 3)
        self.assertGreaterEqual(self.generator.calls, 1)


if __name__ == "__main__":
    unittest.main()

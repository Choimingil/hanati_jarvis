import unittest

from aiops.analysis_service import MetricAnalysisService
from aiops.anomaly_detector import AnomalyDetector
from aiops.context_builder import ContextBuilder
from aiops.feature_extractor import MetricFeatureExtractor
from aiops.incident_case_builder import IncidentCaseBuilder
from aiops.incident_correlator import IncidentCorrelator
from aiops.recovery_verifier import RecoveryVerifier


def snapshot(timestamp, memory=70, disk=40, close_wait=0, errors=0):
    return {
        "timestamp": timestamp,
        "host": {"hostname": "server01"},
        "cpu": {"percent": 30},
        "memory": {
            "percent": memory,
            "available_bytes": 1000,
            "swap_used_bytes": 0,
        },
        "disk": {
            "root": {"percent": disk, "free_bytes": 1000}
        },
        "network": {
            "errors_in": errors,
            "errors_out": 0,
            "drops_in": 0,
            "drops_out": 0,
            "connections": {
                "by_status": {"CLOSE_WAIT": close_wait}
            },
        },
        "processes": {"items": []},
    }


class FeatureAndDetectionTest(unittest.TestCase):
    def test_extracts_trend_and_detects_multiple_anomalies(self):
        features = MetricFeatureExtractor().extract([
            snapshot("2026-08-07T00:00:00+09:00", memory=70),
            snapshot(
                "2026-08-07T00:05:00+09:00",
                memory=92,
                disk=96,
                close_wait=120,
                errors=25,
            ),
        ])
        codes = {
            event["detection_code"]
            for event in AnomalyDetector().detect(features)
        }
        self.assertEqual(features["memory_slope"], 22)
        self.assertIn("1m", features["windows"])
        self.assertIn("5m", features["windows"])
        self.assertIn("15m", features["windows"])
        self.assertIn("MEMORY_LEAK_SUSPECTED", codes)
        self.assertIn("DISK_FULL_PREDICTED", codes)
        self.assertIn("CONNECTION_LEAK_SUSPECTED", codes)
        self.assertIn("NETWORK_ERRORS_INCREASING", codes)


class RecoveryVerifierTest(unittest.TestCase):
    def test_verifies_memory_recovery(self):
        incident = {
            "incident_id": "i-1",
            "error_code": "MEMORY_LEAK",
            "metric_features": {"memory_latest": 92},
        }
        result = RecoveryVerifier().verify(
            incident,
            [snapshot("2026-08-07T00:10:00+09:00", memory=80)],
        )
        self.assertTrue(result["recovered"])


class _Repository:
    def __init__(self, snapshots):
        self.snapshots = snapshots
        self.incidents = []
        self.recommendations = []

    def recent_metrics(self, host, minutes):
        return list(self.snapshots)

    def has_recent_incident(self, host, code, minutes):
        return False

    def recent_error_logs(self, host, minutes):
        return [{
            "timestamp": "2026-08-07T00:04:00+09:00",
            "level": "ERROR",
            "message": "memory allocation failed",
            "service": "order-service",
        }]

    def save_incident(self, document):
        self.incidents.append(document)

    def save_recommendation(self, document):
        self.recommendations.append(document)


class _CaseSearcher:
    def search(self, **kwargs):
        return [{"summary": "past memory incident"}]


class _Generator:
    def generate(self, **kwargs):
        return {
            "cause": "memory leak",
            "runbooks": [{"script_id": "restart_application"}],
        }


class _Indexer:
    def __init__(self):
        self.indexed = []

    def index(self, incident):
        self.indexed.append(incident)


class AnalysisServiceTest(unittest.TestCase):
    def test_builds_retrievable_incident_and_recommendation(self):
        current = snapshot(
            "2026-08-07T00:05:00+09:00", memory=92
        )
        repository = _Repository([
            snapshot("2026-08-07T00:00:00+09:00", memory=70),
            current,
        ])
        indexer = _Indexer()
        service = MetricAnalysisService(
            repository=repository,
            case_searcher=_CaseSearcher(),
            recommendation_generator=_Generator(),
            feature_extractor=MetricFeatureExtractor(),
            anomaly_detector=AnomalyDetector(),
            correlator=IncidentCorrelator(),
            case_builder=IncidentCaseBuilder(),
            incident_indexer=indexer,
            context_builder=ContextBuilder(),
        )

        results = service.analyze(current)

        self.assertEqual(results[0]["status"], "recommended")
        self.assertEqual(len(repository.incidents), 1)
        self.assertEqual(len(repository.recommendations), 1)
        self.assertEqual(len(indexer.indexed), 1)
        self.assertIn(
            "memory allocation failed",
            repository.incidents[0]["summary"]
            + str(repository.incidents[0]["related_logs"]),
        )


if __name__ == "__main__":
    unittest.main()

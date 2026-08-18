import unittest

from aiops.fallback_guidance_generator import FallbackGuidanceGenerator
from aiops.feature_extractor import MetricFeatureExtractor
from aiops.operator_feedback_service import OperatorFeedbackService
from aiops.recommendation_quality_gate import RecommendationQualityGate
from aiops.resource_context_loader import ResourceContextLoader
from aiops.resource_hypothesis_engine import ResourceHypothesisEngine
from log_processor import LogProcessor


def metric(memory=92, close_wait=0):
    return {
        "timestamp": "2026-08-07T12:00:00+09:00",
        "host": {"hostname": "server01"},
        "cpu": {"percent": 30},
        "memory": {
            "percent": memory,
            "available_bytes": 1000,
            "swap_used_bytes": 0,
        },
        "disk": {"root": {"percent": 40, "free_bytes": 1000}},
        "network": {
            "errors_in": 0,
            "errors_out": 0,
            "drops_in": 0,
            "drops_out": 0,
            "connections": {
                "by_status": {"CLOSE_WAIT": close_wait}
            },
        },
        "processes": {"items": []},
    }


class _Repository:
    def __init__(self):
        self.guidance = {}
        self.feedback = []
        self.incidents = []
        self.recommendations = []

    def save_log(self, document):
        pass

    def recent_metrics(self, host, minutes):
        return [metric()]

    def save_resource_guidance(self, document):
        self.guidance[document["guidance_id"]] = document

    def get_resource_guidance(self, guidance_id):
        return self.guidance.get(guidance_id)

    def save_recommendation(self, document):
        self.recommendations.append(document)

    def save_operator_feedback(self, document):
        self.feedback.append(document)

    def save_incident(self, document):
        self.incidents.append(document)


class _CaseSearcher:
    def search(self, **kwargs):
        return [{"summary": "verified memory case"}]


class _RecommendationGenerator:
    def generate(self, **kwargs):
        return None


class _InvalidLLM:
    def generate_text(self, prompt):
        return "fallback"


class _Indexer:
    def __init__(self):
        self.items = []

    def index(self, incident):
        self.items.append(incident)


class ResourceFallbackTest(unittest.TestCase):
    def test_unknown_error_returns_resource_guidance(self):
        repository = _Repository()
        processor = LogProcessor(
            repository=repository,
            case_searcher=_CaseSearcher(),
            recommendation_generator=_RecommendationGenerator(),
            quality_gate=RecommendationQualityGate(),
            resource_context_loader=ResourceContextLoader(
                repository, MetricFeatureExtractor()
            ),
            resource_hypothesis_engine=ResourceHypothesisEngine(),
            fallback_guidance_generator=FallbackGuidanceGenerator(
                _InvalidLLM()
            ),
        )

        result = processor.process({
            "timestamp": "2026-08-07T12:00:00+09:00",
            "level": "ERROR",
            "message": "Unregistered worker failure XYZ-123",
            "host": "server01",
            "service": "order-service",
        })

        self.assertEqual(result["status"], "resource_guidance")
        self.assertEqual(
            result["primary_problem_code"], "MEMORY_LEAK_SUSPECTED"
        )
        self.assertFalse(result["automatic_remediation"])
        self.assertEqual(len(repository.guidance), 1)

    def test_quality_gate_rejects_low_confidence_runbook(self):
        fallback, reason = RecommendationQualityGate().requires_fallback(
            "MEMORY_LEAK",
            ["restart_application"],
            {"runbooks": [{"confidence": 40}]},
        )
        self.assertTrue(fallback)
        self.assertEqual(reason, "low_recommendation_confidence")


class OperatorFeedbackTest(unittest.TestCase):
    def test_only_confirmed_recovery_is_promoted(self):
        repository = _Repository()
        repository.guidance["g-1"] = {
            "guidance_id": "g-1",
            "created_at": "2026-08-07T12:00:00+09:00",
            "host": "server01",
            "service": "order-service",
            "summary": "memory issue",
            "primary_problem_code": "MEMORY_LEAK_SUSPECTED",
            "hypotheses": [{
                "problem_code": "MEMORY_LEAK_SUSPECTED",
                "related_error_code": "MEMORY_LEAK",
            }],
            "resource_features": {"memory_latest": 92},
        }
        indexer = _Indexer()
        service = OperatorFeedbackService(repository, indexer)

        result = service.submit({
            "guidance_id": "g-1",
            "operator": "tester",
            "verdict": "confirmed",
            "confirmed_root_cause": "cache growth",
            "successful_action": "restart application",
            "recovered": True,
        })

        self.assertTrue(result["promoted_to_incident_case"])
        self.assertEqual(len(repository.incidents), 1)
        self.assertEqual(len(indexer.items), 1)

    def test_rejected_guidance_is_not_promoted(self):
        repository = _Repository()
        repository.guidance["g-2"] = {
            "guidance_id": "g-2",
            "created_at": "2026-08-07T12:00:00+09:00",
            "host": "server01",
            "summary": "not relevant",
            "primary_problem_code": "RESOURCE_STATE_NORMAL",
            "hypotheses": [],
            "resource_features": {},
        }
        indexer = _Indexer()

        result = OperatorFeedbackService(repository, indexer).submit({
            "guidance_id": "g-2",
            "operator": "tester",
            "verdict": "rejected",
            "recovered": False,
        })

        self.assertFalse(result["promoted_to_incident_case"])
        self.assertEqual(repository.incidents, [])
        self.assertEqual(indexer.items, [])


if __name__ == "__main__":
    unittest.main()

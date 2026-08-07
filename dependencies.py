from adapters.elastic_adapters import (
    ElasticCaseSearcher,
    ElasticLogRepository,
)
from adapters.llm_adapters import LLMRecommendationGenerator
from adapters.qdrant_adapters import QdrantCaseSearcher
from config import CASE_SEARCHER_BACKEND
from log_processor import LogProcessor
from aiops.analysis_service import MetricAnalysisService
from aiops.anomaly_detector import AnomalyDetector
from aiops.context_builder import ContextBuilder
from aiops.feature_extractor import MetricFeatureExtractor
from aiops.incident_case_builder import IncidentCaseBuilder
from aiops.incident_correlator import IncidentCorrelator
from aiops.incident_indexer import QdrantIncidentIndexer
from aiops.recovery_verifier import RecoveryVerifier


repository = ElasticLogRepository()

if CASE_SEARCHER_BACKEND == "hybrid":
    from adapters.hybrid_adapters import (
        HybridCaseSearcher,
    )

    case_searcher = HybridCaseSearcher(
        vector_searcher=QdrantCaseSearcher(),
        keyword_searcher=ElasticCaseSearcher(),
    )
elif CASE_SEARCHER_BACKEND == "elastic":
    case_searcher = ElasticCaseSearcher()
else:
    case_searcher = QdrantCaseSearcher()

recommendation_generator = LLMRecommendationGenerator(
    history_provider=repository
)


log_processor = LogProcessor(
    repository=repository,
    case_searcher=case_searcher,
    recommendation_generator=(
        recommendation_generator
    ),
)

recovery_verifier = RecoveryVerifier()

metric_analysis_service = MetricAnalysisService(
    repository=repository,
    case_searcher=case_searcher,
    recommendation_generator=recommendation_generator,
    feature_extractor=MetricFeatureExtractor(),
    anomaly_detector=AnomalyDetector(),
    correlator=IncidentCorrelator(),
    case_builder=IncidentCaseBuilder(),
    incident_indexer=QdrantIncidentIndexer(),
    context_builder=ContextBuilder(),
)

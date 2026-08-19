from adapters.elastic_adapters import (
    ElasticCaseSearcher,
    ElasticLogRepository,
)
from adapters.llm_adapters import LLMRecommendationGenerator
from adapters.qdrant_adapters import QdrantCaseSearcher
from config import (
    CASE_SEARCHER_BACKEND,
    INCIDENT_ANALYSIS_ASYNC,
    INCIDENT_ANALYSIS_WORKERS,
)
from log_processor import LogProcessor
from aiops.incident_dispatcher import IncidentAnalysisDispatcher
from aiops.analysis_service import MetricAnalysisService
from aiops.anomaly_detector import AnomalyDetector
from aiops.context_builder import ContextBuilder
from aiops.feature_extractor import MetricFeatureExtractor
from aiops.incident_case_builder import IncidentCaseBuilder
from aiops.incident_correlator import IncidentCorrelator
from aiops.incident_indexer import QdrantIncidentIndexer
from aiops.recovery_verifier import RecoveryVerifier
from aiops.fallback_guidance_generator import FallbackGuidanceGenerator
from aiops.operator_feedback_service import OperatorFeedbackService
from aiops.operational_incident_service import OperationalIncidentService
from aiops.recommendation_quality_gate import RecommendationQualityGate
from aiops.resource_context_loader import ResourceContextLoader
from aiops.resource_hypothesis_engine import ResourceHypothesisEngine


repository = ElasticLogRepository()
operational_incident_service = OperationalIncidentService(repository)

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
    quality_gate=RecommendationQualityGate(),
    resource_context_loader=ResourceContextLoader(
        repository, MetricFeatureExtractor()
    ),
    resource_hypothesis_engine=ResourceHypothesisEngine(),
    fallback_guidance_generator=FallbackGuidanceGenerator(),
    incident_service=operational_incident_service,
)

# 비동기 분석 디스패처. 같은 장애 그룹은 진행 중인 분석 1건으로 묶는다.
# INCIDENT_ANALYSIS_ASYNC=false면 디스패처를 붙이지 않아 동기로 동작한다.
incident_dispatcher = None
if INCIDENT_ANALYSIS_ASYNC:
    incident_dispatcher = IncidentAnalysisDispatcher(
        worker=log_processor._analyze,
        max_workers=INCIDENT_ANALYSIS_WORKERS,
    )
    log_processor.dispatcher = incident_dispatcher

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

operator_feedback_service = OperatorFeedbackService(
    repository=repository,
    incident_indexer=QdrantIncidentIndexer(),
)

from adapters.elastic_adapters import (
    ElasticCaseSearcher,
    ElasticLogRepository,
)
from adapters.llm_adapters import LLMRecommendationGenerator
from adapters.qdrant_adapters import QdrantCaseSearcher
from config import CASE_SEARCHER_BACKEND
from log_processor import LogProcessor


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

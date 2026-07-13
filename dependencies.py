from adapters.mock_adapters import (
    MockCaseSearcher,
    MockLogRepository,
    MockRecommendationGenerator,
)
from config import (
    CASE_SEARCHER_BACKEND,
    LOG_REPOSITORY_BACKEND,
)
from log_processor import LogProcessor


if LOG_REPOSITORY_BACKEND == "elastic":
    from adapters.elastic_adapters import (
        ElasticLogRepository,
    )

    repository = ElasticLogRepository()
else:
    repository = MockLogRepository()

if CASE_SEARCHER_BACKEND == "hybrid":
    from adapters.elastic_adapters import (
        ElasticCaseSearcher,
    )
    from adapters.hybrid_adapters import (
        HybridCaseSearcher,
    )
    from adapters.qdrant_adapters import (
        QdrantCaseSearcher,
    )

    case_searcher = HybridCaseSearcher(
        vector_searcher=QdrantCaseSearcher(),
        keyword_searcher=ElasticCaseSearcher(),
    )
elif CASE_SEARCHER_BACKEND == "elastic":
    from adapters.elastic_adapters import (
        ElasticCaseSearcher,
    )

    case_searcher = ElasticCaseSearcher()
elif CASE_SEARCHER_BACKEND == "qdrant":
    from adapters.qdrant_adapters import (
        QdrantCaseSearcher,
    )

    case_searcher = QdrantCaseSearcher()
else:
    case_searcher = MockCaseSearcher()

recommendation_generator = (
    MockRecommendationGenerator()
)


log_processor = LogProcessor(
    repository=repository,
    case_searcher=case_searcher,
    recommendation_generator=(
        recommendation_generator
    ),
)

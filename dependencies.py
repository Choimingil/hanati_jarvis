from adapters.mock_adapters import (
    MockCaseSearcher,
    MockLogRepository,
    MockRecommendationGenerator,
)
from config import CASE_SEARCHER_BACKEND
from log_processor import LogProcessor


repository = MockLogRepository()

if CASE_SEARCHER_BACKEND == "qdrant":
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

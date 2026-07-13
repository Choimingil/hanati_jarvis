from adapters.mock_adapters import (
    MockCaseSearcher,
    MockLogRepository,
    MockRecommendationGenerator,
)
from log_processor import LogProcessor


repository = MockLogRepository()
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

from abc import ABC, abstractmethod
from typing import Any


class RecommendationGenerator(ABC):

    @abstractmethod
    def generate(
        self,
        error_code: str,
        message: str,
        diagnosis_results: list[dict[str, Any]],
        past_cases: list[dict[str, Any]],
        remediation_candidates: list[str],
    ) -> dict[str, Any]:
        pass

from abc import ABC, abstractmethod
from typing import Any


class CaseSearcher(ABC):

    @abstractmethod
    def search(
        self,
        error_code: str,
        message: str,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        pass

from abc import ABC, abstractmethod
from typing import Any


class LogRepository(ABC):

    @abstractmethod
    def save_log(
        self,
        document: dict[str, Any],
    ) -> None:
        pass

    @abstractmethod
    def save_diagnosis(
        self,
        document: dict[str, Any],
    ) -> None:
        pass

    @abstractmethod
    def save_recommendation(
        self,
        document: dict[str, Any],
    ) -> None:
        pass

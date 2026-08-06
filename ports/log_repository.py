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

    @abstractmethod
    def save_remediation(
        self,
        document: dict[str, Any],
    ) -> None:
        pass

    @abstractmethod
    def remediation_history(
        self,
        script_id: str,
    ) -> dict[str, int]:
        """해당 스크립트의 과거 실행 성공/실패 횟수."""
        pass

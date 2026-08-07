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
    def save_metric(
        self,
        document: dict[str, Any],
    ) -> None:
        pass

    @abstractmethod
    def recent_metrics(
        self, host: str, minutes: int
    ) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    def recent_error_logs(
        self, host: str, minutes: int
    ) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    def save_incident(self, document: dict[str, Any]) -> None:
        pass

    @abstractmethod
    def has_recent_incident(
        self, host: str, detection_code: str, minutes: int
    ) -> bool:
        pass

    @abstractmethod
    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        pass

    @abstractmethod
    def save_recovery_verification(
        self, document: dict[str, Any]
    ) -> None:
        pass

    @abstractmethod
    def remediation_history(
        self,
        script_id: str,
    ) -> dict[str, int]:
        """해당 스크립트의 과거 실행 성공/실패 횟수."""
        pass

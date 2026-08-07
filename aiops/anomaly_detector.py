from __future__ import annotations

from typing import Any

from config import (
    ANOMALY_CLOSE_WAIT_THRESHOLD,
    ANOMALY_DISK_PERCENT_THRESHOLD,
    ANOMALY_MEMORY_GROWTH_THRESHOLD,
    ANOMALY_MEMORY_PERCENT_THRESHOLD,
    ANOMALY_NETWORK_ERROR_GROWTH_THRESHOLD,
)


class AnomalyDetector:
    """Explainable rules used until enough labelled incidents exist."""

    def detect(
        self, features: dict[str, Any]
    ) -> list[dict[str, Any]]:
        if not features:
            return []

        events: list[dict[str, Any]] = []
        if (
            features["memory_latest"] >= ANOMALY_MEMORY_PERCENT_THRESHOLD
            or features["memory_slope"]
            >= ANOMALY_MEMORY_GROWTH_THRESHOLD
        ):
            events.append({
                "error_code": "MEMORY_LEAK",
                "detection_code": "MEMORY_LEAK_SUSPECTED",
                "severity": "critical"
                if features["memory_latest"] >= 95 else "warning",
                "evidence": [
                    f"메모리 사용률 {features['memory_latest']}%",
                    f"분석 구간 증가량 {features['memory_slope']}%p",
                    f"가용 메모리 {features['available_memory_bytes']} bytes",
                ],
            })

        if features["disk_latest"] >= ANOMALY_DISK_PERCENT_THRESHOLD:
            events.append({
                "error_code": "DISK_FULL",
                "detection_code": "DISK_FULL_PREDICTED",
                "severity": "critical"
                if features["disk_latest"] >= 95 else "warning",
                "evidence": [
                    f"디스크 사용률 {features['disk_latest']}%",
                    f"분석 구간 증가량 {features['disk_growth']}%p",
                    f"남은 공간 {features['disk_free_bytes']} bytes",
                ],
            })

        if features["close_wait_latest"] >= ANOMALY_CLOSE_WAIT_THRESHOLD:
            events.append({
                "error_code": "DB_CONNECTION_FAILURE",
                "detection_code": "CONNECTION_LEAK_SUSPECTED",
                "severity": "warning",
                "evidence": [
                    f"CLOSE_WAIT {features['close_wait_latest']}개",
                    f"분석 구간 증가량 {features['close_wait_growth']}개",
                ],
            })

        if (
            features["network_error_growth"]
            >= ANOMALY_NETWORK_ERROR_GROWTH_THRESHOLD
        ):
            events.append({
                "error_code": "EXTERNAL_API_FAILURE",
                "detection_code": "NETWORK_ERRORS_INCREASING",
                "severity": "warning",
                "evidence": [
                    "네트워크 오류·드롭 증가량 "
                    f"{features['network_error_growth']}개"
                ],
            })

        return events

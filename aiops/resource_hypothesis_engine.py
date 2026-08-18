from __future__ import annotations

from typing import Any

from config import (
    ANOMALY_CLOSE_WAIT_THRESHOLD,
    ANOMALY_DISK_PERCENT_THRESHOLD,
    ANOMALY_MEMORY_GROWTH_THRESHOLD,
    ANOMALY_MEMORY_PERCENT_THRESHOLD,
    ANOMALY_NETWORK_ERROR_GROWTH_THRESHOLD,
    RESOURCE_CPU_PERCENT_THRESHOLD,
)


class ResourceHypothesisEngine:
    """Create evidence-backed hypotheses; never claim an unverified cause."""

    def analyze(
        self, features: dict[str, Any]
    ) -> list[dict[str, Any]]:
        if not features:
            return [{
                "problem_code": "INSUFFICIENT_RESOURCE_DATA",
                "title": "리소스 데이터 부족",
                "confidence": 0,
                "evidence": ["최근 15분 메트릭이 없습니다."],
                "suggested_diagnostics": [
                    "psutil Agent 실행 상태 확인",
                    "호스트 식별자 일치 여부 확인",
                ],
                "related_error_code": None,
            }]

        hypotheses: list[dict[str, Any]] = []
        if features["cpu_avg"] >= RESOURCE_CPU_PERCENT_THRESHOLD:
            hypotheses.append({
                "problem_code": "CPU_SATURATION",
                "title": "CPU 포화 가능성",
                "confidence": self._confidence(
                    features["cpu_avg"], RESOURCE_CPU_PERCENT_THRESHOLD
                ),
                "evidence": [
                    f"15분 CPU 평균 {features['cpu_avg']}%",
                    f"15분 CPU 최대 {features['cpu_max']}%",
                    "최상위 프로세스 "
                    f"{features['top_process'].get('name')} "
                    f"CPU {features['top_process'].get('cpu_percent')}%",
                ],
                "suggested_diagnostics": [
                    "상위 CPU 프로세스와 스레드 확인",
                    "같은 시간대 요청량과 최근 배포 확인",
                ],
                "related_error_code": None,
            })

        if (
            features["memory_latest"] >= ANOMALY_MEMORY_PERCENT_THRESHOLD
            or features["memory_slope"]
            >= ANOMALY_MEMORY_GROWTH_THRESHOLD
        ):
            hypotheses.append({
                "problem_code": "MEMORY_LEAK_SUSPECTED",
                "title": "메모리 누수 또는 캐시 증가 가능성",
                "confidence": max(
                    self._confidence(
                        features["memory_latest"],
                        ANOMALY_MEMORY_PERCENT_THRESHOLD,
                    ),
                    min(0.95, 0.55 + features["memory_slope"] / 100),
                ),
                "evidence": [
                    f"메모리 사용률 {features['memory_latest']}%",
                    f"15분 증가량 {features['memory_slope']}%p",
                    f"Swap 사용량 {features['swap_used_bytes']} bytes",
                ],
                "suggested_diagnostics": [
                    "상위 RSS 프로세스 확인",
                    "힙·GC·캐시 엔트리 수 확인",
                ],
                "related_error_code": "MEMORY_LEAK",
            })

        if features["disk_latest"] >= ANOMALY_DISK_PERCENT_THRESHOLD:
            hypotheses.append({
                "problem_code": "DISK_PRESSURE",
                "title": "로그 또는 임시 파일 증가 가능성",
                "confidence": self._confidence(
                    features["disk_latest"],
                    ANOMALY_DISK_PERCENT_THRESHOLD,
                ),
                "evidence": [
                    f"디스크 사용률 {features['disk_latest']}%",
                    f"남은 공간 {features['disk_free_bytes']} bytes",
                ],
                "suggested_diagnostics": [
                    "대용량 파일과 inode 사용률 확인",
                    "로그 로테이션 및 열린 삭제 파일 확인",
                ],
                "related_error_code": "DISK_FULL",
            })

        if features["close_wait_latest"] >= ANOMALY_CLOSE_WAIT_THRESHOLD:
            hypotheses.append({
                "problem_code": "CONNECTION_LEAK_SUSPECTED",
                "title": "소켓 또는 커넥션 반환 누락 가능성",
                "confidence": self._confidence(
                    features["close_wait_latest"],
                    ANOMALY_CLOSE_WAIT_THRESHOLD,
                ),
                "evidence": [
                    f"CLOSE_WAIT {features['close_wait_latest']}개",
                    f"15분 증가량 {features['close_wait_growth']}개",
                ],
                "suggested_diagnostics": [
                    "PID별 TCP 연결과 대상 포트 확인",
                    "HTTP·DB 클라이언트 종료 및 timeout 설정 확인",
                ],
                "related_error_code": "DB_CONNECTION_FAILURE",
            })

        if (
            features["network_error_growth"]
            >= ANOMALY_NETWORK_ERROR_GROWTH_THRESHOLD
        ):
            hypotheses.append({
                "problem_code": "NETWORK_INSTABILITY",
                "title": "네트워크 패킷 손실 가능성",
                "confidence": self._confidence(
                    features["network_error_growth"],
                    ANOMALY_NETWORK_ERROR_GROWTH_THRESHOLD,
                ),
                "evidence": [
                    "네트워크 오류·드롭 증가량 "
                    f"{features['network_error_growth']}개"
                ],
                "suggested_diagnostics": [
                    "인터페이스 오류와 라우팅 경로 확인",
                    "DNS 및 대상 포트 연결 확인",
                ],
                "related_error_code": "EXTERNAL_API_FAILURE",
            })

        if not hypotheses:
            hypotheses.append({
                "problem_code": "RESOURCE_STATE_NORMAL",
                "title": "주요 리소스 이상 징후 없음",
                "confidence": 0.9,
                "evidence": [
                    f"CPU 평균 {features['cpu_avg']}%",
                    f"메모리 {features['memory_latest']}%",
                    f"디스크 {features['disk_latest']}%",
                    f"CLOSE_WAIT {features['close_wait_latest']}개",
                ],
                "suggested_diagnostics": [
                    "애플리케이션 입력 데이터와 로직 확인",
                    "외부 시스템 응답 및 최근 배포 확인",
                ],
                "related_error_code": None,
            })

        return sorted(
            hypotheses, key=lambda item: item["confidence"], reverse=True
        )

    @staticmethod
    def _confidence(value: float, threshold: float) -> float:
        excess = max(0.0, float(value) - float(threshold))
        return round(min(0.95, 0.65 + excess / max(threshold, 1)), 2)

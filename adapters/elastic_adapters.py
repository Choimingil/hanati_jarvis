from typing import Any

from config import (
    ELASTIC_DIAGNOSIS_INDEX,
    ELASTIC_INCIDENT_CASES_INDEX,
    ELASTIC_LOG_INDEX,
    ELASTIC_METRICS_INDEX,
    ELASTIC_OPERATOR_FEEDBACK_INDEX,
    ELASTIC_RECOMMENDATION_INDEX,
    ELASTIC_RECOVERY_INDEX,
    ELASTIC_RESOURCE_GUIDANCE_INDEX,
    ELASTIC_REMEDIATION_INDEX,
)
from elastic.client import get_client
from ports.case_searcher import CaseSearcher
from ports.log_repository import LogRepository


class ElasticLogRepository(LogRepository):

    def __init__(self) -> None:
        self.client = get_client()

    def _index(
        self,
        index: str,
        document: dict[str, Any],
    ) -> None:
        self.client.index(
            index=index,
            document=document,
        )

    def save_log(
        self,
        document: dict[str, Any],
    ) -> None:
        self._index(ELASTIC_LOG_INDEX, document)

    def save_diagnosis(
        self,
        document: dict[str, Any],
    ) -> None:
        self._index(ELASTIC_DIAGNOSIS_INDEX, document)

    def save_recommendation(
        self,
        document: dict[str, Any],
    ) -> None:
        self._index(
            ELASTIC_RECOMMENDATION_INDEX, document
        )

    def save_remediation(
        self,
        document: dict[str, Any],
    ) -> None:
        self._index(ELASTIC_REMEDIATION_INDEX, document)

    def save_metric(
        self,
        document: dict[str, Any],
    ) -> None:
        self._index(ELASTIC_METRICS_INDEX, document)

    def recent_metrics(
        self, host: str, minutes: int
    ) -> list[dict[str, Any]]:
        response = self.client.search(
            index=ELASTIC_METRICS_INDEX,
            query={"bool": {"filter": [
                {"term": {"host.hostname.keyword": host}},
                {"range": {"timestamp": {"gte": f"now-{minutes}m"}}},
            ]}},
            sort=[{"timestamp": "asc"}],
            size=1000,
            ignore_unavailable=True,
        )
        return [hit["_source"] for hit in response["hits"]["hits"]]

    def recent_error_logs(
        self, host: str, minutes: int
    ) -> list[dict[str, Any]]:
        response = self.client.search(
            index=ELASTIC_LOG_INDEX,
            query={"bool": {"filter": [
                {"term": {"host": host}},
                {"term": {"level": "ERROR"}},
                {"range": {"timestamp": {"gte": f"now-{minutes}m"}}},
            ]}},
            sort=[{"timestamp": "desc"}],
            size=20,
            ignore_unavailable=True,
        )
        return [hit["_source"] for hit in response["hits"]["hits"]]

    def save_incident(self, document: dict[str, Any]) -> None:
        self.client.index(
            index=ELASTIC_INCIDENT_CASES_INDEX,
            id=document["incident_id"],
            document=document,
            refresh="wait_for",
        )

    def has_recent_incident(
        self, host: str, detection_code: str, minutes: int
    ) -> bool:
        response = self.client.count(
            index=ELASTIC_INCIDENT_CASES_INDEX,
            query={"bool": {"filter": [
                {"term": {"host.keyword": host}},
                {"term": {"detection_code.keyword": detection_code}},
                {"range": {"created_at": {"gte": f"now-{minutes}m"}}},
            ]}},
            ignore_unavailable=True,
        )
        return response.get("count", 0) > 0

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        try:
            response = self.client.get(
                index=ELASTIC_INCIDENT_CASES_INDEX,
                id=incident_id,
            )
        except Exception:
            return None
        return response.get("_source")

    def save_recovery_verification(
        self, document: dict[str, Any]
    ) -> None:
        self._index(ELASTIC_RECOVERY_INDEX, document)

    def save_resource_guidance(
        self, document: dict[str, Any]
    ) -> None:
        self.client.index(
            index=ELASTIC_RESOURCE_GUIDANCE_INDEX,
            id=document["guidance_id"],
            document=document,
            refresh="wait_for",
        )

    def get_resource_guidance(
        self, guidance_id: str
    ) -> dict[str, Any] | None:
        try:
            response = self.client.get(
                index=ELASTIC_RESOURCE_GUIDANCE_INDEX,
                id=guidance_id,
            )
        except Exception:
            return None
        return response.get("_source")

    def save_operator_feedback(
        self, document: dict[str, Any]
    ) -> None:
        self._index(ELASTIC_OPERATOR_FEEDBACK_INDEX, document)

    def remediation_history(
        self,
        script_id: str,
    ) -> dict[str, int]:
        try:
            response = self.client.search(
                index=ELASTIC_REMEDIATION_INDEX,
                query={
                    "term": {"script_id.keyword": script_id}
                },
                size=0,
                aggs={
                    "by_status": {
                        "terms": {
                            "field": "result.status.keyword"
                        }
                    }
                },
                ignore_unavailable=True,
            )
        except Exception:
            return {"success": 0, "failure": 0}

        buckets = (
            response.get("aggregations", {})
            .get("by_status", {})
            .get("buckets", [])
        )

        # "rejected"/"blocked"는 실제로 실행된 적이 없으니 성공/실패
        # 어느 쪽에도 안 넣는다 - 넣으면 실행 이력이 아니라 거짓 통계가 된다.
        success = 0
        failure = 0
        for bucket in buckets:
            count = bucket.get("doc_count", 0)
            key = bucket.get("key")
            if key == "success":
                success += count
            elif key in ("failed", "timeout"):
                failure += count

        return {"success": success, "failure": failure}


class ElasticCaseSearcher(CaseSearcher):

    def __init__(self) -> None:
        self.client = get_client()

    def search(
        self,
        error_code: str,
        message: str,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        query = {
            "bool": {
                "should": [
                    {
                        "term": {
                            "error_code": error_code
                        }
                    },
                    {"match": {"summary": message}},
                    {
                        "match": {
                            "root_cause": message
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        }

        response = self.client.search(
            index=ELASTIC_INCIDENT_CASES_INDEX,
            query=query,
            size=limit,
        )

        hits = response["hits"]["hits"]

        return [
            {
                **hit["_source"],
                "score": hit["_score"],
            }
            for hit in hits
        ]

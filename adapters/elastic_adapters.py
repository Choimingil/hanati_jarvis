from typing import Any
from elasticsearch import NotFoundError

from config import (
    ELASTIC_DIAGNOSIS_INDEX,
    ELASTIC_INCIDENT_CASES_INDEX,
    ELASTIC_INCIDENT_INDEX,
    ELASTIC_LOG_INDEX,
    ELASTIC_METRICS_INDEX,
    ELASTIC_OPERATOR_FEEDBACK_INDEX,
    ELASTIC_RECOMMENDATION_INDEX,
    ELASTIC_RECOVERY_INDEX,
    ELASTIC_RESOURCE_GUIDANCE_INDEX,
    ELASTIC_REMEDIATION_INDEX,
)
from elastic.client import get_client
from operations.privacy import redact
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
            document=redact(document),
        )

    def save_log(
        self,
        document: dict[str, Any],
    ) -> None:
        ingestion_id = document.get("ingestion_id")
        if ingestion_id:
            self.client.index(
                index=ELASTIC_LOG_INDEX, id=ingestion_id, document=redact(document)
            )
        else:
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
        recommendation = (
            document.get("recommendation") or document.get("guidance") or {}
        )
        recommendation_id = recommendation.get("recommendation_id")
        if recommendation_id:
            self.client.index(
                index=ELASTIC_RECOMMENDATION_INDEX,
                id=recommendation_id,
                document=redact(document),
            )
        else:
            self._index(ELASTIC_RECOMMENDATION_INDEX, document)

    def save_remediation(
        self,
        document: dict[str, Any],
    ) -> None:
        self._index(ELASTIC_REMEDIATION_INDEX, document)

    def save_metric(
        self,
        document: dict[str, Any],
    ) -> None:
        ingestion_id = document.get("ingestion_id")
        if ingestion_id:
            self.client.index(
                index=ELASTIC_METRICS_INDEX, id=ingestion_id, document=redact(document)
            )
        else:
            self._index(ELASTIC_METRICS_INDEX, document)

    def recent_metrics(self, host: str, minutes: int) -> list[dict[str, Any]]:
        response = self.client.search(
            index=ELASTIC_METRICS_INDEX,
            query={
                "bool": {
                    "filter": [
                        {"term": {"host.hostname.keyword": host}},
                        {"range": {"timestamp": {"gte": f"now-{minutes}m"}}},
                    ]
                }
            },
            sort=[{"timestamp": "desc"}],
            size=1000,
            ignore_unavailable=True,
        )
        return list(reversed([hit["_source"] for hit in response["hits"]["hits"]]))

    def recent_error_logs(self, host: str, minutes: int) -> list[dict[str, Any]]:
        response = self.client.search(
            index=ELASTIC_LOG_INDEX,
            query={
                "bool": {
                    "filter": [
                        {"term": {"host": host}},
                        {"term": {"level": "ERROR"}},
                        {"range": {"timestamp": {"gte": f"now-{minutes}m"}}},
                    ]
                }
            },
            sort=[{"timestamp": "desc"}],
            size=20,
            ignore_unavailable=True,
        )
        return [hit["_source"] for hit in response["hits"]["hits"]]

    def save_incident(self, document: dict[str, Any]) -> None:
        self.client.index(
            index=ELASTIC_INCIDENT_CASES_INDEX,
            id=document["incident_id"],
            document=redact(document),
            refresh="wait_for",
        )

    def has_recent_incident(self, host: str, detection_code: str, minutes: int) -> bool:
        response = self.client.count(
            index=ELASTIC_INCIDENT_CASES_INDEX,
            query={
                "bool": {
                    "filter": [
                        {"term": {"host.keyword": host}},
                        {"term": {"detection_code.keyword": detection_code}},
                        {"range": {"created_at": {"gte": f"now-{minutes}m"}}},
                    ]
                }
            },
            ignore_unavailable=True,
        )
        return response.get("count", 0) > 0

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        try:
            response = self.client.get(
                index=ELASTIC_INCIDENT_CASES_INDEX,
                id=incident_id,
            )
        except NotFoundError:
            return None
        return response.get("_source")

    def get_operational_incident(self, incident_id: str) -> dict[str, Any] | None:
        try:
            response = self.client.get(
                index=ELASTIC_INCIDENT_INDEX,
                id=incident_id,
            )
        except NotFoundError:
            return None
        return response.get("_source")

    def create_operational_incident(self, document: dict[str, Any]) -> None:
        self.client.index(
            index=ELASTIC_INCIDENT_INDEX,
            id=document["incident_id"],
            document=redact(document),
            op_type="create",
            refresh="wait_for",
        )

    def update_operational_incident(
        self,
        incident_id: str,
        changes: dict[str, Any],
        expected_version: int,
    ) -> dict[str, Any]:
        response = self.client.update(
            index=ELASTIC_INCIDENT_INDEX,
            id=incident_id,
            script={
                "lang": "painless",
                "source": (
                    "if (ctx._source.version != params.expected) { "
                    "ctx.op = 'none'; return; } "
                    "for (entry in params.changes.entrySet()) { "
                    "ctx._source[entry.getKey()] = entry.getValue(); }"
                ),
                "params": {
                    "expected": expected_version,
                    "changes": redact(changes),
                },
            },
            refresh=False,
            source=True,
        )
        if response.get("result") == "noop":
            raise RuntimeError("incident version conflict")
        if response.get("get", {}).get("_source") is not None:
            return response["get"]["_source"]
        updated = self.client.get(
            index=ELASTIC_INCIDENT_INDEX,
            id=incident_id,
        )
        return updated["_source"]

    def record_incident_occurrence(
        self, incident_id, changes, expected_version, expected_count
    ):
        response = self.client.update(
            index=ELASTIC_INCIDENT_INDEX,
            id=incident_id,
            script={
                "lang": "painless",
                "source": "if (ctx._source.version != params.version || ctx._source.occurrence_count != params.count) { ctx.op='none'; return; } for (entry in params.changes.entrySet()) { ctx._source[entry.getKey()]=entry.getValue(); }",
                "params": {
                    "version": expected_version,
                    "count": expected_count,
                    "changes": redact(changes),
                },
            },
            refresh=False,
            source=True,
        )
        if response.get("result") == "noop":
            raise RuntimeError("incident aggregation conflict; retry")
        if response.get("get", {}).get("_source") is not None:
            return response["get"]["_source"]
        return self.client.get(index=ELASTIC_INCIDENT_INDEX, id=incident_id)["_source"]

    def list_operational_incidents(self, minutes: int = 10) -> list[dict[str, Any]]:
        response = self.client.search(
            index=ELASTIC_INCIDENT_INDEX,
            query={
                "range": {
                    "last_seen": {
                        "gte": f"now-{minutes}m",
                    }
                }
            },
            sort=[
                {
                    "priority_rank": {
                        "order": "asc",
                        "missing": "_last",
                        "unmapped_type": "long",
                    }
                },
                {"last_seen": "desc"},
            ],
            size=200,
            ignore_unavailable=True,
        )
        return [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]

    def recent_incident_logs(self, incident_id: str, minutes: int = 10):
        response = self.client.search(
            index=ELASTIC_LOG_INDEX,
            query={
                "bool": {
                    "filter": [
                        {"bool": {
                            "should": [
                                {"term": {"incident_id": incident_id}},
                                {"term": {"incident_id.keyword": incident_id}},
                            ],
                            "minimum_should_match": 1,
                        }},
                        {"range": {"received_at": {"gte": f"now-{minutes}m"}}},
                    ],
                }
            },
            sort=[{"received_at": {"order": "desc", "unmapped_type": "date"}}],
            size=20,
            source=["timestamp", "received_at", "message", "host", "service", "environment", "level", "source", "synthetic", "raw.source", "raw.synthetic"],
            ignore_unavailable=True,
        )
        return [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]

    def get_recommendation(self, recommendation_id: str) -> dict[str, Any] | None:
        try:
            response = self.client.get(
                index=ELASTIC_RECOMMENDATION_INDEX,
                id=recommendation_id,
            )
        except NotFoundError:
            return None
        source = response.get("_source", {})
        return source.get("recommendation") or source.get("guidance")

    def get_remediation_execution(self, execution_id: str) -> dict[str, Any] | None:
        try:
            response = self.client.get(
                index=ELASTIC_REMEDIATION_INDEX,
                id=execution_id,
            )
        except NotFoundError:
            return None
        return response.get("_source")

    def find_remediation_executions(
        self, recommendation_id: str
    ) -> list[dict[str, Any]]:
        """한 추천에 대해 내려진 승인/거부 이력을 오래된 순으로 반환한다."""
        try:
            response = self.client.search(
                index=ELASTIC_REMEDIATION_INDEX,
                query={"match_phrase": {"recommendation_id": recommendation_id}},
                sort=[{"approved_at": "asc"}],
                size=50,
                ignore_unavailable=True,
            )
        except NotFoundError:
            return []
        # recommendation_id가 text 필드라 토큰 단위로 매칭되므로
        # 정확히 같은 id만 남긴다.
        return [
            hit["_source"]
            for hit in response["hits"]["hits"]
            if hit["_source"].get("recommendation_id") == recommendation_id
        ]

    def save_remediation_execution(self, document: dict[str, Any]) -> None:
        self.client.index(
            index=ELASTIC_REMEDIATION_INDEX,
            id=document["execution_id"],
            document=redact(document),
            op_type="create",
            refresh="wait_for",
        )

    def save_recovery_verification(self, document: dict[str, Any]) -> None:
        self._index(ELASTIC_RECOVERY_INDEX, document)

    def save_resource_guidance(self, document: dict[str, Any]) -> None:
        self.client.index(
            index=ELASTIC_RESOURCE_GUIDANCE_INDEX,
            id=document["guidance_id"],
            document=redact(document),
            refresh="wait_for",
        )

    def get_resource_guidance(self, guidance_id: str) -> dict[str, Any] | None:
        try:
            response = self.client.get(
                index=ELASTIC_RESOURCE_GUIDANCE_INDEX,
                id=guidance_id,
            )
        except NotFoundError:
            return None
        return response.get("_source")

    def save_operator_feedback(self, document: dict[str, Any]) -> None:
        self._index(ELASTIC_OPERATOR_FEEDBACK_INDEX, document)

    def remediation_history(
        self,
        script_id: str,
    ) -> dict[str, int]:
        try:
            response = self.client.search(
                index=ELASTIC_REMEDIATION_INDEX,
                query={"bool": {"filter": [{"term": {"script_id.keyword": script_id}}], "must_not": [{"term": {"result.execution_mode.keyword": "simulation"}}]}},
                size=0,
                aggs={"by_status": {"terms": {"field": "result.status.keyword"}}},
                ignore_unavailable=True,
            )
        except NotFoundError:
            return {"success": 0, "failure": 0}

        buckets = (
            response.get("aggregations", {}).get("by_status", {}).get("buckets", [])
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
                    {"term": {"error_code": error_code}},
                    {"match": {"summary": message}},
                    {"match": {"root_cause": message}},
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

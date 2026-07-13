from typing import Any

from config import (
    ELASTIC_DIAGNOSIS_INDEX,
    ELASTIC_INCIDENT_CASES_INDEX,
    ELASTIC_LOG_INDEX,
    ELASTIC_RECOMMENDATION_INDEX,
    ELASTIC_REMEDIATION_INDEX,
)
from elastic.client import get_client
from ports.case_searcher import CaseSearcher
from ports.log_repository import LogRepository


class ElasticLogRepository(LogRepository):

    def __init__(self) -> None:
        self.client = get_client()

    def save_log(
        self,
        document: dict[str, Any],
    ) -> None:
        self.client.index(
            index=ELASTIC_LOG_INDEX,
            document=document,
        )

    def save_diagnosis(
        self,
        document: dict[str, Any],
    ) -> None:
        self.client.index(
            index=ELASTIC_DIAGNOSIS_INDEX,
            document=document,
        )

    def save_recommendation(
        self,
        document: dict[str, Any],
    ) -> None:
        self.client.index(
            index=ELASTIC_RECOMMENDATION_INDEX,
            document=document,
        )

    def save_remediation(
        self,
        document: dict[str, Any],
    ) -> None:
        self.client.index(
            index=ELASTIC_REMEDIATION_INDEX,
            document=document,
        )


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

        return [
            {
                **hit["_source"],
                "score": hit["_score"],
            }
            for hit in response["hits"]["hits"]
        ]

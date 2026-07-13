from typing import Any

from elasticsearch import Elasticsearch

from config import ELASTICSEARCH_URL


es = Elasticsearch(ELASTICSEARCH_URL)


def check_connection() -> bool:
    try:
        return bool(es.ping())
    except Exception:
        return False


def save_document(
    index: str,
    document: dict[str, Any],
) -> dict[str, Any]:
    response = es.index(
        index=index,
        document=document,
    )

    return {
        "index": response.get("_index"),
        "id": response.get("_id"),
        "result": response.get("result"),
    }


def find_incident_cases(
    error_code: str,
    message: str,
    size: int = 3,
) -> list[dict[str, Any]]:
    query = {
        "bool": {
            "should": [
                {
                    "term": {
                        "error_code.keyword": error_code
                    }
                },
                {
                    "match": {
                        "summary": message
                    }
                },
                {
                    "match": {
                        "root_cause": message
                    }
                },
            ],
            "minimum_should_match": 1,
        }
    }

    response = es.search(
        index="incident-cases",
        query=query,
        size=size,
    )

    return [
        hit["_source"]
        for hit in response["hits"]["hits"]
    ]

from typing import Any

from qdrant_client.models import FieldCondition, Filter, MatchValue

from config import QDRANT_COLLECTION
from ports.case_searcher import CaseSearcher
from qdrant.client import encode, get_client


class QdrantCaseSearcher(CaseSearcher):

    def search(
        self,
        error_code: str,
        message: str,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        client = get_client()
        query_vector = encode(
            f"{error_code} {message}"
        )

        results = client.query_points(
            collection_name=QDRANT_COLLECTION,
            query=query_vector,
            query_filter=Filter(must=[FieldCondition(
                key="error_code",
                match=MatchValue(value=error_code),
            )]),
            limit=limit,
            with_payload=True,
        ).points

        return [
            {
                **point.payload,
                "score": point.score,
            }
            for point in results
        ]

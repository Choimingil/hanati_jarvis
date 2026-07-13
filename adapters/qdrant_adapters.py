from typing import Any

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
            limit=limit,
        ).points

        return [
            {
                **point.payload,
                "score": point.score,
            }
            for point in results
        ]

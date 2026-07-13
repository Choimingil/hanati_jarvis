from typing import Any

from ports.case_searcher import CaseSearcher


class HybridCaseSearcher(CaseSearcher):
    """Qdrant(벡터 유사도)와 Elasticsearch(키워드) 검색 결과를 합쳐서
    반환한다. 두 백엔드에 학습된 과거 대응 사례를 모두 추천 근거로
    사용한다는 서비스 방향성에 맞춘 구현.
    """

    def __init__(
        self,
        vector_searcher: CaseSearcher,
        keyword_searcher: CaseSearcher,
    ) -> None:
        self.vector_searcher = vector_searcher
        self.keyword_searcher = keyword_searcher

    def search(
        self,
        error_code: str,
        message: str,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        vector_results = self.vector_searcher.search(
            error_code=error_code,
            message=message,
            limit=limit,
        )
        keyword_results = self.keyword_searcher.search(
            error_code=error_code,
            message=message,
            limit=limit,
        )

        merged: dict[Any, dict[str, Any]] = {}

        for case in [*vector_results, *keyword_results]:
            key = case.get(
                "incident_id", id(case)
            )
            existing = merged.get(key)

            if existing is None or case.get(
                "score", 0
            ) > existing.get("score", 0):
                merged[key] = case

        ranked = sorted(
            merged.values(),
            key=lambda case: case.get("score", 0),
            reverse=True,
        )

        return ranked[:limit]

"""incident_cases 컬렉션에 테스트용 과거 사례를 시딩한다.

실행: python -m qdrant.seed
"""

from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
)

from config import (
    EMBEDDING_VECTOR_SIZE,
    QDRANT_COLLECTION,
)
from incident_cases import INCIDENT_CASES
from qdrant.client import encode, get_client


def seed() -> None:
    client = get_client()

    if client.collection_exists(QDRANT_COLLECTION):
        client.delete_collection(
            collection_name=QDRANT_COLLECTION
        )

    client.create_collection(
        collection_name=QDRANT_COLLECTION,
        vectors_config=VectorParams(
            size=EMBEDDING_VECTOR_SIZE,
            distance=Distance.COSINE,
        ),
    )

    points = [
        PointStruct(
            id=idx,
            vector=encode(
                f"{case['error_code']} "
                f"{case['summary']} "
                f"{case['root_cause']}"
            ),
            payload=case,
        )
        for idx, case in enumerate(INCIDENT_CASES)
    ]

    client.upload_points(
        collection_name=QDRANT_COLLECTION,
        points=points,
    )

    print(
        f"[QDRANT SEED] {len(points)}건의 "
        f"incident case를 '{QDRANT_COLLECTION}' "
        f"컬렉션에 업로드했습니다."
    )


if __name__ == "__main__":
    seed()

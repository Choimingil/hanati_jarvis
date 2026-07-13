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
from qdrant.client import encode, get_client


INCIDENT_CASES = [
    {
        "incident_id": "TEST-001",
        "error_code": "DISK_FULL",
        "summary": "로그 파일 증가로 디스크 부족",
        "root_cause": "오래된 로그 미정리",
        "resolution": "오래된 로그 압축",
    },
    {
        "incident_id": "TEST-002",
        "error_code": "DISK_FULL",
        "summary": "업로드 디렉토리 용량 초과로 디스크 풀",
        "root_cause": "대용량 업로드 파일 미삭제",
        "resolution": "오래된 업로드 파일 정리 및 보관 정책 적용",
    },
    {
        "incident_id": "TEST-003",
        "error_code": "ORA-28040",
        "summary": "JDBC 드라이버 버전 불일치로 인증 실패",
        "root_cause": "구버전 JDBC 드라이버 사용",
        "resolution": "JDBC 드라이버 최신 버전으로 업데이트",
    },
    {
        "incident_id": "TEST-004",
        "error_code": "ORA-28040",
        "summary": "sqlnet.ora 설정 오류로 접속 거부",
        "root_cause": "SQLNET.ALLOWED_LOGON_VERSION_SERVER 설정 누락",
        "resolution": "sqlnet.ora 설정 수정 후 리스너 재기동",
    },
]


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

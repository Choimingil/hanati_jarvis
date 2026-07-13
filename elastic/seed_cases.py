"""incident-cases 인덱스에 테스트용 과거 사례를 시딩한다.

Qdrant의 `qdrant/seed.py`와 동일한 데이터(incident_cases.py)를 사용해서
두 백엔드가 같은 과거 대응 사례를 알고 있도록 맞춘다.

실행: python -m elastic.seed_cases
"""

from config import ELASTIC_INCIDENT_CASES_INDEX
from elastic.client import get_client
from incident_cases import INCIDENT_CASES


def seed() -> None:
    client = get_client()

    if client.indices.exists(
        index=ELASTIC_INCIDENT_CASES_INDEX
    ):
        client.indices.delete(
            index=ELASTIC_INCIDENT_CASES_INDEX
        )

    client.indices.create(
        index=ELASTIC_INCIDENT_CASES_INDEX,
        body={
            "mappings": {
                "properties": {
                    "incident_id": {
                        "type": "keyword"
                    },
                    "error_code": {
                        "type": "keyword"
                    },
                    "summary": {"type": "text"},
                    "root_cause": {"type": "text"},
                    "resolution": {"type": "text"},
                }
            }
        },
    )

    for case in INCIDENT_CASES:
        client.index(
            index=ELASTIC_INCIDENT_CASES_INDEX,
            document=case,
        )

    client.indices.refresh(
        index=ELASTIC_INCIDENT_CASES_INDEX
    )

    print(
        f"[ELASTIC SEED] {len(INCIDENT_CASES)}건의 "
        f"incident case를 "
        f"'{ELASTIC_INCIDENT_CASES_INDEX}' "
        f"인덱스에 업로드했습니다."
    )


if __name__ == "__main__":
    seed()

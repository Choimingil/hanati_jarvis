"""log_generator가 발생시키는 각 장애 시나리오의 실제 에러 로그와, 그
에러에 대응하는 진단/조치 스크립트 정보(config.ERROR_RULES)를 묶어서
Qdrant + Elasticsearch의 incident-case 저장소에 학습(색인)시킨다.

qdrant/seed.py, elastic/seed_cases.py는 incident_cases.py에 손으로 쓴
테스트 사례 4건만 넣는다. 이 스크립트는 log_generator/registry.py에 등록된
6개 시나리오 전부(+ 시나리오가 없는 기존 ORA-28040)를, config.ERROR_RULES에
정의된 실제 진단/조치 스크립트 id와 함께 넣어서 case_searcher가 실행
가능한 스크립트 근거를 갖고 추천하게 한다.

기존 컬렉션/인덱스를 지우지 않고 incident_id 기반으로 upsert한다
(재실행 가능, qdrant/seed.py가 만든 TEST-* 사례와 안 겹침).

실행: python scripts/seed_incident_knowledge.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

LOG_GENERATOR_DIR = REPO_ROOT / "log_generator"
if str(LOG_GENERATOR_DIR) not in sys.path:
    sys.path.insert(0, str(LOG_GENERATOR_DIR))

from qdrant_client.models import (  # noqa: E402
    Distance,
    PointStruct,
    VectorParams,
)

from config import (  # noqa: E402
    ELASTIC_INCIDENT_CASES_INDEX,
    EMBEDDING_VECTOR_SIZE,
    ERROR_RULES,
    QDRANT_COLLECTION,
    SCRIPT_DESCRIPTIONS,
)
from elastic.client import get_client as get_es_client  # noqa: E402
from logger.log_constants import LogLevel  # noqa: E402
from qdrant.client import encode  # noqa: E402
from qdrant.client import get_client as get_qdrant_client  # noqa: E402
from registry import SCENARIO_REGISTRY  # noqa: E402

# qdrant/seed.py가 만드는 TEST-* 사례는 정수 id 0~3을 쓴다. 이 스크립트가
# 만드는 사례는 그 뒤로 안전하게 떨어지도록 오프셋을 둔다.
QDRANT_ID_OFFSET = 1000


def _script_text(script_ids: list[str]) -> str:
    return ", ".join(
        SCRIPT_DESCRIPTIONS.get(script_id, script_id)
        for script_id in script_ids
    )


def _scenario_narrative(error_code: str) -> tuple[str, str]:
    """error_code에 매핑된 log_generator 시나리오에서 실제 ERROR 메시지와,
    그 직전 WARN 경고들을 이어붙인 문자열을 뽑는다. 매핑된 시나리오가
    없으면(ORA-28040처럼 log_generator가 만들지 않는 코드) 빈 문자열 반환."""
    for _key, (scenario_cls, _label, mapped_code) in (
        SCENARIO_REGISTRY.items()
    ):
        if mapped_code != error_code:
            continue

        events = scenario_cls().events()
        warnings = [
            e.message for e in events if e.level == LogLevel.WARN
        ]
        errors = [
            e.message for e in events if e.level == LogLevel.ERROR
        ]
        summary = errors[0] if errors else ""
        root_cause = (
            " → ".join(warnings) if warnings else summary
        )
        return summary, root_cause

    return "", ""


def build_cases() -> list[dict]:
    cases = []

    for error_code, rule in ERROR_RULES.items():
        summary, root_cause = _scenario_narrative(error_code)

        if not summary:
            summary = f"{error_code} 발생"
        if not root_cause:
            root_cause = (
                _script_text(rule["diagnostic_scripts"])
                + " 점검으로 확인 가능한 원인"
            )

        cases.append({
            "incident_id": f"LOGGEN-{error_code}",
            "error_code": error_code,
            "summary": summary,
            "root_cause": root_cause,
            "resolution": _script_text(
                rule["remediation_candidates"]
            ),
            "diagnostic_scripts": rule["diagnostic_scripts"],
            "remediation_candidates": rule[
                "remediation_candidates"
            ],
        })

    return cases


def seed_qdrant(cases: list[dict]) -> None:
    client = get_qdrant_client()

    if not client.collection_exists(QDRANT_COLLECTION):
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(
                size=EMBEDDING_VECTOR_SIZE,
                distance=Distance.COSINE,
            ),
        )

    points = [
        PointStruct(
            id=QDRANT_ID_OFFSET + idx,
            vector=encode(
                f"{case['error_code']} {case['summary']} "
                f"{case['root_cause']}"
            ),
            payload=case,
        )
        for idx, case in enumerate(cases)
    ]

    client.upsert(
        collection_name=QDRANT_COLLECTION, points=points
    )

    print(
        f"[QDRANT] {len(points)}건의 log_generator 에러 사례를 "
        f"'{QDRANT_COLLECTION}' 컬렉션에 학습시켰습니다."
    )


def seed_elasticsearch(cases: list[dict]) -> None:
    client = get_es_client()

    if not client.indices.exists(
        index=ELASTIC_INCIDENT_CASES_INDEX
    ):
        client.indices.create(
            index=ELASTIC_INCIDENT_CASES_INDEX,
            mappings={
                "properties": {
                    "incident_id": {"type": "keyword"},
                    "error_code": {"type": "keyword"},
                    "summary": {"type": "text"},
                    "root_cause": {"type": "text"},
                    "resolution": {"type": "text"},
                    "diagnostic_scripts": {
                        "type": "keyword"
                    },
                    "remediation_candidates": {
                        "type": "keyword"
                    },
                }
            },
        )

    for case in cases:
        client.index(
            index=ELASTIC_INCIDENT_CASES_INDEX,
            id=case["incident_id"],
            document=case,
        )

    client.indices.refresh(
        index=ELASTIC_INCIDENT_CASES_INDEX
    )

    print(
        f"[ELASTIC] {len(cases)}건의 log_generator 에러 사례를 "
        f"'{ELASTIC_INCIDENT_CASES_INDEX}' 인덱스에 학습시켰습니다."
    )


def main() -> None:
    cases = build_cases()
    seed_qdrant(cases)
    seed_elasticsearch(cases)


if __name__ == "__main__":
    main()

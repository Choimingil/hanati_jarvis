# 아키텍처 / 클래스 역할 정리

이 문서는 현재 저장소에 있는 코드가 어떤 구조로 되어 있고, 각 파일/클래스가
무슨 역할을 하는지 정리한 참고 문서다. 사용법은 [README.md](README.md)를 보고,
"이 코드가 지금 어떻게 동작하는가"를 파악할 때는 이 문서를 본다.

## 1. 전체 흐름

```
fluentbit / 외부 클라이언트
        │  POST /api/v1/logs
        ▼
routes/log_routes.py (log_blueprint)
        │
        ▼
dependencies.py 가 조립해 둔 LogProcessor 인스턴스
        │
        ▼
log_processor.py : LogProcessor.process()
    1) log_normalizer.normalize_log()      — 로그 형태 정규화
    2) error_detector.detect_error_code()  — 에러 코드 판별
    3) script_runner.run_script()          — 진단 스크립트 실행 (ERROR_RULES 기반)
    4) case_searcher.search()              — 과거 유사 사례 검색 (ports/CaseSearcher, Qdrant/Elasticsearch에 학습된 데이터 기반)
    5) recommendation_generator.generate() — 대응 방안 생성 (ports/RecommendationGenerator)
    6) repository.save_*()                 — 로그/진단/추천 결과 저장 (ports/LogRepository)
        │
        ▼  (운영자가 recommended_actions 중 하나를 선택)
        │  POST /api/v1/remediations/approve
        ▼
routes/remediation_routes.py (remediation_blueprint)
    - ERROR_RULES의 remediation_candidates에 있는 script_id인지 검증(allowlist)
    - script_runner.run_script()로 실제 조치 스크립트 실행
    - repository.save_remediation()으로 실행 결과 저장
```

`case_searcher`, `recommendation_generator`, `repository` 세 가지는 모두
`ports/`에 정의된 인터페이스이고, 실제 구현체는 `adapters/`에 있다.
`dependencies.py`가 환경변수를 보고 어떤 구현체를 주입할지 결정한다
(mock ↔ 실제 백엔드 스위치).

이 전체 흐름(에러 탐지 → 진단 → **Qdrant/Elasticsearch에 학습된 과거 대응
사례 기반 추천** → 운영자 승인 → 스크립트 실행)이 서비스가 원래 지향하는
AIOps 대응 루프다. 자세한 서비스 관점 설명과 실제 테스트 절차는
[TESTING.md](TESTING.md) 참고.

## 2. 애플리케이션 진입점 / 조립

| 파일 | 역할 |
|---|---|
| `app.py` | Flask 앱 팩토리(`create_app`). `log_blueprint`를 등록하고 `/health`를 제공. `python app.py`로 직접 실행 시 `API_HOST`/`API_PORT`로 서빙. |
| `config.py` | 모든 설정값을 환경변수 기반으로 모아두는 곳. API 포트, 진단 스크립트 경로(`DIAGNOSTIC_SCRIPTS`), 에러 코드별 대응 규칙(`ERROR_RULES`), 백엔드 스위치(`CASE_SEARCHER_BACKEND`, `LOG_REPOSITORY_BACKEND`), Qdrant/Elasticsearch 접속 정보를 정의. |
| `dependencies.py` | 의존성 조립(수동 DI). `LOG_REPOSITORY_BACKEND`/`CASE_SEARCHER_BACKEND` 값에 따라 mock 또는 실제 어댑터를 골라 `LogProcessor`에 주입하고, 모듈 레벨 싱글턴 `log_processor`를 만든다. |

## 3. 도메인 로직 (백엔드에 의존하지 않는 순수 로직)

| 파일 | 클래스/함수 | 역할 |
|---|---|---|
| `log_processor.py` | `LogProcessor` | 로그 1건을 받아 정규화 → 에러 판별 → 진단 → 사례 검색 → 추천 생성 → 저장까지 전체 파이프라인을 조율하는 핵심 클래스. 포트 3종(`LogRepository`, `CaseSearcher`, `RecommendationGenerator`)만 알고 실제 구현은 모른다. |
| `log_normalizer.py` | `normalize_log()` | 다양한 형태로 들어오는 원본 로그 딕셔너리를 표준 스키마(`timestamp`, `level`, `message`, `host`, `service`, `environment`, `raw`)로 변환. |
| `error_detector.py` | `detect_error_code()` | 로그 메시지를 정규식(`ERROR_PATTERNS`)으로 검사해 `ORA-28040`, `DISK_FULL` 같은 에러 코드를 판별. |
| `script_runner.py` | `run_script()` | `config.DIAGNOSTIC_SCRIPTS`/`REMEDIATION_SCRIPTS` 같은 allowlist에 있는 쉘 스크립트만 subprocess로 실행. 타임아웃/실행권한/allowlist 미포함을 각각 다른 상태로 반환. `routes/remediation_routes.py`가 운영자 승인 후 조치 스크립트를 실행할 때도 동일 함수를 재사용한다. |
| `utils/time_utils.py` | `now_iso()` | UTC 기준 ISO8601 타임스탬프 생성 헬퍼. |
| `incident_cases.py` | `INCIDENT_CASES` | Qdrant(`qdrant/seed.py`)와 Elasticsearch(`elastic/seed_cases.py`)에 동일하게 시딩하는 과거 장애 대응 사례 fixture. 두 백엔드가 같은 "학습 데이터"를 갖도록 공유. |

## 4. 포트 (인터페이스)

`ports/` 아래 3개 추상 클래스가 `LogProcessor`가 의존하는 계약이다.

| 파일 | 인터페이스 | 메서드 |
|---|---|---|
| `ports/log_repository.py` | `LogRepository` | `save_log`, `save_diagnosis`, `save_recommendation`, `save_remediation` |
| `ports/case_searcher.py` | `CaseSearcher` | `search(error_code, message, limit)` → 과거 유사 사례 리스트 |
| `ports/recommendation_generator.py` | `RecommendationGenerator` | `generate(error_code, message, diagnosis_results, past_cases, remediation_candidates)` → 추천 결과 dict |

## 5. 어댑터 (포트 구현체)

| 파일 | 클래스 | 구현 대상 | 특징 |
|---|---|---|---|
| `adapters/mock_adapters.py` | `MockLogRepository` | `LogRepository` | 메모리 리스트에 저장 + `print`로 로그만 남김. 테스트/로컬 기본값. |
| | `MockCaseSearcher` | `CaseSearcher` | `DISK_FULL`일 때만 하드코딩된 사례 1건 반환, 그 외엔 빈 리스트. |
| | `MockRecommendationGenerator` | `RecommendationGenerator` | LLM 호출 없이 입력값을 그대로 조립한 고정 포맷 응답 반환. |
| `adapters/qdrant_adapters.py` | `QdrantCaseSearcher` | `CaseSearcher` | `error_code + message`를 임베딩해 Qdrant `incident_cases` 컬렉션에서 벡터(의미) 검색. `CASE_SEARCHER_BACKEND=qdrant`일 때 사용. |
| `adapters/elastic_adapters.py` | `ElasticLogRepository` | `LogRepository` | `save_log`/`save_diagnosis`/`save_recommendation`/`save_remediation`을 각각 Elasticsearch 인덱스(`application-logs`, `application-diagnoses`, `application-recommendations`, `application-remediations`)에 저장. `LOG_REPOSITORY_BACKEND=elastic`일 때 사용. |
| | `ElasticCaseSearcher` | `CaseSearcher` | `incident-cases` 인덱스에서 `error_code` term + `summary`/`root_cause` 키워드 매칭으로 과거 사례 검색. `CASE_SEARCHER_BACKEND=elastic`일 때 사용. |
| `adapters/hybrid_adapters.py` | `HybridCaseSearcher` | `CaseSearcher` | `QdrantCaseSearcher`(벡터)와 `ElasticCaseSearcher`(키워드)를 둘 다 호출해서 `incident_id` 기준으로 병합 후 score순 정렬. "Qdrant와 Elasticsearch 둘 다 학습된 내용을 근거로 추천"하는 서비스 방향성을 그대로 구현한 것. `CASE_SEARCHER_BACKEND=hybrid`일 때 사용. |

## 6. Qdrant 지원 모듈 (`qdrant/`)

| 파일 | 역할 |
|---|---|
| `qdrant/client.py` | `get_client()` (Qdrant 클라이언트), `get_embedding_model()` (`BAAI/bge-m3` `SentenceTransformer`), `encode()` — 둘 다 `lru_cache`로 lazy singleton. `QdrantCaseSearcher`와 `seed.py`가 공용으로 사용. |
| `qdrant/seed.py` | `incident_cases.py`의 `INCIDENT_CASES`를 임베딩해 `incident_cases` 컬렉션에 업로드하는 시딩 스크립트. `python -m qdrant.seed`로 실행. |
| `qdrant/qdrant_data/` | 로컬 파일 기반 Qdrant 저장소(자동 생성, git에는 커밋되지 않음). |

## 7. Elasticsearch 지원 모듈 (`elastic/`)

팀원이 추가한 Elasticsearch 실습/파이프라인 스크립트 모음. `adapters/elastic_adapters.py`가
`elastic/client.py`만 가져다 쓰고, 나머지는 개발/운영 중 수동으로 실행하는 보조 스크립트다.

| 파일 | 역할 |
|---|---|
| `elastic/client.py` | `get_client()` — `config.py`의 `ELASTICSEARCH_URL`/`ELASTICSEARCH_USER`/`ELASTICSEARCH_PASSWORD`/`ELASTICSEARCH_VERIFY_CERTS`로 `Elasticsearch` 클라이언트 생성. |
| `elastic/mapping.py` | `create_log_index()` — `application-logs` 인덱스를 명시적 매핑(timestamp/service/level/message/user_id/request_url/method/error/host)으로 생성. 수동 실행용. |
| `elastic/seed_cases.py` | `incident_cases.py`의 `INCIDENT_CASES`를 `incident-cases` 인덱스에 시딩. `ElasticCaseSearcher`/`HybridCaseSearcher`가 검색할 데이터를 채운다. `python -m elastic.seed_cases`로 실행. |
| `elastic/insert_log.py` | `insert_log(log)` — 단건 로그 저장 예제/수동 테스트 스크립트. |
| `elastic/search_log.py` | `get_all_logs()`, `search_error_logs()`, `search_service()`, `search_keyword()` — 저장된 로그를 조회/검색하는 수동 테스트 스크립트. |
| `elastic/bulk_insert.py` | `elastic/log_generator.py`의 `generate_log()`로 만든 더미 로그 1000건을 `bulk()`로 적재하는 부하/샘플 데이터 스크립트. |
| `elastic/log_generator.py` | `generate_log()` — 랜덤 서비스/레벨/메시지 조합의 더미 로그 1건을 생성 (아래 8번 `log_generator/`와는 별개의, ES 예제용 미니 제너레이터). |
| `elastic/main.py` | `main()` — Elasticsearch 연결 확인용 스모크 테스트(`es.info()` 호출). |
| `elastic/search_test.py` | 전체 로그를 조회해 출력하는 가장 단순한 조회 스크립트. |

> 이 문서를 작성한 시점 기준으로 로컬에 실행 중인 Elasticsearch가 없어
> (`localhost:9200` connection refused) 실제 저장/조회 결과까지는 검증하지
> 못했다. import 경로 수정과 mock ↔ elastic 스위치, 연결 실패 시 에러 처리는
> 확인됨. 자세한 내용은 [README.md](README.md)의 "Elasticsearch 연동" 절 참고.

## 8. 로그 생성기 (`log_generator/`) — 별도 CLI 도구

Flask 앱과는 독립적으로, 정상/장애 로그를 합성해 파일에 계속 써주는
시뮬레이터. fluentbit가 이 파일을 tail 해서 `/api/v1/logs`로 전달하는
시나리오를 테스트할 때 쓴다. `log_generator/` 디렉토리를 CWD로 두고
`python main.py`로 실행한다 (내부 import가 `logger.xxx`, `scenario.xxx`,
`system.xxx` 형태의 스크립트 기준 상대 경로이기 때문).

> **fluentbit 연동 수정 (2026-07-13)**: 원래 `main.py`는
> `DefaultFormatter`(사람이 읽는 텍스트)로 `log_generator/app.log`에 썼는데,
> fluentbit(`fluentbit/fluent-bit.conf`)는 `fluentbit/application.log`를
> JSON 파서로 tail하고 있어서 경로도 포맷도 맞지 않아 실제로는 전혀
> 연결되어 있지 않았다. `JsonFormatter`(신규)를 추가하고 출력 경로를
> `fluentbit/application.log`(이 파일 위치 기준 절대경로)로 바꿔서 실제
> fluentbit → 백엔드 파이프라인이 동작하도록 고쳤다. 3개 프로세스(백엔드,
> fluent-bit, `log_generator/main.py`)를 동시에 띄워서 `DISK_FULL` 시나리오가
> fluentbit를 거쳐 `recommended` 상태까지 도착하는 것을 직접 확인함. 자세한
> 절차는 [TESTING.md](TESTING.md) 6번 참고.

| 파일 | 클래스 | 역할 |
|---|---|---|
| `log_generator/main.py` | — | 엔트리 포인트. `SystemInfo`, 정상 로그 패턴, 장애 시나리오 목록(확률 가중치 포함)을 조립해 `ScenarioRunner.run()`을 무한 루프로 실행. `FLUENTBIT_LOG_PATH`(=`fluentbit/application.log`, 이 파일 기준 절대경로)에 `JsonFormatter`로 기록한다. |
| `log_generator/system/system_info.py` | `SystemInfo` | 호스트명/IP/OS/리소스/서비스명 등 로그에 찍히는 시스템 메타데이터. |
| | `NormalLogPattern` | 평상시 반복 출력할 정상 로그 메시지 목록과 간격(`delay`). |
| | `FailureBehavior` | 장애가 발생할 확률(`probability`), 정상 로그 후 장애를 트리거하기까지의 대기시간(`trigger_after`), 사용할 시나리오 목록. |
| | `FailureScenarioConfig` | 시나리오 하나 + 해당 시나리오가 뽑힐 가중치(`probability`). |
| `log_generator/scenario/scenario.py` | `Scenario` (ABC) | 모든 장애 시나리오의 베이스 클래스. `events()`를 구현해야 함. |
| `log_generator/scenario/log_event.py` | `LogEvent` | 로그 한 줄에 해당하는 데이터(딜레이, 레벨, 메시지, 이후 시스템 상태, 발생 소스, 타임스탬프). |
| `log_generator/scenario/scenario_runner.py` | `ScenarioRunner` | 정상 로그를 순환 출력하다가, 설정된 확률/대기시간에 따라 장애 시나리오를 하나 골라 이벤트를 순서대로 `writer`에 기록. 시나리오가 여러 개면 `probability` 가중치로 랜덤 선택(`_select_scenario`). |
| `log_generator/scenario/dns_failure_scenario.py` | `DNSFailureScenario` | DNS 조회 실패 → 서비스 endpoint 해석 실패 → circuit breaker open 순서의 5단계 이벤트. |
| `log_generator/scenario/disk_full_scenario.py` | `DiskFullScenario` | 디스크 사용량 90% 초과 → 로그 로테이션 실패 → `No space left on device` → 쓰기 불가 → read-only 전환. |
| `log_generator/scenario/database_connection_failure_scenario.py` | `DatabaseConnectionFailureScenario` | DB 커넥션 타임아웃 → 재시도 → 연결 실패 → 쿼리 실행 불가 → 요청 처리 중단. |
| `log_generator/scenario/external_api_failure_scenario.py` | `ExternalAPIFailureScenario` | 외부 API 응답 지연 → 재시도 → HTTP 503 → 결제 서비스 불가 → 트랜잭션 취소. |
| `log_generator/scenario/memory_leak_scenario.py` | `MemoryLeakScenario` | 메모리 사용량 증가 → 힙 85% 초과 → GC 빈발 → OOM → 프로세스 종료. |
| `log_generator/scenario/redis_cache_failure_scenario.py` | `RedisFailureScenario` | Redis 지연 → 캐시 미스 증가 → Redis 연결 끊김 → DB로 폴백 → DB 과부하. |
| `log_generator/logger/log_formatter.py` | `LogFormatter` (ABC) | 로그 포맷터 인터페이스. |
| `log_generator/logger/default_formatter.py` | `DefaultFormatter` | `[시간] [레벨] [호스트] [상태] 메시지` 형태의 사람이 읽기 좋은 텍스트 포맷 구현. 현재 `main.py`는 이 대신 `JsonFormatter`를 사용한다(사람이 로컬에서 눈으로 확인할 때는 여전히 유용해서 남겨둠). |
| `log_generator/logger/json_formatter.py` | `JsonFormatter` | fluentbit의 `app_json` 파서와 `log_normalizer.py`가 기대하는 `timestamp`/`level`/`message`/`host`/`service` 키를 가진 한 줄짜리 JSON을 생성. `main.py`가 사용하는 기본 포맷터. |
| `log_generator/logger/log_writer.py` | `LogWriter` (ABC) | 로그 출력(쓰기) 인터페이스. |
| `log_generator/logger/file_writer.py` | `FileWriter` | 파일에 로그를 append. 스레드 락으로 동시 쓰기 보호. |
| `log_generator/logger/log_constants.py` | `LogLevel`, `SystemStatus` | 로그 레벨(`DEBUG`~`CRITICAL`)과 시스템 상태(`HEALTHY`/`DEGRADED`/`FAILED`/`RECOVERING`) 상수. |
| `loggenerator_example.py` | — | 저장소 루트에서 `log_generator/main.py`를 서브프로세스로 실행하는 예시 러너 (README의 "log generator 사용법"에서 언급). |

## 9. HTTP 라우트

| 파일 | 역할 |
|---|---|
| `routes/log_routes.py` | `log_blueprint` — `POST /api/v1/logs`. 단건/배열 JSON을 받아 각각 `dependencies.log_processor.process()`로 전달하고 결과 리스트를 반환 (탐지 → 진단 → 추천까지). |
| `routes/remediation_routes.py` | `remediation_blueprint` — `POST /api/v1/remediations/approve`. 운영자가 추천된 `script_id`/`error_code`/`approved_by`를 보내면, `ERROR_RULES`의 `remediation_candidates`에 있는 스크립트인지 검증한 뒤 `script_runner.run_script()`로 실행하고 `dependencies.repository.save_remediation()`으로 결과를 저장한다. **이전에는 `app.py`에 등록되지 않고 삭제된 `elastic_repository.py`를 참조해 로드조차 안 되던 미사용 코드였는데, 이번에 `dependencies.repository`를 쓰도록 고치고 `app.py`에 등록해서 정상 동작하도록 복구했다.** (부수적으로 `run_script()`가 절대 반환하지 않는 `"executed"` 상태와 비교하던 상태 코드 버그도 `"success"`로 수정.) |

두 블루프린트 모두 `app.py`에 등록되어 있고, 이제 "탐지 → 진단 → 추천 →
운영자 승인 → 스크립트 실행"까지 전체 루프가 실제로 동작한다.

## 10. 이전 이슈: `diagnosis_service.py` / `recommendation_service.py`

`ports`/`adapters` 구조가 도입되기 전에 작성된 것으로 보이는 중복 구현체였다
(로그 진단·추천 로직을 `log_processor.py`와 별개로 직접 `elastic_repository`를
호출해 구현). `app.py`가 등록하는 블루프린트에서도, `dependencies.py`에서도
전혀 참조되지 않아 실제로는 한 번도 실행되지 않는 죽은 코드였고, 참조하던
`elastic_repository.py`도 최초 커밋부터 `config.ELASTICSEARCH_URL`(정의된 적
없음)을 import해서 원래도 로드 불가능했다. 두 파일 모두 삭제했다 — 동일한
역할은 `log_processor.py` + `ports/adapters`가 이미 수행하고 있다.

## 11. 요약: 백엔드 스위치 가능한 지점

| 포트 | 기본(mock) | 대안 | 스위치 환경변수 |
|---|---|---|---|
| `CaseSearcher` | `MockCaseSearcher` | `QdrantCaseSearcher` / `ElasticCaseSearcher` / `HybridCaseSearcher`(둘 다) | `CASE_SEARCHER_BACKEND=qdrant`\|`elastic`\|`hybrid` |
| `LogRepository` | `MockLogRepository` | `ElasticLogRepository` | `LOG_REPOSITORY_BACKEND=elastic` |
| `RecommendationGenerator` | `MockRecommendationGenerator` | (아직 없음, LLM 연동은 별도 진행 중 — README "구현 방법" 참고) | — |

운영자 승인 → 스크립트 실행(`routes/remediation_routes.py`)은 백엔드 스위치와
무관하게 항상 `script_runner.run_script()` + 현재 주입된 `repository`를
사용한다. 실제로 눌러보면서 확인하는 절차는 [TESTING.md](TESTING.md) 참고.

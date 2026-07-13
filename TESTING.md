# 실제 서비스 테스트 가이드

이 문서는 "에러 발생 → 진단 → **Qdrant/Elasticsearch에 학습된 과거 사례
기반 추천** → 운영자 승인 → 스크립트 실행"이라는 서비스 목표대로 지금
코드가 실제로 동작하는지 확인하는 절차를 정리한다. 코드 구조 자체가
궁금하면 [ARCHITECTURE.md](ARCHITECTURE.md)를 먼저 보는 걸 추천한다.

> **범위 안내**: 추천 문구를 생성하는 `recommendation_generator`(LLM 연동)는
> 다른 팀원이 별도로 작업 중이라 이 문서/이번 작업에서는 다루지 않는다.
> 지금은 `MockRecommendationGenerator`가 고정 포맷으로 응답한다. 이 문서는
> 그 앞뒤 — 탐지/진단/**과거 사례 검색(Qdrant+Elasticsearch)**/운영자
> 승인/스크립트 실행 — 이 실제로 동작하는지에 집중한다.

## 0. 전체 그림

```
에러 로그 발생
  → POST /api/v1/logs
  → 에러 코드 판별 (ORA-28040, DISK_FULL)
  → 진단 스크립트 실행 (test-runbooks/check_*.sh)
  → 과거 유사 사례 검색 (Qdrant 벡터 검색 + Elasticsearch 키워드 검색)
  → 추천안 응답 (recommended_actions, past_cases)
  → 운영자가 추천안 중 하나 선택
  → POST /api/v1/remediations/approve
  → 조치 스크립트 실행 (test-runbooks/compress_old_logs.sh 등)
```

## 1. 사전 준비

```bash
cd hanati_jarvis
python3 -m venv venv          # 이미 있다면 생략
source venv/bin/activate
pip install -r requirements.txt
```

## 2. 가장 빠른 스모크 테스트 (외부 의존성 없음, mock 모드)

아무 환경변수도 지정하지 않으면 `CaseSearcher`/`LogRepository` 둘 다 mock으로
동작한다. Qdrant, Elasticsearch 서버가 없어도 전체 API 흐름(탐지 → 진단 →
추천 → 승인 → 실행)을 바로 확인할 수 있다.

```bash
python app.py
# -> http://0.0.0.0:8080 에서 서빙
```

다른 터미널에서:

```bash
# 헬스체크
curl -s http://localhost:8080/health | python3 -m json.tool

# 1) 디스크 부족 에러 로그 전송 -> 탐지/진단/추천
curl -s -X POST http://localhost:8080/api/v1/logs \
  -H "Content-Type: application/json" \
  -d '{
    "level": "ERROR",
    "message": "No space left on device",
    "service": "log-writer",
    "host": "host-1"
  }' | python3 -m json.tool
```

응답의 `recommendation.recommended_actions`(예: `["compress_old_logs"]`)와
`recommendation.past_cases`(과거 유사 사례, `resolution` 필드 포함)를 보고
운영자가 조치를 고른다고 가정한다.

```bash
# 2) 운영자가 compress_old_logs를 승인 -> 실제 스크립트 실행
curl -s -X POST http://localhost:8080/api/v1/remediations/approve \
  -H "Content-Type: application/json" \
  -d '{
    "script_id": "compress_old_logs",
    "error_code": "DISK_FULL",
    "approved_by": "operator-1"
  }' | python3 -m json.tool
# -> status: "success", stdout: "TEST_COMPRESS_OLD_LOGS_OK ..."

# 3) 추천되지 않은(allowlist에 없는) 스크립트는 차단되는지 확인
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8080/api/v1/remediations/approve \
  -H "Content-Type: application/json" \
  -d '{
    "script_id": "rm_rf_root",
    "error_code": "DISK_FULL",
    "approved_by": "operator-1"
  }'
# -> 403
```

`ORA-28040` 계열도 동일하게 확인할 수 있다:

```bash
curl -s -X POST http://localhost:8080/api/v1/logs \
  -H "Content-Type: application/json" \
  -d '{"level":"ERROR","message":"ORA-28040: no matching authentication protocol","service":"db-gateway","host":"host-2"}' \
  | python3 -m json.tool
# recommended_actions -> ["update_jdbc_driver", "modify_sqlnet"]
```

## 3. Qdrant 기반 추천 테스트

```bash
# incident_cases.py의 과거 사례를 Qdrant에 임베딩해서 업로드 (최초 1회)
python -m qdrant.seed

CASE_SEARCHER_BACKEND=qdrant python app.py
```

위 1번 curl(디스크 부족 로그)을 다시 보내보면, `past_cases`가 하드코딩된
mock 응답 대신 Qdrant 벡터 검색 결과(유사도 `score` 포함, 여러 건)로 채워지는
것을 확인할 수 있다.

## 4. Elasticsearch 기반 추천 테스트

로컬에 Elasticsearch가 없다면(예: 이 저장소를 처음 받은 환경) 아래처럼 보안
없이 단일 노드로 띄운다. **개발/테스트 전용 설정이다 — 운영에는 사용하지
말 것.**

```bash
docker run -d --name test-es \
  -p 9200:9200 \
  -e "discovery.type=single-node" \
  -e "xpack.security.enabled=false" \
  docker.elastic.co/elasticsearch/elasticsearch:8.15.0
```

```bash
export ELASTICSEARCH_URL=http://localhost:9200
export ELASTICSEARCH_USER=elastic
export ELASTICSEARCH_PASSWORD=
export ELASTICSEARCH_VERIFY_CERTS=false

# 연결 확인
python -m elastic.main

# incident_cases.py의 과거 사례를 incident-cases 인덱스에 시딩 (최초 1회)
python -m elastic.seed_cases

# LogRepository도 Elasticsearch로 저장하고 싶다면 함께 지정
LOG_REPOSITORY_BACKEND=elastic CASE_SEARCHER_BACKEND=elastic python app.py
```

1번의 curl을 다시 보내면 `past_cases`가 Elasticsearch 키워드 검색 결과로
채워지고, `/health`의 `storage`가 `elastic`으로 표시된다. 저장된 문서는
`python -m elastic.search_log`류 스크립트나 Kibana/`curl localhost:9200/...`로
직접 확인 가능하다.

> **이 환경에서 직접 검증한 것과 못한 것**: 이 세션에서는 로컬에 Docker가
> 떠 있지 않아 실제 Elasticsearch 서버로 end-to-end 저장/조회까지는 확인하지
> 못했다. `LOG_REPOSITORY_BACKEND=elastic`/`CASE_SEARCHER_BACKEND=elastic`
> 로 실행했을 때 코드 경로가 정확히 Elasticsearch까지 도달하고, 서버가 없을
> 땐 앱이 죽지 않고 `processing_failed`로 깔끔하게 에러를 반환하는 것까지는
> 확인했다. 위 docker 명령으로 실제 서버를 띄운 뒤 한 번 더 검증해보는 걸
> 권장한다.

## 5. Hybrid 모드 (Qdrant + Elasticsearch 동시 활용)

기획서의 "Qdrant와 Elasticsearch의 내용들을 토대로 추천"을 가장 그대로
구현한 모드. 두 백엔드 모두 시딩되어 있어야 한다(3, 4번 먼저 수행).

```bash
CASE_SEARCHER_BACKEND=hybrid python app.py
```

`past_cases`에 Qdrant 벡터 검색과 Elasticsearch 키워드 검색 결과가 합쳐져서
(동일 `incident_id`는 점수가 더 높은 쪽으로 병합) 반환된다.

## 6. fluentbit + log_generator로 실제 파이프라인 태우기

`log_generator/`가 정상/장애 로그를 만들어내고, fluentbit가 그 파일을 tail
해서 `/api/v1/logs`로 전달하는 흐름이다. **처음 점검했을 때는 이 둘이
연결되어 있지 않았다** — `log_generator/main.py`가 `log_generator/app.log`에
사람이 읽기 좋은 텍스트(`[시간] [레벨] ...`)로 썼는데, fluentbit는
`fluentbit/application.log`를 JSON 파서(`app_json`)로 tail하고 있어서
경로도 포맷도 둘 다 맞지 않았다. 그래서:

- `log_generator/logger/json_formatter.py`(신규) `JsonFormatter` 추가 —
  fluentbit의 `app_json` 파서와 백엔드 `log_normalizer.py`가 기대하는
  `timestamp`/`level`/`message`/`host`/`service` 필드를 가진 한 줄짜리
  JSON을 만든다.
- `log_generator/main.py`가 이제 `FLUENTBIT_LOG_PATH`(이 파일 위치 기준
  절대경로로 계산한 `fluentbit/application.log`)에 `JsonFormatter`로 쓴다.
  CWD가 어디든 항상 같은 파일을 가리킨다.

수정 후 아래 절차로 실행하면 된다:

```bash
# 터미널 1: 백엔드
python app.py

# 터미널 2: fluentbit
cd fluentbit
fluent-bit -c ./fluent-bit.conf

# 터미널 3: 로그 시뮬레이터
cd log_generator
python main.py
# -> fluentbit/application.log 에 JSON 로그가 계속 쌓이고,
#    fluentbit가 곧바로 tail해서 /api/v1/logs로 전달한다 (Ctrl+C로 중단)
```

**실제로 위 3개 프로세스를 동시에 띄워서 확인했다.** `python main.py`가 쓴
정상 로그(`INFO`)는 fluentbit를 거쳐 `{"status":"ignored"}`로, 무작위로
뽑힌 `ExternalAPIFailureScenario`/`MemoryLeakScenario` 등의 `ERROR` 로그는
`{"status":"unknown_error"}`로 도착하는 것을 fluent-bit의 `Log_Response_Payload`
로그에서 직접 확인했다. `DiskFullScenario`는 확률 기반이라 자연 발생을
기다리는 대신 같은 파일에 강제로 한 번 더 써서(`probability=1.0`으로 고정)
검증했는데, `{"status":"recommended","error_code":"DISK_FULL",...}` 까지
fluentbit → 백엔드 경로로 정확히 도착했다 — 진단 스크립트 실행, mock 과거
사례 검색, 추천안 생성까지 전부 정상 동작.

6개 장애 시나리오 중 실제로 `error_detector.py`가 인식하는 것은
`DiskFullScenario`의 `"No space left on device."` 메시지(→ `DISK_FULL`)
뿐이다. 나머지 DNS/DB커넥션/외부API/메모리릭/Redis 시나리오는
`error_detector.ERROR_PATTERNS`에 매칭되는 규칙이 아직 없어
`unknown_error`로 처리된다(로그 수신 자체는 정상 — 탐지 규칙만 없는 것) —
새 에러 코드를 다루려면 `config.ERROR_RULES`와
`error_detector.ERROR_PATTERNS`에 규칙을, 조치가 필요하면
`config.REMEDIATION_SCRIPTS`에 스크립트를 추가하면 된다.

> README.md의 "fluentbit 사용법" 절에 있는 수동 `echo '{"timestamp":...}' >>
> application.log` 데모도 동일한 파일을 대상으로 하기 때문에 여전히 그대로
> 동작한다 (직접 재확인함).

## 7. 알려진 제한사항 / 다음에 할 일

- `recommendation_generator`는 아직 mock. 실제 LLM 연동은 별도 진행 중.
- `HybridCaseSearcher`의 병합 로직은 "동일 incident_id면 더 높은 score 채택"
  하는 단순 로직이다. Qdrant(코사인 유사도)와 Elasticsearch(BM25) 점수
  스케일이 서로 달라 단순 비교는 정확하지 않을 수 있다 — 지금은 두 소스를
  "함께 보여준다"는 최소 요건만 만족시킨 상태.
- `ERROR_RULES`/`error_detector.ERROR_PATTERNS`에 등록된 에러 코드가
  `ORA-28040`, `DISK_FULL` 둘뿐이라 실제 서비스 커버리지는 아직 좁다.
- 이 환경에는 Elasticsearch가 없어 4번 항목은 코드 경로만 검증했고 실 서버
  기준 재검증이 필요하다.

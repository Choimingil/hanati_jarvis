# 실제 서비스 테스트 가이드

이 문서는 "에러 발생 → 진단 → **Qdrant/Elasticsearch에 학습된 과거 사례
기반 추천** → 운영자 승인 → 스크립트 실행"이라는 서비스 목표대로 지금
코드가 실제로 동작하는지 확인하는 절차를 정리한다. 코드 구조 자체가
궁금하면 [ARCHITECTURE.md](ARCHITECTURE.md)를 먼저 보는 걸 추천한다.

> **mock 없음**: `CaseSearcher`(Qdrant/Elasticsearch), `LogRepository`
> (Elasticsearch), `RecommendationGenerator`(LLM) 전부 실제 백엔드만
> 있다. fluent-bit/Elasticsearch/Qdrant 중 하나라도 꺼져 있으면 해당
> 기능은 그대로 실패한다 (`scripts/dev_infra.sh`로 셋 다 띄운다).

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
scripts/dev_infra.sh up   # fluent-bit + Elasticsearch + Qdrant 전부 Docker로 기동
python3 -m venv venv      # 이미 있다면 생략
source venv/bin/activate
pip install -r requirements.txt

# 최초 1회 데이터 시딩
python -m qdrant.seed
python -m elastic.seed_cases
```

## 2. 스모크 테스트

`config.py`의 `QDRANT_URL`/`ELASTICSEARCH_URL` 기본값이 `dev_infra.sh`가
띄운 컨테이너를 가리켜서 별도 env 없이 바로 동작한다.

```bash
scripts/run_app.sh
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
# -> status: "success", stdout: "[compress_old_logs] 오래된 로그 압축 작업 수행.. / 작업 완료.."

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

## 3. 과거 사례 검색 (Qdrant + Elasticsearch, 기본값 hybrid)

`CASE_SEARCHER_BACKEND` 기본값은 `hybrid` — Qdrant(벡터 유사도)와
Elasticsearch(키워드) 둘 다 조회해서 병합한다(동일 `incident_id`는 점수
높은 쪽 채택). `qdrant` / `elastic` 값으로 한쪽만 쓰게 강제할 수도 있다:

```bash
CASE_SEARCHER_BACKEND=qdrant scripts/run_app.sh   # Qdrant만
CASE_SEARCHER_BACKEND=elastic scripts/run_app.sh  # Elasticsearch만
```

1번 curl(디스크 부족 로그)을 보내면 `past_cases`가 실제 검색 결과(유사도
`score` 포함)로 채워진다. 둘 중 하나라도 꺼져 있으면(`scripts/dev_infra.sh
down` 등) 해당 요청은 연결 에러로 실패한다 — mock으로 대체되지 않는다.

저장된 Elasticsearch 문서는 `python -m elastic.search_log`류 스크립트나
Kibana/`curl localhost:9200/...`로 직접 확인 가능하다.

## 4. fluentbit + log_generator로 실제 파이프라인 태우기

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

fluent-bit는 이제 `scripts/dev_infra.sh up`으로 Docker 컨테이너로 뜬다
(`fluentbit/` 디렉토리를 통째로 마운트해서 `fluent-bit.conf`/`parser.conf`를
그대로 쓰고, `Host host.docker.internal`로 호스트에서 도는 백엔드에
전달한다). 절차:

```bash
# 터미널 1: 인프라 (fluent-bit 포함 3개 전부)
scripts/dev_infra.sh up

# 터미널 2: 백엔드
scripts/run_app.sh

# 터미널 3: 로그 시뮬레이터
cd log_generator
python main.py
# -> fluentbit/application.log 에 JSON 로그가 계속 쌓이고,
#    fluent-bit 컨테이너가 tail해서 host.docker.internal:8080 으로 전달 (Ctrl+C로 중단)
```

fluent-bit 컨테이너 로그는 `docker logs -f hanati-fluentbit`로 본다.

**실제로 위 조합을 다시 띄워서 확인했다(Docker 전환 후 재검증).**
`python main.py`가 쓴 정상 로그(`INFO`)는 `{"status":"ignored"}`로, 무작위로
뽑힌 `ExternalAPIFailureScenario`/`MemoryLeakScenario` 등의 `ERROR` 로그는
`{"status":"unknown_error"}`로 도착하는 것을 `docker logs`의
`Log_Response_Payload`에서 직접 확인했다. `DiskFullScenario`는 확률 기반이라
자연 발생을 기다리는 대신 같은 파일에 강제로 한 번 더 써서
(`probability=1.0`으로 고정) 검증했는데, `{"status":"recommended",
"error_code":"DISK_FULL",...}` 까지 fluent-bit(도커) → 백엔드 →
Qdrant+Elasticsearch(hybrid) → LLM 경로로 정확히 도착했다 —
`past_cases`에 두 백엔드 결과가 섞여 있고 `generated_by`가 `llm`인 것까지
확인.

이제 6개 장애 시나리오가 모두 `error_detector.py`에서 인식된다
(`DISK_FULL`, `DNS_RESOLUTION_FAILURE`, `DB_CONNECTION_FAILURE`,
`EXTERNAL_API_FAILURE`, `MEMORY_LEAK`, `REDIS_CONNECTION_FAILURE`).
각 코드마다 `config.ERROR_RULES`에 진단/조치 스크립트가 매핑되어 있고,
조치 스크립트는 `test-runbooks/`에서 `작업 수행.. / 작업 완료..` 형태로
동작한다. 새 에러 코드를 추가하려면 `error_detector.ERROR_PATTERNS`에
패턴을, `config.ERROR_RULES`에 규칙을, `test-runbooks/`에 스크립트를
추가하면 된다(스크립트 경로 맵은 `ERROR_RULES`에서 자동 생성된다).

> README.md의 "fluentbit 사용법" 절에 있는 수동 `echo '{"timestamp":...}' >>
> application.log` 데모도 동일한 파일을 대상으로 하기 때문에 여전히 그대로
> 동작한다 (직접 재확인함).

## 5. 웹 콘솔 (운영자 UI)

`scripts/run_app.sh` 로 서버를 띄운 뒤 브라우저에서 `http://localhost:8080/` 로
접속하면 운영자용 단일 페이지가 나온다.

1. 장애 시나리오(=log_generator가 만드는 6개 오류)를 하나 고르고 **분석** 클릭
   (직접 로그 메시지를 입력할 수도 있다)
2. `POST /api/v1/logs` 결과로 **현재 오류 원인**과 **추천도 높은 순 조치
   스크립트 리스트**(점수 바 포함)가 표시된다
3. 리스트에서 **실행**을 누르면 `POST /api/v1/remediations/approve` 로 해당
   스크립트가 실제로 호출되고, `작업 수행.. / 작업 완료..` stdout이 그대로
   화면에 출력된다

오류 원인과 추천 랭킹은 `RECOMMENDATION_BACKEND`(기본값 `llm`)가 결정한다.
`OPENAI_API_KEY`가 설정되어 있으면 LLM이 원인/랭킹을 생성하고, 없으면
`recommendation_ranker.py`의 결정론적 랭킹으로 자동 대체되므로 키 없이도
페이지가 정상 동작한다.

## 6. 알려진 제한사항 / 다음에 할 일

- 실제 LLM 호출은 `OPENAI_API_KEY`가 있을 때만 이뤄지고, 없으면 결정론적
  fallback 랭킹으로 동작한다(`generated_by`가 `llm` ↔ `llm-fallback`으로 구분됨).
- `HybridCaseSearcher`의 병합 로직은 "동일 incident_id면 더 높은 score 채택"
  하는 단순 로직이다. Qdrant(코사인 유사도)와 Elasticsearch(BM25) 점수
  스케일이 서로 달라 단순 비교는 정확하지 않을 수 있다 — 지금은 두 소스를
  "함께 보여준다"는 최소 요건만 만족시킨 상태.
- mock 백엔드는 전부 제거했다. fluent-bit/Elasticsearch/Qdrant 중 하나라도
  꺼져 있으면 관련 요청은 연결 에러로 실패한다 (앱 자체는 뜨고 `/health`는
  응답한다 - 개별 요청만 실패).

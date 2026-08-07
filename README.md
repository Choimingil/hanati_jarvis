> 코드 구조/클래스별 역할은 [ARCHITECTURE.md](ARCHITECTURE.md), 전체 서비스
> 흐름(탐지→진단→추천→운영자 승인→스크립트 실행)을 실제로 테스트하는
> 방법은 [TESTING.md](TESTING.md) 참고.

## 로컬 인프라 자동 실행 (fluent-bit / Elasticsearch / Qdrant)

**mock 백엔드 없음.** 셋 다 Docker 컨테이너로 띄운다 (fluent-bit도 포함,
`fluentbit/fluent-bit.conf`/`parser.conf`를 그대로 마운트해서 씀). 셋 중
하나라도 꺼져 있으면 관련 API 요청이 그대로 실패한다 — Docker Desktop을
먼저 켜둘 것.

```bash
scripts/dev_infra.sh up       # 이미지 없으면 받아서 3개 전부 기동
scripts/dev_infra.sh status   # 상태 확인
scripts/dev_infra.sh down     # 전부 정지
```

`config.py`의 `QDRANT_URL`/`ELASTICSEARCH_URL` 기본값이 위 컨테이너를
가리키므로 별도 export 없이 바로 연동된다. 최초 1회 데이터 시딩:

```bash
python -m qdrant.seed
python -m elastic.seed_cases
```

백엔드 실행 (venv 없으면 생성 + 의존성 설치까지 자동):

```bash
scripts/run_app.sh
```

자세한 사용 흐름은 [TESTING.md](TESTING.md) 참고.

## fluentbit 사용법

fluent-bit는 `scripts/dev_infra.sh up`으로 Docker 컨테이너로 뜬다 (위
"로컬 인프라 자동 실행" 참고). 동작 확인:

1. `scripts/run_app.sh`로 백엔드 실행
2. 다른 터미널에서 `fluentbit` 디렉토리 진입 후
   `echo '{"timestamp":"2026-07-13T19:40:00+0900","level":"INFO","message":"HTTP output test"}' >> application.log` 수행
3. 백엔드 실행한 터미널이나 `docker logs -f hanati-fluentbit`에서 API 넘어온 것 확인




fluentbit api 주소

http://localhost:8080/api/v1/logs POST

## 시스템 메트릭 수집 Agent

`psutil` 기반 Agent가 호스트 CPU/메모리/디스크/네트워크와 CPU 사용률이
높은 프로세스 목록을 수집해 Elasticsearch의
`application-system-metrics` 인덱스에 저장한다. 프로세스 명령행과 환경변수는
민감정보 노출을 막기 위해 수집하지 않는다.

`scripts/run_app.sh`를 실행하면 백엔드와 Agent가 함께 기동되며 기본 30초마다
자동 수집한다. 백엔드 종료 시 Agent도 함께 종료된다.

Agent만 별도로 실행하려면 다음 명령을 사용한다.

```bash
python -m collector.agent --once
python -m collector.agent
```

기본 전송 주소는 `http://127.0.0.1:8080/api/v1/metrics`, 수집 간격은 30초,
프로세스는 상위 20개다. 아래 환경변수로 변경할 수 있다.

- `METRICS_API_URL`
- `METRICS_COLLECT_INTERVAL_SECONDS`
- `METRICS_PROCESS_LIMIT`
- `ELASTIC_METRICS_INDEX`
- `METRICS_AGENT_ENABLED` (`false`이면 `run_app.sh`에서 자동 기동하지 않음)

Linux에서 전체 프로세스의 네트워크 연결을 조회하려면 Agent 실행 계정에
추가 권한이 필요할 수 있다. 권한이 없으면 스냅샷의
`network.connections.access_denied`가 `true`가 되고 나머지 정보는 계속
수집된다.

### 메트릭 기반 자동 탐지·가이드

메트릭 저장 후 다음 분석이 자동으로 실행된다.

1. 최근 15분 스냅샷에서 1분/5분/15분 특징값 계산
2. 메모리 증가, 디스크 포화, CLOSE_WAIT, 네트워크 오류 증가 탐지
3. 같은 호스트의 최근 ERROR 로그 연관 분석
4. Elasticsearch/Qdrant에서 동일 오류 유형의 과거 사례 검색
5. 현재 근거와 과거 사례를 LLM에 전달해 Runbook 추천
6. 완성된 장애 사례를 `incident-cases`와 Qdrant에 저장

동일 호스트·탐지 코드의 장애는 기본 5분 동안 다시 생성하지 않는다.
임계값과 쿨다운은 환경변수로 조정할 수 있다.

- `INCIDENT_COOLDOWN_MINUTES`
- `ANOMALY_MEMORY_PERCENT_THRESHOLD`
- `ANOMALY_MEMORY_GROWTH_THRESHOLD`
- `ANOMALY_DISK_PERCENT_THRESHOLD`
- `ANOMALY_CLOSE_WAIT_THRESHOLD`
- `ANOMALY_NETWORK_ERROR_GROWTH_THRESHOLD`

조치 후 새 메트릭이 수집되면 다음 API로 실제 복구 여부를 검증할 수 있다.

```bash
curl -X POST http://localhost:8080/api/v1/remediations/verify \
  -H 'Content-Type: application/json' \
  -d '{"incident_id":"장애 UUID"}'
```

검증 결과는 `application-recovery-verifications` 인덱스에 저장된다.




구현 방법

ports 디렉토리 하위에

case_searcher.py : Qdrant 구현
log_repository.py : ElasticSearch 구현
recommendation_generator.py : LLM 구현


## log gernerator 사용법
현재 프로젝트 내의 실행하고 있는 프로그램 내에 loggenerator_example.py 코드 삽입

수행과 함께 /app.log 경로에 로그 발생

## LLM API 사용법

프로젝트 최상단에서 아래 명령어 수행 API 서버 기동

```
uvicorn llm_agent.app:app --host 127.0.0.1 --port 8000 --reload
```

API는 http://127.0.0.1:8000/docs 에서 확인


## 웹 콘솔 (운영자 UI)

메인 서비스(`python app.py`)를 띄운 뒤 브라우저에서
`http://localhost:8080/` 로 접속하면 운영자용 단일 페이지가 나온다.

1. `log_generator`가 만드는 6개 장애 시나리오 중 하나를 고르고 **분석** 클릭
2. LLM이 판단한 **현재 오류 원인**과, 호출하면 좋은 **조치 스크립트를
   추천도 높은 순**으로 정렬한 리스트(점수 바 포함)가 표시된다
3. 리스트에서 **실행**을 누르면 해당 스크립트가 실제로 호출되고
   (`작업 수행.. / 작업 완료..`) 결과가 화면에 출력된다

원인/랭킹은 `RECOMMENDATION_BACKEND`(기본값 `llm`)가 담당한다.
`OPENAI_API_KEY`가 있으면 LLM이, 없으면 `recommendation_ranker.py`의
결정론적 랭킹이 자동으로 대체하므로 키 없이도 페이지가 동작한다.

인식하는 오류 코드는 `DISK_FULL`, `DNS_RESOLUTION_FAILURE`,
`DB_CONNECTION_FAILURE`, `EXTERNAL_API_FAILURE`, `MEMORY_LEAK`,
`REDIS_CONNECTION_FAILURE`(+ 기존 `ORA-28040`)이며, 각 코드의 진단/조치
스크립트는 `config.ERROR_RULES`에 정의되어 있고 실제 파일은
`test-runbooks/`에 있다.


## Qdrant 연동 (case_searcher)

기존에는 `case_searcher`가 항상 `MockCaseSearcher`(하드코딩된 응답)로 동작했는데,
`CASE_SEARCHER_BACKEND` 환경변수로 mock / Qdrant 중 선택해서 실행할 수 있도록 수정했다.

### 변경된 파일

- `config.py` : `CASE_SEARCHER_BACKEND`, `QDRANT_URL`, `QDRANT_PATH`,
  `QDRANT_COLLECTION`, `EMBEDDING_MODEL_NAME`, `EMBEDDING_VECTOR_SIZE` 설정 추가
- `qdrant/client.py` (신규) : Qdrant 클라이언트 / 임베딩 모델(`BAAI/bge-m3`)을
  lazy singleton으로 생성하는 공용 모듈
- `qdrant/seed.py` (신규, 기존 `qdrant/qdrant.py` 데모 스크립트를 대체) :
  `incident_cases` 컬렉션에 테스트용 과거 사례를 시딩하는 스크립트
- `adapters/qdrant_adapters.py` (신규) : `CaseSearcher` 포트를 구현하는
  `QdrantCaseSearcher` (질의를 임베딩 후 벡터 검색, `MockCaseSearcher`와
  동일한 응답 스키마로 반환)
- `dependencies.py` : `CASE_SEARCHER_BACKEND` 값에 따라 `MockCaseSearcher` /
  `QdrantCaseSearcher` 중 하나를 주입
- `app.py` : `/health`의 `case_search` 값이 실제 사용 중인 백엔드를 반영
- `requirements.txt` : `qdrant-client`, `sentence-transformers` 추가

### 사용법

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. incident_cases 컬렉션 시딩 (최초 1회, 데이터 갱신 시 재실행)
python -m qdrant.seed

# 3. Qdrant 백엔드로 서버 실행
CASE_SEARCHER_BACKEND=qdrant python app.py
```

`CASE_SEARCHER_BACKEND`를 지정하지 않으면 기존과 동일하게 mock으로 동작한다.

기본값은 로컬 파일 기반 Qdrant(`qdrant/qdrant_data/`, git에는 커밋되지 않음)이며,
Docker 등으로 별도 Qdrant 서버를 띄운 경우 `QDRANT_URL`(예: `http://localhost:6333`)을
지정하면 해당 서버를 사용한다.


## 구현 내용

### 1. Elasticsearch Client 구성

파일: elastic/client.py

구현 내용:

- Python Elasticsearch Client 연결 구현
- Elasticsearch 서버 연결 설정
- Basic Authentication 적용
- HTTPS 환경에서 Elasticsearch 통신 구성


### 2. 로그 Index 생성 및 Mapping 설계

파일: elastic/mapping.py

구현 내용:

- 로그 데이터 저장을 위한 Elasticsearch Index 생성
- 로그 분석 목적에 맞는 Field Mapping 설계
- 로그 검색 성능을 고려한 데이터 타입 설정

생성 Index: application-logs

Mapping:


Mapping:

|Field|Type|설명|
|---|---|---|
|timestamp|date|로그 발생 시간|
|service|keyword|서비스명|
|level|keyword|로그 레벨(INFO, ERROR 등)|
|message|text|로그 메시지|
|user_id|keyword|사용자 식별 정보|
|request_url|keyword|요청 URL|
|method|keyword|HTTP Method|
|error|text|오류 내용|
|host|keyword|서버 정보|


### 3. 로그 데이터 적재 기능 구현

파일: elastic/insert_log.py

구현 내용:

- Python Dictionary 형태의 로그 데이터 생성
- Elasticsearch Document 형태로 변환 및 저장
- 저장된 로그 ID 반환 기능 구현


저장 예시:

```json
{
  "timestamp": "2026-07-13T21:29:25",
  "service": "auth-service",
  "level": "ERROR",
  "message": "로그인 실패",
  "user_id": "user123",
  "request_url": "/login",
  "method": "POST",
  "error": "Invalid password",
  "host": "server01"
}

4. 로그 조회 및 검색 기능 구현

파일: elastic/search_log.py

구현 내용:
- Elasticsearch 저장 로그 조회
- 저장된 Document 검색 기능 구현
- 장애 로그 분석을 위한 검색 기반 마련


## Elasticsearch 연동 (log_repository)

`elastic/` 디렉토리의 스크립트들은 원래 `from client import get_client`처럼
스크립트 자신의 디렉토리를 기준으로 하는 import를 사용하고 있어서, 패키지로
`import elastic.xxx` 하면 `ModuleNotFoundError`가 발생했다. 또한 접속 정보
(URL, 비밀번호)가 `elastic/client.py`에 하드코딩되어 있었다. 이번에 아래와
같이 수정해서 `case_searcher`와 동일한 방식으로 `log_repository`도 mock /
Elasticsearch를 스위치할 수 있도록 통합했다.

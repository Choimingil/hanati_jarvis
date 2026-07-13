> 코드 구조/클래스별 역할은 [ARCHITECTURE.md](ARCHITECTURE.md), 전체 서비스
> 흐름(탐지→진단→추천→운영자 승인→스크립트 실행)을 실제로 테스트하는
> 방법은 [TESTING.md](TESTING.md) 참고.

## fluentbit 사용법

1. fluentbit-test.py 실행 : python3 fluentbit-test,py

2. fluentbit 디렉토리 내에서 fluent-bit -c ./fluent-bit.conf 수행

3. 다른 터미널에서 fluentbit 디렉토리 진입 후 echo '{"timestamp":"2026-07-13T19:40:00+0900","level":"INFO","message":"HTTP output test"}' >> application.log 수행

4. 파이썬 실행한 터미널에서 API 넘어온 것 확인




fluentbit api 주소

http://localhost:8080/api/v1/logs POST




구현 방법

ports 디렉토리 하위에

case_searcher.py : Qdrant 구현
log_repository.py : ElasticSearch 구현
recommendation_generator.py : LLM 구현


## log gernerator 사용법
현재 프로젝트 내의 실행하고 있는 프로그램 내에 loggenerator_example.py 코드 삽입

수행과 함께 /app.log 경로에 로그 발생


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

### 변경된 파일

- `elastic/*.py` : 내부 import를 `from client import ...` →
  `from elastic.client import ...` 형태로 수정해 패키지로 정상 import되도록
  변경 (`elastic/client.py`, `mapping.py`, `insert_log.py`, `search_log.py`,
  `search_test.py`, `main.py`, `bulk_insert.py`)
- `elastic/client.py` : 하드코딩되어 있던 URL/비밀번호를 제거하고
  `config.py`의 `ELASTICSEARCH_URL` / `ELASTICSEARCH_USER` /
  `ELASTICSEARCH_PASSWORD` / `ELASTICSEARCH_VERIFY_CERTS` 환경변수를 사용하도록 변경
- `config.py` : `LOG_REPOSITORY_BACKEND`, `ELASTICSEARCH_URL`,
  `ELASTICSEARCH_USER`, `ELASTICSEARCH_PASSWORD`,
  `ELASTICSEARCH_VERIFY_CERTS`, `ELASTIC_LOG_INDEX`,
  `ELASTIC_DIAGNOSIS_INDEX`, `ELASTIC_RECOMMENDATION_INDEX` 설정 추가
- `adapters/elastic_adapters.py` (신규) : `LogRepository` 포트를 구현하는
  `ElasticLogRepository` (`save_log` / `save_diagnosis` /
  `save_recommendation`을 각각 별도 인덱스에 저장)
- `dependencies.py` : `LOG_REPOSITORY_BACKEND` 값에 따라 `MockLogRepository` /
  `ElasticLogRepository` 중 하나를 주입
- `app.py` : `/health`의 `storage` 값이 실제 사용 중인 백엔드를 반영
- 루트의 `elastic_repository.py` 삭제 : `config.ELASTICSEARCH_URL`이 정의되어
  있지 않아 애초에 import가 실패하던 죽은 코드였고, 동일한 역할을
  `adapters/elastic_adapters.py`가 대체함

### 사용법

```bash
# 1. 의존성 설치 (elasticsearch 패키지는 requirements.txt에 이미 포함)
pip install -r requirements.txt

# 2. 접속 정보를 환경변수로 지정 (비밀번호는 기본값 없음, 반드시 지정)
export ELASTICSEARCH_URL=https://localhost:9200
export ELASTICSEARCH_USER=elastic
export ELASTICSEARCH_PASSWORD=your-password

# 3. elastic 백엔드로 서버 실행
LOG_REPOSITORY_BACKEND=elastic python app.py
```

`LOG_REPOSITORY_BACKEND`를 지정하지 않으면 기존과 동일하게 mock으로 동작한다.

> 참고: 이 환경에는 실행 중인 Elasticsearch 서버가 없어서(포트 9200
> connection refused) 실제 저장/조회까지는 검증하지 못했다. import 경로와
> mock ↔ elastic 스위치 배선, 그리고 연결 실패 시 에러가 앱을 죽이지 않고
> `processing_failed` 응답으로 깔끔하게 전파되는 것까지는 확인했다.
> 로컬에 Elasticsearch를 띄운 뒤(`elastic/main.py`로 연결 확인,
> `elastic/mapping.py`로 인덱스 생성) 실제 저장 결과를 검증해보길 권장한다.

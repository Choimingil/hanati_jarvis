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

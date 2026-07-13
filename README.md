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
fluentbit 사용법

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

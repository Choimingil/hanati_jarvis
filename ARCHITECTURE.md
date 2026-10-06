# 시스템 구조

실행 기준은 `docker-compose.yml`입니다. Elasticsearch·Qdrant·Redis·LLM Agent·수집기·Fluent Bit·AIOps API·분석 worker가 Compose 내부 네트워크로 통신합니다. 기존 초기화와 수집 Python 모듈은 해당 이미지에서 실행합니다.

수집 API는 마스킹한 데이터를 Redis Streams에 기록한 뒤 202를 반환합니다. Worker는 작업 잠금과 처리 중 heartbeat를 유지하며 분석 결과를 Elasticsearch에 저장합니다. 실패 작업은 최대 3회 처리 후 실패 기록을 남깁니다. 작업 접수증은 완료 후 기본 7일 보관합니다. 모든 저장소를 아우르는 exactly-once 트랜잭션을 제공하지는 않습니다.

추천은 incident ID·버전·만료 시간·작업 ID·등록된 대상 목록을 포함합니다. 사전 검증 결과는 대상과 Agent 정책 해시에 결합되고 120초 동안 유효합니다. Redis의 대상·추천 잠금과 Agent SQLite journal은 실행 ID 재사용 및 중복 실행을 막습니다. 응답 유실 시 재실행하지 않고 원래 실행 기록을 조회합니다. 불확실한 결과는 잠금을 유지합니다.

선택적 `execution` profile의 Agent는 기존 AIOps 이미지를 사용합니다. Docker API로 등록된 Compose 프로젝트·서비스·이미지를 확인하고 내장 조회/재시작 작업을 수행합니다. 셸, 호스트 명령, 컨테이너 exec는 사용하지 않습니다. Docker socket 접근 권한은 Docker 호스트 제어 권한에 해당하므로 Agent와 정책 파일을 신뢰할 수 있는 관리 범위에 두어야 합니다.

상태 복원은 동일 컨테이너·동일 이미지의 실행/정지/일시정지 상태에 한정됩니다. 이미지 버전, 배포 구성, 데이터베이스 또는 거래 데이터의 롤백을 의미하지 않습니다. 현재 업무 검사 구현은 Jarvis의 접수 및 분석 경로입니다. 금융 업무별 검증은 별도 내장 probe 구현과 정책 등록이 필요합니다.

`/health`는 저장소와 분석 worker 준비 상태에 따라 200/503을 반환합니다. 응답과 `/api/v1/operations/status`에는 별도로 수집 지연·누락을 표시합니다. 수집 상태 때문에 건강한 이중화 컨테이너 판정이 순환해서 차단되지 않도록 readiness와 데이터 신선도를 구분합니다.

원문·저장 문서·LLM 요청·JSON 응답에 민감 정보 마스킹을 적용합니다. 정규식 마스킹은 완전한 DLP를 대체하지 않습니다. `LLM_EXTERNAL_ENABLED=false`로 외부 LLM 호출을 차단할 수 있습니다. 사용자 로그인/RBAC는 이번 범위에서 제외했습니다.

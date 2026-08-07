# Hanati Jarvis AIOps

로그와 호스트 리소스를 함께 분석해 장애를 탐지하고, 과거 검증 사례를 근거로
Runbook 또는 추가 진단 가이드를 제공하는 운영자 승인형 AIOps 서비스다.

- 로그 수집: Fluent Bit → Flask API → Elasticsearch
- 리소스 수집: psutil Agent → Flask API → Elasticsearch
- 사례 검색: Elasticsearch 키워드 검색 + Qdrant 벡터 검색
- 원인·조치 안내: LLM, 실패 시 결정론적 fallback
- 조치 실행: 운영자 승인 후 allowlist Runbook만 실행
- 학습 사례: 운영자 확인과 복구 검증이 끝난 사례만 승격

세부 코드 구조는 [ARCHITECTURE.md](ARCHITECTURE.md), 수동 테스트 절차는
[TESTING.md](TESTING.md)를 참고한다.

## 1. 서비스 동작 흐름

### 1.1 등록된 오류 로그

```text
ERROR 로그 수신
→ 오류 코드 판별
→ 진단 스크립트 실행
→ Elasticsearch/Qdrant 과거 사례 검색
→ LLM 원인·Runbook 추천
→ 추천 품질 검사
→ 운영자 승인/거부/추가 진단
→ 실행 결과 저장
```

지원 오류 코드는 다음과 같다.

- `ORA-28040`
- `DISK_FULL`
- `DNS_RESOLUTION_FAILURE`
- `DB_CONNECTION_FAILURE`
- `EXTERNAL_API_FAILURE`
- `MEMORY_LEAK`
- `REDIS_CONNECTION_FAILURE`

추천 Runbook은 `config.ERROR_RULES`에 등록된 후보만 허용하며, 실제 파일은
`test-runbooks/`에 있다. LLM이 임의 명령을 생성해 실행할 수는 없다.

### 1.2 추천할 수 없는 오류 로그

다음 조건이면 기존 추천을 중단하고 리소스 기반 fallback을 실행한다.

- 등록되지 않은 오류 코드
- 조치 후보가 없음
- 추천 또는 Runbook이 비어 있음
- 최고 추천 신뢰도가 기준값보다 낮음
- 추천 생성기가 실패함

fallback 흐름:

```text
추천 품질 미달
→ 같은 호스트의 최근 15분 메트릭 조회
→ 1분/5분/15분 특징 계산
→ 리소스 문제 가설 생성
→ 관련 오류 유형의 검증된 과거 사례 검색
→ LLM이 수치 근거 안에서 요약
→ 운영자에게 가설·신뢰도·추가 진단 제시
```

현재 생성 가능한 리소스 가설:

| 가설 | 주요 근거 |
|---|---|
| CPU 포화 | CPU 평균·최대, 상위 프로세스 |
| 메모리 누수/캐시 증가 | 메모리 사용률·증가량, Swap |
| 디스크 압박 | 디스크 사용률·남은 공간 |
| 연결 누수 | `CLOSE_WAIT` 수와 증가량 |
| 네트워크 불안정 | 패킷 오류·드롭 증가량 |
| 리소스 정상 | 주요 지표가 임계값 이내 |
| 데이터 부족 | 최근 메트릭 없음 또는 호스트 불일치 |

리소스 가설은 원인 확정이 아니다. 자동 조치는 항상 비활성화되고 운영자의
확인이 필요하다.

### 1.3 메트릭에서 먼저 발견한 이상

psutil Agent가 보낸 메트릭은 저장 직후 자동 분석된다.

```text
30초 메트릭 수집
→ 1분/5분/15분 특징 계산
→ 메모리·디스크·연결·네트워크 이상 탐지
→ 같은 호스트의 최근 ERROR 로그 연관 분석
→ 과거 사례 검색
→ LLM Runbook 추천
→ Elasticsearch와 Qdrant에 장애 사례 저장
```

같은 호스트에서 동일 탐지가 반복될 경우 기본 5분 쿨다운을 적용한다.

### 1.4 운영자 피드백과 사례 승격

리소스 fallback 결과는 다음 상태로 평가할 수 있다.

- `confirmed`: 원인과 관련 있음
- `partial`: 일부 관련 있음
- `rejected`: 관련 없음
- `needs_investigation`: 추가 확인 필요

다음 조건을 모두 만족한 경우에만 검증된 장애 사례로 Elasticsearch와
Qdrant에 저장한다.

```text
운영자 confirmed
+ 실제 원인 입력
+ 수행한 조치 입력
+ recovered=true
```

LLM이 제안했다는 이유만으로 학습 사례가 되지 않는다.

## 2. 실행 방법

### 2.1 인프라 실행

Docker Desktop을 먼저 실행한다.

```bash
scripts/dev_infra.sh up
scripts/dev_infra.sh status
```

이 스크립트는 다음 컨테이너를 기동한다.

- Fluent Bit
- Elasticsearch
- Qdrant

최초 한 번 과거 사례를 시딩한다.

```bash
python -m qdrant.seed
python -m elastic.seed_cases
```

종료:

```bash
scripts/dev_infra.sh down
```

### 2.2 애플리케이션과 psutil Agent 실행

```bash
scripts/run_app.sh
```

`run_app.sh`는 다음 작업을 한 번에 수행한다.

1. `venv`가 없으면 생성
2. `requirements.txt` 설치 확인
3. Flask 백엔드 실행
4. psutil Agent 실행
5. 기본 30초마다 시스템 메트릭 전송
6. 백엔드 종료 시 Agent 함께 종료

Agent를 비활성화하려면:

```bash
METRICS_AGENT_ENABLED=false scripts/run_app.sh
```

Agent만 한 번 실행하려면:

```bash
python -m collector.agent --once
```

운영자 콘솔은 `http://localhost:8080/`, 상태 확인은
`http://localhost:8080/health`에서 가능하다.

## 3. 수집 데이터

psutil Agent는 다음 정보를 수집한다.

- CPU 전체·코어별 사용률과 Load Average
- 메모리, 가용 메모리, Swap
- 루트 디스크 사용량과 디스크 I/O 누적값
- 네트워크 송수신량, 오류, 드롭
- TCP 상태별 연결 수와 LISTEN 포트
- CPU 기준 상위 프로세스의 PID, 이름, 메모리, 스레드 수

민감정보 노출을 줄이기 위해 프로세스 명령행과 환경변수는 수집하지 않는다.
Linux에서 전체 연결 조회 권한이 없으면
`network.connections.access_denied=true`로 기록하고 나머지는 계속 수집한다.

Fluent Bit은 `fluentbit/application.log`를 읽어
`POST /api/v1/logs`로 전송한다. 현재 Fluent Bit은 로그 수집을 담당하고
호스트 리소스는 psutil Agent가 담당한다.

## 4. 주요 API

| Method | 경로 | 역할 |
|---|---|---|
| `GET` | `/health` | 백엔드 설정 및 상태 확인 |
| `POST` | `/api/v1/logs` | 단건/배열 로그 분석 |
| `POST` | `/api/v1/metrics` | 시스템 메트릭 저장 및 자동 분석 |
| `POST` | `/api/v1/remediations/approve` | Runbook 승인 및 실행 |
| `POST` | `/api/v1/remediations/reject` | Runbook 거부 기록 |
| `POST` | `/api/v1/remediations/diagnose` | 진단 스크립트 재실행 |
| `POST` | `/api/v1/remediations/verify` | 조치 전후 메트릭으로 복구 검증 |
| `POST` | `/api/v1/guidance/feedback` | 리소스 가설에 대한 운영자 피드백 |

피드백 요청 예시:

```bash
curl -X POST http://localhost:8080/api/v1/guidance/feedback \
  -H 'Content-Type: application/json' \
  -d '{
    "guidance_id": "가이드 UUID",
    "operator": "operator01",
    "verdict": "confirmed",
    "confirmed_root_cause": "HTTP 응답 객체 close 누락",
    "successful_action": "애플리케이션 수정 및 재배포",
    "recovered": true,
    "confirmed_error_code": "EXTERNAL_API_FAILURE"
  }'
```

복구 검증 요청 예시:

```bash
curl -X POST http://localhost:8080/api/v1/remediations/verify \
  -H 'Content-Type: application/json' \
  -d '{"incident_id":"장애 UUID"}'
```

## 5. 저장 인덱스

| Elasticsearch 인덱스 | 데이터 |
|---|---|
| `application-logs` | 수신 로그 |
| `application-system-metrics` | 30초 단위 리소스 스냅샷 |
| `application-diagnoses` | 진단 스크립트 결과 |
| `application-recommendations` | Runbook 및 리소스 가이드 |
| `application-remediations` | 승인·거부·실행 결과 |
| `application-resource-guidance` | 미등록/저신뢰 로그의 리소스 가설 |
| `application-operator-feedback` | 가설에 대한 운영자 판단 |
| `application-recovery-verifications` | 조치 전후 복구 판정 |
| `incident-cases` | 검증된 과거 장애 사례 |

Qdrant의 `incident_cases` 컬렉션에는 장애 요약 임베딩과 오류 코드 payload를
저장한다. 검색 시 의미 유사도와 오류 코드 필터를 함께 적용한다.

## 6. 주요 환경변수

### API·수집

- `API_HOST` / `API_PORT`
- `METRICS_API_URL`
- `METRICS_COLLECT_INTERVAL_SECONDS` 기본 `30`
- `METRICS_PROCESS_LIMIT` 기본 `20`
- `METRICS_AGENT_ENABLED` 기본 `true`

### 검색·저장

- `ELASTICSEARCH_URL`
- `ELASTICSEARCH_USER`
- `ELASTICSEARCH_PASSWORD`
- `QDRANT_URL`
- `QDRANT_COLLECTION`
- `CASE_SEARCHER_BACKEND`: `qdrant`, `elastic`, `hybrid`(기본)
- `OPENAI_API_KEY`

### 탐지·품질 기준

- `INCIDENT_COOLDOWN_MINUTES` 기본 `5`
- `RESOURCE_FALLBACK_CONFIDENCE_THRESHOLD` 기본 `60`
- `RESOURCE_CPU_PERCENT_THRESHOLD` 기본 `90`
- `ANOMALY_MEMORY_PERCENT_THRESHOLD` 기본 `90`
- `ANOMALY_MEMORY_GROWTH_THRESHOLD` 기본 `10`
- `ANOMALY_DISK_PERCENT_THRESHOLD` 기본 `90`
- `ANOMALY_CLOSE_WAIT_THRESHOLD` 기본 `100`
- `ANOMALY_NETWORK_ERROR_GROWTH_THRESHOLD` 기본 `20`

## 7. 테스트

```bash
python -m unittest discover -s tests -v
python -m compileall -q .
bash -n scripts/run_app.sh
```

현재 테스트는 시스템 수집, 메트릭 특징 추출, 이상 탐지, 장애 사례 생성,
복구 검증, 미등록 로그 fallback, 추천 품질 검사, 운영자 피드백과 검증 사례
승격을 포함한다.

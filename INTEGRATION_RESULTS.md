# 연동 검사 결과 — 2026-10-06

대상: mingil, 검사 시작 기준 e1d6d01034e761049743c6c0bb485151c4a08872. 아래 두 수정과 검사 코드를 반영한 상태의 결과입니다.

## 판정

현재 환경에서 수행 가능한 검사 84개가 통과했습니다. **Docker/Podman 실행 파일, Docker socket, Fluent Bit·Redis 서버 실행 파일이 없어 실제 Compose 컨테이너 간 연동 성공은 미확인입니다.** 배포 서버에 접근해 측정한 결과가 아닙니다.

| 경로 | 결과 | 검사 방식과 한계 |
|---|---|---|
| Fluent Bit JSON 형식→API→Redis 큐→Worker→ES 저장 어댑터 | 통과 | 실제 로그 formatter·Flask route·queue·worker·adapter 실행. Fluent Bit 필터의 Add는 모사, Redis는 fakeredis, ES는 기록 spy. 실제 Fluent Bit 프로세스는 미실행 |
| Collector→메트릭 API→메트릭 큐→Worker→저장 어댑터 | 통과 | 실제 현재 환경의 psutil snapshot 수집, 나머지 저장소는 모의. 배포 호스트 자원 수집을 보장하지 않음 |
| Qdrant 저장·384차원 검색·오류 코드 필터·마스킹 | 통과 | 실제 qdrant-client 로컬 엔진. 고정 테스트 벡터를 사용하므로 임베딩 모델 추론은 미검사 |
| Qdrant 종료·다시 열기→데이터 유지 | 통과 | 임시 디렉토리의 실제 로컬 저장소 재개방. Docker volume 복구 검사는 아님 |
| Elasticsearch HTTP 직렬화·인덱스 URL·마스킹 | 통과 | 실제 ES Python 클라이언트와 localhost HTTP stub 사용. 실제 Elasticsearch 엔진·매핑은 미실행 |
| Compose 내부 URL·의존 서비스·공유 로그 volume·Dockerfile 경로 | 통과 | YAML/파일 계약 검사. Docker Compose 자체 config/기동 검사는 아님 |
| Admin·Client 초기화·사건 상세 선택·출력 이스케이프 | 통과 | jsdom과 모의 API 응답. 실제 배포 브라우저 검사는 아님 |
| Redis 장애 시 접수 실패, 재시도, 중복 억제·정책·복구 지표 | 통과 | 기존 검사 포함, 실제 서비스 장애 유발은 아님 |
| 외부 LLM 생성·Agent 실제 조치·실제 업무 API | 미검사 | 자격증명·실제 환경 없이 거래나 컨테이너 조치를 수행하지 않음 |

## 발견 및 수정

1. AIOps API·Worker가 Elasticsearch 초기화 완료를 기다리지 않아 최초 로그 인덱스 매핑과 자동 생성이 경쟁할 수 있었습니다. 둘 모두 `elastic-init: service_completed_successfully`에 의존하도록 수정했습니다. 정적 시작 순서 결함을 찾은 것이며 실제 Docker에서 오류를 재현한 것은 아닙니다.
2. INFO 로그 저장에 ingestion_id가 빠져, 재처리 시 저장 문서 ID를 재사용할 수 없었습니다. ERROR와 동일하게 작업 ID를 전달하도록 수정했습니다. API→Worker 경로 검사에서 ID 누락을 검출했고 수정 후 통과했습니다.

## 실제 배포 서버에서 마지막 확인

```sh
git pull origin mingil
docker compose up -d --build
docker compose --profile verification run --rm deployment-check
docker compose --profile verification run --rm deployment-check python -m operations.integration_check --wait-seconds 20
```

첫 번째 검사는 기동·초기화·OOM·실제 자원 제한·readiness를, 두 번째 검사는 공유 로그의 실제 Fluent Bit 전달과 실제 저장소 검색 등을 확인합니다. 두 검사 모두 passed=true여야 해당 검사 범위의 실제 연동 통과로 판단합니다. INFO 표식은 검증용으로 저장되며 조치나 금융 거래는 실행하지 않습니다.

기본 Fluent Bit의 Read_From_Head Off는 DB 체크포인트가 없는 최초 시작에서 기존 파일 내용을 건너뛸 수 있습니다. 실제 연동 검사는 tail 발견 후 새 표식을 추가합니다. 시작 전 생성된 로그까지 수집하려면 읽기 시작 위치와 영속 tail 체크포인트 정책을 별도로 정해야 합니다. 이 수집 정책은 이번 검사에서 변경하지 않았습니다.

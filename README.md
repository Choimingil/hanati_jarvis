# Hanati Jarvis

로그·자원 정보를 수집해 장애 분석과 운영자 승인 기반 조치를 제공하는 AIOps 프로젝트입니다. 모든 서비스 실행은 `docker-compose.yml`에 정의된 이미지로 수행합니다.

## 시작

1. 외부 LLM이나 실행 Agent를 사용할 경우 `.env.example`을 `.env`로 복사하고 필요한 값을 설정합니다. 기본 실행에는 `.env`가 없어도 됩니다.
2. `docker compose up -d --build`로 서비스를 시작합니다.
3. `http://localhost:8080`에서 분석·진단·조치 화면을 확인합니다.

Compose는 `.env` 또는 셸 환경변수의 설정값을 읽으며, 값이 없으면 `docker-compose.yml`의 기본값을 사용합니다. `.env` 파일을 필수로 요구하는 `env_file` 설정은 사용하지 않아 구버전 Compose에서도 검증이 가능합니다. 외부 LLM을 쓰려면 실제 `OPENAI_API_KEY`를 설정하고, 사용하지 않으려면 `LLM_EXTERNAL_ENABLED=false`를 설정합니다. 예제 API 키는 실제 키가 아닙니다.

Redis와 `analysis-worker`가 로그·메트릭 분석을 처리합니다. 수집 API는 HTTP 202와 작업 ID를 반환하며 `/api/v1/analysis/jobs/{job_id}`에서 완료 여부를 확인합니다. 초기 이미지 빌드와 임베딩 모델 다운로드에는 시간이 필요합니다.

장애 목록은 최근 10분에 발생·갱신된 장애를 표시합니다. 진행중·긴급·미확인·분석중 탭으로 조건을 선택하고, 장애명을 누르면 단위시스템·환경·호스트·발생 구간·원문·발생 시각과 해당 장애의 최근 로그를 확인할 수 있습니다. 분석이 완료되지 않은 장애도 상세 정보는 조회할 수 있습니다.

관리자(`/admin`)의 장애 시나리오 선택·실행 영역은 화면 맨 위에 있습니다. 클라이언트(`/client`)의 별도 장애 모니터링 영역은 제거했습니다. 시나리오 시작을 Redis로 공유하고 클라이언트가 1초마다 확인하여, 수집·분석 경로에 장애가 도착하면 목록과 상세를 자동으로 갱신합니다. Fluent Bit의 전송·파일 발견 주기도 1초로 줄였습니다. 일반 목록 갱신은 관리자 2초, 클라이언트 5초이며 시나리오 결과를 기다리는 동안 클라이언트는 1초마다 갱신합니다. 실제 표시까지는 로그 수집·Worker 처리 시간이 필요합니다.

최근 발생 시각이 1분 이내인 장애는 목록·상세의 빨간 테두리와 `최근 1분` 표시로 강조하고, 1분이 지나면 자동으로 해제합니다. 서버 시각을 기준으로 계산하여 브라우저 시계 차이를 보정합니다. 동기화 중에도 사용자가 선택한 탭·장애 상세·입력 중인 조치 정보를 유지합니다.

관리자 ‘로그 조회’의 Redis 탭은 큐 접수·재시도·처리 확인·실패 보관 기록을, Worker 탭은 작업 ID별 분석 시작·완료·소요 시간·오류 및 현재 생존 신호를 보여줍니다. 로그 화면이 열려 있는 동안 2초마다 갱신합니다. 각 로그는 최근 60건을 표시하며, 시나리오 실행 후에는 해당 실행 시점 이후 기록을 조회합니다. 실행 전 검사는 명령 실행 가능 여부를 확인하는 단계로, 통과 후 별도 승인이 필요합니다. 대상 미등록·작업 비활성화·이중화 부족 등의 차단 사유를 화면에 표시합니다. [실행 전 검사·승인 흐름](OPERATIONS.md#실행-전-검사가-실제-조치를-수행하지-않는-이유)에서 상세 내용을 확인할 수 있습니다.

`log-generator`는 기본 `LOG_GENERATOR_MODE=manual`로 공유 로그 파일만 준비하고 대기합니다. 기본 기동만으로 모의 장애를 생성하지 않습니다. 관리자 화면에서 시나리오를 실행하면 기존과 같이 한 번만 발생시킵니다. 연속 무작위 장애 데모가 필요할 때만 `.env`에 `LOG_GENERATOR_MODE=random`을 지정합니다. 생성된 로그는 `environment=simulation`, `synthetic=true`로 표시하여 실제 수집 로그와 구별합니다.

이전 구성에서 기본 기동만으로 DNS·Redis·디스크 등의 장애가 계속 보였던 주된 코드 원인은 무작위 시나리오 생성기입니다. 기동 순서도 Fluent Bit·Collector가 AIOps의 준비 상태를 기다리도록 수정했습니다. Worker의 생존 신호는 분석 처리와 별도로 갱신하므로 긴 임베딩·LLM 처리 중 연결이 끊긴 것으로 표시되는 것을 방지합니다. Collector의 단위시스템은 `hanati-collector`, 환경은 `compose`이며, 수집 범위는 해당 컨테이너에서 보이는 자원입니다.

기존 실행 환경 반영과 실제 컨테이너 오류 확인:

```sh
git pull origin mingil
docker compose stop log-generator
docker compose up -d --build
docker compose restart fluent-bit
docker compose --profile verification run --rm deployment-check
docker compose --profile verification run --rm deployment-check python -m operations.integration_check --wait-seconds 20
```

`.env`에 `LOG_GENERATOR_MODE=random`이 있으면 먼저 `manual`로 변경합니다. 초기화 컨테이너의 정상 상태는 `Exited (0)`이며 반복 실행되는 서비스가 아닙니다. 첫 검사는 기동·readiness 및 실패한 컨테이너의 최근 로그를, 두 번째 검사는 INFO 표식의 실제 전달·저장을 확인합니다. 기존 장애 데이터는 삭제하지 않으며 마지막 발생 이후 10분이 지나면 목록에서 제외됩니다.

## Compose 컨테이너 진단·조치

`execution-targets.example.json`을 `execution-targets.json`으로, `execution_agent/manifest.example.json`을 `agent-manifest.json`으로 복사합니다. `.env`의 `EXECUTION_AGENT_TOKEN`에 32자 이상의 무작위 값을 설정한 뒤 `docker compose --profile execution up -d --build`를 실행합니다. Agent도 기존 `hanati-aiops:local` 이미지를 사용합니다.

예제 작업은 기본적으로 비활성화되어 있습니다. 컨테이너·Compose 서비스·이미지·환경을 검토하고 허용할 작업만 활성화합니다. 지원하는 내장 작업은 Docker 상태 조회와 재시작입니다. 호스트 명령이나 컨테이너 셸 스크립트는 실행하지 않습니다. 재시작은 건강한 이중화 컨테이너, 점검 상태, 실행 전 상태 복원 가능성을 확인한 뒤 허용합니다. 기본 단일 컨테이너 구성에서는 이중화 검사 때문에 재시작이 차단됩니다.

현재 복구 검사는 Jarvis 컨테이너의 health 상태와 로그 접수·worker 처리 경로를 검증합니다. 다른 금융 업무 서비스의 거래 복구까지 검증하는 기능은 추가 구현이 필요합니다. 상세 설정과 제한은 [운영 안내](OPERATIONS.md)를 참고하세요.

## 반영된 1차 개선

- 추천과 실행 대상의 환경·서비스·인스턴스 결합, 사전 검증 및 승인 만료 확인
- 재시작 전 이중화·점검·상태 복원 검사
- Redis 분산 잠금과 Agent 영속 실행 기록을 통한 중복 실행 방지
- 명령 완료와 업무 경로 복구 확인 분리
- 별도 분석 worker, 재시도 및 실패 작업 기록
- 수집 누락·지연·권한 부족과 서비스 상태 표시
- 저장·응답·LLM 입력의 민감 정보 마스킹, 화면 출력 이스케이프

로그인·사용자 권한 관리(1번)는 요청에 따라 제외했습니다. 운영 화면과 API 접근 제한은 배포 환경에서 설정해야 합니다.

[구조](ARCHITECTURE.md) · [운영](OPERATIONS.md) · [검증](TESTING.md)

업무 개선으로 서비스 중요도·피해 지표에 따른 P1~P3 우선순위, 반복 오류 분석 재사용, 읽기 전용 업무 KPI 복구 검사, 기존 이미지 기반 짧은 기동·부하 검사 도구를 추가했습니다. 실제 업무 API와 기준은 설정이 필요하며 [운영 안내](OPERATIONS.md)에 예제가 있습니다.


미사용 예제와 독립 LLM HTTP 서버 코드는 [보관 설명](old/unused-2026-10-06/README.md)에 보존하고 활성 경로에서 제거했습니다. LLM은 Worker가 직접 호출합니다. Collector와 ES 초기화는 Compose에 정의된 전용 이미지에서 의존성을 빌드 시 설치합니다. 상시 메모리 상한은 Agent 포함 5632MiB(5.5GiB)입니다.


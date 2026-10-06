# Hanati Jarvis

로그·자원 정보를 수집해 장애 분석과 운영자 승인 기반 조치를 제공하는 AIOps 프로젝트입니다. 모든 서비스 실행은 `docker-compose.yml`에 정의된 이미지로 수행합니다.

## 시작

1. `.env.example`을 `.env`로 복사하고 필요한 값을 설정합니다.
2. `docker compose up -d --build`로 서비스를 시작합니다.
3. `http://localhost:8080`에서 분석·진단·조치 화면을 확인합니다.

Redis와 `analysis-worker`가 로그·메트릭 분석을 처리합니다. 수집 API는 HTTP 202와 작업 ID를 반환하며 `/api/v1/analysis/jobs/{job_id}`에서 완료 여부를 확인합니다. 초기 이미지 빌드와 임베딩 모델 다운로드에는 시간이 필요합니다.

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

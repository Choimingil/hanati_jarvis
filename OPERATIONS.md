# 운영 안내

## 실행과 설정

기본 서비스는 `docker compose up -d --build`로 실행합니다. 선택적 실행 Agent는 `docker compose --profile execution up -d --build`로 함께 실행합니다. 별도 호스트 설치·실행 스크립트는 없습니다.

Agent 사용 전 다음을 준비합니다.

- `.env`: `EXECUTION_AGENT_TOKEN`에 32자 이상의 무작위 비밀 값 설정
- `execution-targets.json`: 예제의 대상 식별자, Agent URL, `token_env` 확인
- `agent-manifest.json`: 예제 복사 후 허용 대상·이미지·작업만 설정

등록 파일과 실제 Agent의 host/environment/service/instance는 일치해야 합니다. 예제의 host는 Compose에 지정한 Agent hostname `jarvis-compose-node`입니다. `scope: compose`인 내부 주소 `http://execution-agent:8090`만 내부 HTTP 예외를 허용합니다. 그 밖의 원격 Agent는 HTTPS가 필요합니다. 실제 비밀 값과 정책 파일은 Git 및 이미지 빌드에 포함하지 않습니다.

예제는 `hanati-aiops:local`의 `hanati-aiops` 컨테이너를 대상으로 하며 모든 작업이 비활성화되어 있습니다. 조회 작업을 활성화하면 Docker 상태 진단을 사용할 수 있습니다. 재시작을 활성화하려면 `redundancy_peers`에 실제 같은 프로젝트·서비스·승인 이미지의 건강한 별도 컨테이너를 등록해야 합니다. 단일 컨테이너 Compose 기본 구성은 재시작 조건을 충족하지 않습니다. 예제 대상을 무관한 금융 업무 서비스로 바꾸는 것만으로 업무 검사가 지원되지는 않습니다.

## 승인과 복구

화면에서 대상을 선택하고 사전 검증을 실행합니다. 이중화·점검 라벨(`jarvis.maintenance`)·상태 복원 가능성·기존 실행 잠금·정책 해시를 확인한 뒤 승인할 수 있습니다. 만료·변경된 추천 또는 사전 검증은 다시 수행해야 합니다.

재시작 완료는 incident를 `MONITORING`으로 옮기며 복구를 확정하지 않습니다. 복구 확인은 컨테이너 health와 무해한 INFO 이벤트의 접수/분석 완료를 두 차례 확인합니다. 성공해야 `RESOLVED`로 전환되고 대상 잠금이 해제됩니다. 현재 구현은 Jarvis 처리 경로 검사이며 실제 결제·계정계 거래 검사는 아닙니다.

재시작 실패 시 동일 이미지의 실행 전 runtime 상태 복원을 시도합니다. 교체된 컨테이너, 불확실한 통신 결과 또는 복원 실패에는 자동 재실행을 하지 않습니다. 상태 복원은 배포 버전이나 업무 데이터 롤백이 아닙니다.

응답 유실 시 화면에서 실행 결과를 새로 조회합니다. Agent journal에서 계속 불확실한 실행은 관리자가 Docker 상태와 작업 종료를 확인한 뒤 실행 Agent 이미지 안에서 `python -m execution_agent.reconcile EXECUTION_ID --observed-status failed --reason '확인 근거' --confirm-operations-stopped`를 수행할 수 있습니다. journal에 실행 자체가 없으면 원래 요청 JSON을 `--request-file`로 제공해야 하며 실패 tombstone만 생성할 수 있습니다. 이후 중앙 결과를 새로 조회합니다. 성공으로 정리해도 복구 확인은 별도로 필요합니다.

## 데이터와 장애 확인

`/api/v1/operations/status`에서 저장소, worker heartbeat, 작업 대기·실패, 호스트별 마지막 메트릭과 신선도를 확인합니다. 기본 신선도 기준은 120초입니다. collector 기본 구성의 메트릭은 collector 컨테이너가 보는 자원이며 물리 서버 전체를 보장하지 않습니다. Agent의 논리적 host와 메트릭 host가 다르면 누락으로 표시될 수 있으므로 실제 수집 식별자를 맞춰 운영해야 합니다.

Redis AOF와 Agent SQLite volume을 유지해야 중복 실행 방지 기록이 보존됩니다. 볼륨 삭제나 Redis 복구 시 기록 손실을 확인한 뒤 조치를 재개합니다. 분석 실패 작업은 3회 후 실패 기록으로 이동하며 자동 무한 재시도하지 않습니다. 저장소 장애는 503 또는 실행 미확정 상태로 표시합니다.

`LLM_EXTERNAL_ENABLED=false`로 외부 LLM을 차단할 수 있습니다. 기본 마스킹 규칙은 비밀번호·토큰·주민번호·카드/계좌 형태·전화·이메일 등이며 조직 정책에 맞게 확장해야 합니다. 로그인/RBAC는 이번 변경에 포함되지 않습니다. Docker socket과 정책 파일을 수정할 수 있는 사용자는 호스트 제어 권한을 갖는 것으로 취급해야 합니다.

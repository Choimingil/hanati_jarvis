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

## 8GB·2코어 배포 자원 설정

Compose에 서비스별 `mem_limit`, `memswap_limit`, `cpus`를 지정했습니다. 메모리는 예약량이 아닌 상한이며, 메모리와 swap 합계 상한을 동일하게 설정해 컨테이너의 swap 사용을 차단합니다. 제한 초과 시 해당 컨테이너에서 OOM 종료가 발생할 수 있으므로 실제 부하를 측정하며 조정해야 합니다.

| 서비스 | 메모리 상한(MiB) | CPU 상한(코어 환산) |
|---|---:|---:|
| Elasticsearch | 1536 | 0.65 |
| Qdrant | 512 | 0.30 |
| AIOps API | 1024 | 0.40 |
| 분석 Worker | 1536 | 0.75 |
| Redis | 384 | 0.20 |
| LLM Agent | 256 | 0.15 |
| 실행 Agent(선택) | 192 | 0.15 |
| Collector | 192 | 0.10 |
| Fluent Bit | 128 | 0.10 |
| 로그 생성기 | 128 | 0.05 |
| Elasticsearch 초기화(일회성) | 256 | 0.35 |
| Qdrant 초기화(일회성) | 1536 | 0.75 |

초기화 서비스를 제외한 상한 합계는 실행 Agent 포함 5888MiB(5.75GiB)입니다. 서버 RAM이 8GiB인 경우 산술적으로 2.25GiB를 OS·Docker 등의 여유로 남기는 계획이며 실제 가용량은 서버 표시값과 다른 프로세스에 따라 달라집니다. Qdrant 초기화는 완료 후 종료되고 API·Worker는 완료를 기다리므로 초기화 한도를 상시 사용량에 더하지 않습니다. Elasticsearch 초기화는 별도로 완료 여부를 확인합니다. 여러 초기화를 수동으로 동시에 재실행하면 이 여유 계획을 벗어날 수 있습니다.

CPU 상한 합계는 2코어보다 크며 동시 부하에서는 호스트 스케줄러가 2코어를 나눕니다. 서비스별 폭주를 제한하되 CPU의 일부를 OS에 보장하는 설정은 아닙니다. 임베딩의 OpenMP·MKL·OpenBLAS 스레드는 1개로 제한하고 토크나이저 병렬 처리를 끕니다. 분석 Worker는 현재 기본 1개를 유지합니다.

Redis는 데이터 최대 메모리 128MiB와 `noeviction`을 사용합니다. 실행 잠금·기록을 공간 확보 목적으로 삭제하지 않고, 한도에 도달하면 쓰기 요청을 거부합니다. AOF·프로세스 오버헤드·재작성 여유 때문에 컨테이너 메모리 상한을 더 크게 잡았습니다. 수집 API는 큐 쓰기 실패 시 503을 반환하고 Worker 처리가 지연될 수 있으므로 Redis 사용량과 작업 적체를 확인해야 합니다. 미완료 작업과 영속 실행 기록은 자동 삭제되지 않습니다.

배포 서버에서 새 구성을 적용하려면 `git pull origin mingil` 후 `docker compose up -d --build`를 실행합니다. Agent를 사용하는 경우 `docker compose --profile execution up -d --build`를 사용합니다. 데이터 volume은 삭제하지 않습니다. 런타임 제한은 이미지 빌드에는 적용되지 않으며 빌드·모델 다운로드는 별도의 CPU·메모리·네트워크 부하를 만들 수 있습니다.

적용 확인은 `docker stats --no-stream`으로 하고, `docker inspect hanati-aiops --format '{{.HostConfig.Memory}} {{.HostConfig.MemorySwap}} {{.HostConfig.NanoCpus}}'`로 실제 한도를 확인합니다. 서버의 `free -h`, 컨테이너 OOM 상태, 수집 신선도와 분석 대기열을 함께 관찰합니다. 이 설정은 측정 전 시작값으로, 실제 트래픽을 처리할 수 있다는 성능 보장은 아닙니다.

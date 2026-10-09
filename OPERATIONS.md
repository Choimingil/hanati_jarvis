# 운영 안내

## 실행과 설정

기본 서비스는 `docker compose up -d --build`로 실행합니다. 선택적 실행 Agent는 `docker compose --profile execution up -d --build`로 함께 실행합니다. 별도 호스트 설치·실행 스크립트는 없습니다.

Agent 사용 전 다음을 준비합니다.

- `.env`: `EXECUTION_AGENT_TOKEN`에 32자 이상의 무작위 비밀 값 설정
- `execution-targets.json`: 예제의 대상 식별자, Agent URL, `token_env` 확인
- `agent-manifest.json`: 예제 복사 후 허용 대상·이미지·작업만 설정

등록 파일과 실제 Agent의 host/environment/service/instance는 일치해야 합니다. 예제의 host는 Compose에 지정한 Agent hostname `jarvis-compose-node`입니다. `scope: compose`인 내부 주소 `http://execution-agent:8090`만 내부 HTTP 예외를 허용합니다. 그 밖의 원격 Agent는 HTTPS가 필요합니다. 실제 비밀 값과 정책 파일은 Git 및 이미지 빌드에 포함하지 않습니다.

예제는 `hanati-aiops:local`의 `hanati-aiops` 컨테이너를 대상으로 하며 모든 작업이 비활성화되어 있습니다. 조회 작업을 활성화하면 Docker 상태 진단을 사용할 수 있습니다. 재시작을 활성화하려면 `redundancy_peers`에 실제 같은 프로젝트·서비스·승인 이미지의 건강한 별도 컨테이너를 등록해야 합니다. 단일 컨테이너 Compose 기본 구성은 재시작 조건을 충족하지 않습니다. 예제 대상을 무관한 금융 업무 서비스로 바꾸는 것만으로 업무 검사가 지원되지는 않습니다.

## 시나리오의 기존 셸 스크립트 실행

`test-runbooks/catalog.json`은 기존 커밋 `245c9fa4b8b9d2bc562a0023a5bc738dfac88cd9`에서 복원한 셸 스크립트 58개의 종류·경로·SHA-256을 등록합니다. `config.ERROR_RULES`의 장애별 매핑을 사용하며 20개 시나리오 중 19개에는 대응 스크립트가 있습니다. `RATE_LIMIT_EXCEEDED`는 대응 스크립트가 없어 수동 등록으로 진행합니다.

등록 스크립트 실행 대상은 `synthetic=true`, `simulation / order-api`인 해당 장애의 호스트에만 연결됩니다. 기존 추천을 조회할 때도 현재 등록 대상을 다시 연결하며 추천 ID·버전·유효 시간 검증을 유지합니다. 리소스 분석으로 전환된 시나리오 장애도 기존 등록 스크립트를 선택할 수 있습니다. 추가된 등록 스크립트는 평가되지 않은 항목으로 표시합니다.

Runbook의 `log-generator-scripts` 대상을 선택한 뒤 승인하면 API 컨테이너에서 원본 `.sh` 파일을 실행합니다. 기존 조치 스크립트는 출력·짧은 대기만 수행하며 실제 DB·Redis·애플리케이션을 변경하지 않습니다. 진단도 테스트 출력이고 `check_disk_usage.sh`의 `df`만 API 컨테이너 파일시스템을 읽습니다. 실행 인자·환경에 입력한 조치 방법이나 인증 정보를 넣지 않습니다. 파일 누락·변경·종류 불일치는 실행 대상을 제공하지 않거나 실행을 차단합니다. 제한 시간은 10초이며 결과 출력은 스트림별 8,000자입니다.

등록 스크립트 실행도 중앙 Redis 예약·중복 요청 보호와 SQLite 영수증을 사용합니다. API의 `scenario-script-state` volume(`/state/scenario-scripts`)을 보존합니다. `SCENARIO_SCRIPT_STATE_DIR`로 다른 영속 경로를 설정할 수 있습니다. 별도 실행 Agent나 Docker socket은 필요하지 않습니다. 명령 완료 후 ‘스크립트 결과 확인’으로 스크립트 정상 종료와 등록 파일 상태를 확인합니다. 결과는 `execution_mode=simulation`이며 실제 업무 복구 검사·운영 성공 통계와 구분합니다.

## 수동 조치 등록

장애 상세에서 실행 대상이 없는 항목에 ‘수동 조치 등록’을 표시합니다. 외부에서 조치를 수행한 뒤 수행 완료를 체크하고, 조치 방법과 운영자를 입력하여 등록합니다. 단위시스템·환경·호스트·장애 코드·등록 시각과 함께 장애 문서의 `manual_actions`에 저장되며 새로고침·서비스 재기동 후에도 이력을 조회할 수 있습니다. 같은 장애가 재발해도 기존 이력을 유지합니다. 입력한 방법은 기록 데이터로만 저장합니다.

복구 확인을 미체크하면 `MONITORING`으로 옮기고 추가 확인 방법을 등록할 수 있습니다. 운영자가 복구를 직접 확인했다고 체크하면 `RESOLVED`로 처리하고 `recovery_confirmation=operator_report`를 기록합니다. 자동 검사를 수행했다고 표시하지 않습니다. 자동 실행 중이거나 자동 실행의 복구 확인을 기다리는 장애는 이 등록으로 우회하지 않습니다.

`POST /api/v1/remediations/manual`에는 `incident_id`, 현재 `incident_version`, 재시도에서 유지할 `registration_id`, `operator`, `method`, `performed=true`, boolean `recovered`가 필요합니다. 동일 요청은 기존 등록 결과를 반환하며, 같은 ID로 다른 내용을 보내거나 버전 충돌·필수값 누락이면 409입니다. 입력 중인 값은 일반 새로고침에서 유지합니다. 조치 방법은 8,000자, 운영자는 200자, 장애별 이력은 100건으로 제한하며 민감정보를 마스킹합니다.

## 승인과 복구

화면에서 대상을 선택하고 ‘승인 후 실행’을 누릅니다. 별도 실행 전 검사 단계 없이 승인 요청 안에서 이중화·점검 라벨(`jarvis.maintenance`)·상태 복원 가능성·기존 실행 잠금·정책 해시를 확인하여 명령을 실행합니다. 만료·변경된 추천은 최신 장애 상세에서 다시 불러와야 합니다.

재시작 완료는 incident를 `MONITORING`으로 옮기며 복구를 확정하지 않습니다. 복구 확인은 컨테이너 health와 무해한 INFO 이벤트의 접수/분석 완료를 두 차례 확인합니다. 성공해야 `RESOLVED`로 전환되고 대상 잠금이 해제됩니다. 현재 구현은 Jarvis 처리 경로 검사이며 실제 결제·계정계 거래 검사는 아닙니다.

재시작 실패 시 동일 이미지의 실행 전 runtime 상태 복원을 시도합니다. 교체된 컨테이너, 불확실한 통신 결과 또는 복원 실패에는 자동 재실행을 하지 않습니다. 상태 복원은 배포 버전이나 업무 데이터 롤백이 아닙니다.

응답 유실 시 화면에서 실행 결과를 새로 조회합니다. Agent journal에서 계속 불확실한 실행은 관리자가 Docker 상태와 작업 종료를 확인한 뒤 실행 Agent 이미지 안에서 `python -m execution_agent.reconcile EXECUTION_ID --observed-status failed --reason '확인 근거' --confirm-operations-stopped`를 수행할 수 있습니다. journal에 실행 자체가 없으면 원래 요청 JSON을 `--request-file`로 제공해야 하며 실패 tombstone만 생성할 수 있습니다. 이후 중앙 결과를 새로 조회합니다. 성공으로 정리해도 복구 확인은 별도로 필요합니다.

## 데이터와 장애 확인

### 오류 상세의 완료 상태

| 저장된 장애 상태 | 상세 표시 | 처리 기준 |
|---|---|---|
| `MONITORING` | 조치 완료 · 복구 확인 대기 | 명령 또는 수동 조치 완료, 복구 확인 필요 |
| `RESOLVED` | 처리 완료 | 등록된 복구 검사 또는 운영자의 복구 확인 완료 |

상세 상단에 완료 시각·처리 운영자·조치 내용·확인 방식을 함께 표시합니다. 자동 조치의 마지막 실행 요약을 장애 문서에 보존하며 기존 건은 실행 이력에서 복원합니다. 조회 실패 시 저장된 완료 상태를 유지하고 이력 조회 지연을 알립니다. 완료 후에도 선택한 상세는 닫히지 않으며 최근 10분의 ‘처리 완료 이력’에서 다시 선택할 수 있습니다.

완료된 조치는 다시 실행하거나 복구 확인을 반복하도록 제안하지 않습니다. `REOPENED` 또는 조치 실패 상태에서는 과거 성공 이력으로 현재 장애를 완료 표시하지 않습니다. 이전 수동 조치 이력도 새 자동 조치의 운영자·방법을 덮어쓰지 않습니다.

화면의 장애 시나리오·등록 스크립트 실행·스크립트 결과 확인 문구와 실제 업무 복구 확인은 각각의 결과를 표시합니다. `simulation` 환경 값과 `synthetic` 분류는 기존 데이터·대상 결합을 위해 유지하고 환경 표시는 ‘시나리오’로 표시합니다. 출력용 스크립트의 파일 확인으로 실제 운영 서비스 복구를 검사했다고 표시하지 않습니다. 실제 운영 대상에는 환경·서비스·호스트가 일치하는 Agent 및 승인할 Compose 작업·복구 검사를 설정합니다.

### 대상 선택과 승인 및 복구 확인

1. 추천에 연결된 대상을 선택합니다. 장애·추천의 ID, 버전, 유효 시간과 허용 조치가 일치하고 실제 장애 상태가 `ACTION_REQUIRED`여야 합니다. 등록 테스트 스크립트가 있는 시나리오 장애는 `INVESTIGATING`에서도 명시적으로 승인할 수 있습니다.
2. 대상을 선택하면 ‘승인 후 실행’이 활성화됩니다. 승인 요청은 `/api/v1/remediations/approve`로 바로 전송하며 사용자가 별도 검사나 검사 증명을 준비할 필요가 없습니다.
3. 서버가 승인 요청 안에서 대상 환경·서비스·호스트·인스턴스 결합, 실행 Agent 인증·정책, 실제 Compose 컨테이너·승인 이미지, 이중화·점검·실행 상태 복원·기존 실행 잠금을 확인합니다. Agent 응답 중 장애가 갱신될 수 있어 최신 추천을 다시 확인한 뒤 실행을 예약하고 명령을 보냅니다. Agent도 실행 직전에 조건을 확인합니다. 서버의 승인 조건 확인에서 차단되면 실제 이유를 표시하며 명령과 실행 예약을 생성하지 않습니다.
4. 명령 성공은 `MONITORING` 상태입니다. ‘업무 복구 확인’에서 컨테이너 health 및 등록된 복구 경로를 확인해야 `RESOLVED`로 바뀝니다. 기본 복구 검사는 Jarvis 로그 접수·Worker 처리 경로이며 외부 금융 업무 거래를 대신 검증하지 않습니다.

기본 장애 시나리오는 `simulation / order-api / web01 / log-generator-scripts`의 기존 테스트 셸 스크립트로 연결합니다. 실제 Agent 대상은 `execution-targets.json`의 환경·서비스·호스트가 일치해야 하며 `scripts` 배열을 선택적으로 지정해 대상의 허용 스크립트 ID를 제한할 수 있습니다. 실제 대상이 없으면 수동 조치 등록을 제공합니다. 예제 Agent 작업은 `enabled=false`이고, 실행 Agent는 선택 프로필입니다. 기본 단일 컨테이너의 실제 재시작은 이중화 조건에서 차단됩니다.

승인 시 조건이 충족되지 않으면 화면에서 실제 사유를 확인하고 설정·대상·최신 추천을 확인한 뒤 다시 승인합니다. 요청 처리 중에는 대상 변경·중복 클릭을 막습니다. 기존 실행 ID에 대한 재요청은 기존 결과를 반환하므로 명령을 다시 실행하지 않습니다. Agent의 작업 비활성화·인증 거절도 차단 사유로 전달합니다.

### 시나리오 후속 UNKNOWN 메시지 제외

시나리오의 핵심 ERROR 뒤에 후속 상태·영향 설명도 ERROR로 기록되어 각각 별도 UNKNOWN 장애가 생성되고 있었습니다. `Unable to write application data.`, `Service entering read-only mode.` 등 현재 20개 시나리오의 후속 문장 39개는 수집 로그로만 보존하고 별도 장애·추천·LLM 분석을 만들지 않습니다. 대소문자·공백·마침표 차이를 보정하고, `synthetic=true`인 미등록 시나리오 오류도 같은 방식으로 처리합니다.

기존 후속 UNKNOWN 장애는 목록·탭 건수에서 제외하며 저장된 원문·장애 이력은 삭제하지 않습니다. `No space left on device.` 등의 인식되는 핵심 오류는 계속 탐지합니다. 이 후속 메시지 목록과 관계없는 실제 미등록 오류의 리소스 분석은 유지합니다.

### Redis·Worker 수집·분석 로그

관리자 ‘로그 조회’에서 Redis·Worker 탭을 선택합니다. Redis는 현재 연결·스트림 잔여량·전달/처리 확인 대기·최종 실패 건수와 접수·재시도·큐 제거 기록을 표시합니다. Worker는 현재 생존 신호와 작업 ID·종류·대상·시도 횟수·처리 결과·소요 시간·오류 종류를 표시합니다. 기본 조회 구간은 최근 5분이며 시나리오 실행 후에는 실행 시점 이후의 각 소스 최근 60건을 표시합니다. 화면이 열려 있는 동안 2초마다 갱신하며 로그 내용은 마스킹합니다.

새 활동 기록은 Redis에 소스별 최대 1,000건, 마지막 기록 이후 1시간의 만료를 적용합니다. 기존 작업 영수증·분석 스트림·실행 잠금의 보존 정책과 별개입니다. 로그 기록 실패로 이미 접수·처리한 작업을 실패로 바꾸지 않습니다. 업데이트 이전 기록은 소급 생성하지 않습니다.

이 탭은 실제 애플리케이션의 큐·Worker 활동 기록이며 Redis 서버 및 Docker stdout 전체를 가져오는 기능은 아닙니다. Redis가 중단되면 그 저장소의 활동 기록도 저장·조회할 수 없습니다. 장애 중 프로세스 로그 전체가 필요하면 `docker compose logs --tail=100 redis analysis-worker`로 확인합니다. 저장소별 조회 실패는 해당 탭에 표시하고 나머지 로그는 계속 조회합니다.

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
| 실행 Agent(선택) | 192 | 0.15 |
| Collector | 192 | 0.10 |
| Fluent Bit | 128 | 0.10 |
| 로그 생성기 | 128 | 0.05 |
| Elasticsearch 초기화(일회성) | 256 | 0.35 |
| Qdrant 초기화(일회성) | 1536 | 0.75 |

초기화 서비스를 제외한 상한 합계는 실행 Agent 포함 5632MiB(5.5GiB)입니다. 서버 RAM이 8GiB인 경우 산술적으로 2.5GiB를 OS·Docker 등의 여유로 남기는 계획이며 실제 가용량은 서버 표시값과 다른 프로세스에 따라 달라집니다. Qdrant 초기화는 완료 후 종료되고 API·Worker는 완료를 기다리므로 초기화 한도를 상시 사용량에 더하지 않습니다. Elasticsearch 초기화는 별도로 완료 여부를 확인합니다. 여러 초기화를 수동으로 동시에 재실행하면 이 여유 계획을 벗어날 수 있습니다.

CPU 상한 합계는 2코어보다 크며 동시 부하에서는 호스트 스케줄러가 2코어를 나눕니다. 서비스별 폭주를 제한하되 CPU의 일부를 OS에 보장하는 설정은 아닙니다. 임베딩의 OpenMP·MKL·OpenBLAS 스레드는 1개로 제한하고 토크나이저 병렬 처리를 끕니다. 분석 Worker는 현재 기본 1개를 유지합니다.

Redis는 데이터 최대 메모리 128MiB와 `noeviction`을 사용합니다. 실행 잠금·기록을 공간 확보 목적으로 삭제하지 않고, 한도에 도달하면 쓰기 요청을 거부합니다. AOF·프로세스 오버헤드·재작성 여유 때문에 컨테이너 메모리 상한을 더 크게 잡았습니다. 수집 API는 큐 쓰기 실패 시 503을 반환하고 Worker 처리가 지연될 수 있으므로 Redis 사용량과 작업 적체를 확인해야 합니다. 미완료 작업과 영속 실행 기록은 자동 삭제되지 않습니다.

배포 서버에서 새 구성을 적용하려면 `git pull origin mingil` 후 `docker compose up -d --build`를 실행합니다. Agent를 사용하는 경우 `docker compose --profile execution up -d --build`를 사용합니다. 데이터 volume은 삭제하지 않습니다. 런타임 제한은 이미지 빌드에는 적용되지 않으며 빌드·모델 다운로드는 별도의 CPU·메모리·네트워크 부하를 만들 수 있습니다.

적용 확인은 `docker stats --no-stream`으로 하고, `docker inspect hanati-aiops --format '{{.HostConfig.Memory}} {{.HostConfig.MemorySwap}} {{.HostConfig.NanoCpus}}'`로 실제 한도를 확인합니다. 서버의 `free -h`, 컨테이너 OOM 상태, 수집 신선도와 분석 대기열을 함께 관찰합니다. 이 설정은 측정 전 시작값으로, 실제 트래픽을 처리할 수 있다는 성능 보장은 아닙니다.

## 업무 영향 우선순위와 반복 장애

`business-services.example.json`을 `business-services.json`으로 복사하고 실제 환경·서비스명, 중요도(`tier1` 등), 긴급 기준을 설정합니다. 현재 예제는 설명용이며 자동으로 운영 정책에 적용되지 않습니다. 로그에는 선택적으로 다음 보고 정보를 포함할 수 있습니다.

```json
{"business_impact":{"failed_transactions":100,"affected_customers":20,"failure_rate":0.12,"p95_latency_ms":6000,"service_available":false}}
```

실패율은 0~1, 응답 시간은 ms입니다. 입력값은 확인된 사실이 아닌 보고 근거로 표시합니다. 기본적으로 핵심 업무 또는 거래/고객 피해는 P2, 업무 중단 또는 긴급 기준 초과는 P1, 영향 미확인은 P3입니다. 횟수만으로 업무 중단을 확정하지 않습니다. 현재 우선순위는 분석 큐의 순서를 재배치하지 않고 운영 화면과 추천에 표시합니다. 조직별 기준은 운영자가 검토해야 합니다.

같은 환경·서비스·정규화 메시지·오류 코드의 로그는 기존 사건에 집계합니다. 최근 300초 내 분석이고 추천이 아직 유효하면 신규 분석/추천을 생략합니다. 발생 수와 마지막 발생·업무 영향은 갱신하며 단순 반복으로 승인 버전을 무효화하지 않습니다. 새 호스트, 우선순위 상승, 추천 만료, 분석 재검토 주기 경과 또는 해결 후 재발은 다시 분석합니다. 조치·복구 관찰 중에는 새 추천을 만들지 않습니다. 원문 로그와 개별 작업 접수증은 보존하므로 큐/저장 비용까지 없어지는 것은 아닙니다. 별도 외부 알림 발송은 이번 변경에 없습니다.

## 읽기 전용 업무 복구 검사

Agent 작업에 `business_probe: "http_kpi"`와 `business_recovery`를 설정하면 업무 상태 API를 GET으로 조회합니다. manifest의 `business_recovery_example`은 참고용이며 활성 정책이 아닙니다. 실제 연동 시 해당 내용을 `business_recovery`로 옮기고 실제 URL·허용 호스트·환경·서비스·지표 기준·비밀 환경변수를 설정해야 합니다. 예제 도메인은 호출 가능한 업무 API가 아닙니다. Agent 대상의 service/environment와 검사 정책의 expected_service/expected_environment가 일치해야 합니다.

API 응답 예시는 다음과 같습니다.

```json
{
  "service":"payment-api",
  "environment":"production",
  "sampled_at":"2026-10-06T07:10:30Z",
  "window_started_at":"2026-10-06T07:10:00Z",
  "success_rate":0.999,
  "failure_rate":0.001,
  "p95_latency_ms":100,
  "transactions":100
}
```

`window_started_at`부터 `sampled_at`까지 집계된 실제 거래 지표를 제공해야 합니다. 집계 구간은 조치 **완료 후** 시작하고, 표본은 기본 120초 이내여야 합니다. 타임존 없는 시간, 미래·과거 표본, 미달 거래 수, 잘못된 업무 식별자, 미달 성공률 또는 초과 실패율/응답 시간은 복구 실패로 처리합니다. 동일 조건을 두 차례 확인하고 Docker running/health도 함께 통과해야 incident를 해결합니다. URL은 관리자 허용 목록과 일치해야 하고 리다이렉트는 따라가지 않습니다. HTTPS를 기본으로 하며 내부 HTTP가 필요할 때만 `allow_internal_http: true`를 명시합니다. 토큰은 `.env`의 지정 환경변수로 전달합니다.

업무 정책 누락 또는 API 조회 실패는 복구 확인 실패입니다. 현재 기본 `jarvis_pipeline`은 Jarvis 자체 처리 경로만 검증합니다. 금융 서비스에 해당 모드를 사용해 거래 복구를 확인했다고 판단하면 안 됩니다. 실제 거래 API, 계정, 조직 임계값은 제공되지 않았으므로 이번 변경에는 읽기 전용 연동 기능과 예제만 포함합니다. 일시 중단 허용 정책은 이번 1~4번 범위에 없으므로 단일 인스턴스 재시작 제한은 유지됩니다.

## 짧은 배포·부하 확인

검증도 기존 `hanati-aiops:local` 이미지의 `verification` profile로 실행합니다. 별도 호스트 실행 스크립트나 신규 이미지는 필요하지 않습니다. 실제 Docker socket을 조회하므로 신뢰할 수 있는 관리자만 실행하며, read-only mount가 Docker API 권한을 제한해 주는 것은 아닙니다. 검사 모듈은 Docker 변경 API를 호출하지 않습니다.

```sh
# 기동·초기화 종료 코드·OOM·실제 CPU/메모리 제한·API/worker readiness 확인
# 최대 대기 구간 30초, 조회 실패 시 종료 코드 1
docker compose --profile verification run --rm deployment-check
# 실행 Agent까지 점검할 때
docker compose --profile execution --profile verification run --rm deployment-check python -m operations.deployment_check --include-agent
# 명시적으로 실행하는 10/50/100건 반복 오류 검사: 단계별 60초 제한
docker compose --profile verification run --rm deployment-check python -m operations.load_check --counts 10 50 100 --deadline-seconds 60
```

부하 검사는 `validation` 환경·`jarvis-load-validation` 서비스의 합성 ERROR 로그를 전송합니다. 같은 오류 집계와 접수/완료 시간을 확인하는 검사이며 서로 다른 100개 장애의 LLM 처리량 측정은 아닙니다. 운영 대상과 동일한 검증용 서비스명을 등록하지 마세요. 실제 조치를 승인하지 않지만 ERROR 분석에 따른 외부 LLM 호출 비용이 발생할 수 있습니다. 타임아웃 시 다음 단계로 진행하지 않으며 이미 접수한 작업은 Worker가 계속 처리합니다. 결과와 `docker stats`, 저장소 여유, 대기열을 함께 확인하세요. 검사용 컨테이너는 실행 중에만 추가 128MiB 상한을 사용합니다.

기동 검사 통과 후 별도의 점검 시간에 `docker compose restart aiops analysis-worker`로 재기동하고 같은 기동 검사를 반복해 확인할 수 있습니다. 이 명령은 서비스 중단을 수반하므로 실제 서버에서 자동으로 실행하지 않습니다. 현재 작업 환경에는 Docker 실행 환경이 없어 실 서버 기동·부하 수치는 측정하지 않았습니다.


## 미사용 정리와 최적화 적용

보관 원본과 미사용 구간은 `old/unused-2026-10-06/README.md`에 있습니다. old는 Docker 빌드에서 제외하며 자동 실행하지 않습니다. 사용 중인 LLMService·fallback 랭커·자원 비교 클래스는 삭제하지 않습니다. 독립 LLM Agent를 제거해 API→LLM Agent 통신 없이 Worker가 직접 외부 LLM을 호출합니다. 기존 배포에서 남은 `hanati-llm-agent` 컨테이너는 배포 관리자가 중지·정리해야 합니다.

Collector/ES 초기화는 각각 Compose의 `hanati-collector:local`, `hanati-elastic-init:local` 이미지로 변경했습니다. 패키지는 빌드 시 설치하므로 정상 시작 때마다 pip 설치를 반복하지 않습니다. 새 Dockerfile 적용을 위해 전체 `docker compose up -d --build`가 필요합니다. 실행 Agent는 기존 프로필 방식으로 실행합니다.

Qdrant와 Elasticsearch 사례 초기화는 이미 채워진 데이터가 있으면 건드리지 않습니다. Qdrant 스키마가 다르면 삭제 대신 오류로 종료합니다. 사례를 바꾸려면 별도의 관리 절차로 수행해야 합니다. 초기화가 일부 완료된 비어 있지 않은 저장소에도 자동 덮어쓰기를 하지 않으므로 최초 초기화 오류 시 데이터 상태를 확인하세요.

메트릭 보존은 Worker 유지보수 스레드에서 기본 14일 기준으로 시작하고 24시간마다 수행합니다. `.env`에서 `METRICS_RETENTION_ENABLED=false`로 끌 수 있고 보관 기간·주기도 기존 환경변수로 설정합니다. 삭제는 메트릭 인덱스만 대상으로 합니다. Redis 잠금과 최근 실행 기록은 삭제하지 않습니다. 30일 지난 dead-letter와 90일 지난 감사 스트림은 분당 최대 100건씩 ES `jarvis-dead-letters`, `jarvis-audit`에 저장한 뒤 Redis에서 제거하며 ES 실패 시 원본을 유지합니다. 이 ES 아카이브의 장기 보존·백업 정책은 별도로 설정해야 합니다.

로그·메트릭 큐는 분리했으며 Worker는 각각 한 건씩 처리합니다. 기존 혼합 큐도 읽으므로 이미 접수한 작업을 이동·삭제할 필요는 없습니다. 단일 작업의 긴 분석을 선점하는 기능이나 P1 우선 큐는 추가하지 않았습니다. 분석 실패는 5초·10초 backoff 후 재처리하고 3회 실패 시 dead-letter로 기록합니다.

Admin과 Client는 실제 장애 목록의 서비스 버튼으로 분석 상세를 선택합니다. Client의 테스트 시나리오 자동 추종을 제거했습니다. 주기 조회는 이전 요청 완료 후 다시 예약하며 숨겨진 탭에서는 조회하지 않고 실패 시 간격을 늘립니다. 상태 표시는 최대 5초 캐시가 적용됩니다. 사용자 권한/RBAC 추가는 이번 범위에 포함되지 않습니다.

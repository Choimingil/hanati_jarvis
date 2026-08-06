#!/usr/bin/env bash
# 로컬 개발용 fluent-bit / Elasticsearch / Qdrant 자동 기동 스크립트 (Docker 기반)
#
# 사용법:
#   scripts/dev_infra.sh up       # 이미지 없으면 받아서 3개 전부 기동
#   scripts/dev_infra.sh down     # 전부 정지
#   scripts/dev_infra.sh status   # 상태만 확인
#
# 셋 다 Docker 컨테이너로 띄운다. fluent-bit는 fluentbit/ 디렉토리를 그대로
# 마운트해서 fluent-bit.conf / parser.conf를 쓰고, 호스트에서 도는
# app.py(scripts/run_app.sh)로 host.docker.internal을 통해 로그를 전달한다.
# 전부 개발/테스트 전용 설정이다 (보안 비활성화).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ES_CONTAINER="hanati-es"
QDRANT_CONTAINER="hanati-qdrant"
FLUENTBIT_CONTAINER="hanati-fluentbit"
ES_PORT="9200"
QDRANT_PORT="6333"

need_docker() {
  command -v docker >/dev/null || { echo "docker 없음. Docker Desktop 설치 후 재실행"; exit 1; }
  docker info >/dev/null 2>&1 || { echo "docker 데몬이 안 떠 있음. Docker Desktop 실행 후 재실행"; exit 1; }
}

container_running() {
  docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$1"
}

container_exists() {
  docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$1"
}

start_elasticsearch() {
  need_docker
  if container_running "$ES_CONTAINER"; then
    echo "[elasticsearch] 이미 실행 중"
    return
  fi
  if container_exists "$ES_CONTAINER"; then
    echo "[elasticsearch] 기존 컨테이너 재시작"
    docker start "$ES_CONTAINER" >/dev/null
  else
    echo "[elasticsearch] 컨테이너 생성 (이미지 없으면 자동 다운로드, 시간 걸릴 수 있음)"
    docker run -d --name "$ES_CONTAINER" \
      -p "${ES_PORT}:9200" \
      -e "discovery.type=single-node" \
      -e "xpack.security.enabled=false" \
      docker.elastic.co/elasticsearch/elasticsearch:8.15.0 >/dev/null
  fi
  echo -n "[elasticsearch] 기동 대기"
  for _ in $(seq 1 60); do
    curl -sf "http://localhost:${ES_PORT}" >/dev/null 2>&1 && { echo " 완료"; return; }
    echo -n "."
    sleep 2
  done
  echo " 시간 초과 (docker logs $ES_CONTAINER 로 확인)"
}

start_qdrant() {
  need_docker
  if container_running "$QDRANT_CONTAINER"; then
    echo "[qdrant] 이미 실행 중"
    return
  fi
  if container_exists "$QDRANT_CONTAINER"; then
    echo "[qdrant] 기존 컨테이너 재시작"
    docker start "$QDRANT_CONTAINER" >/dev/null
  else
    echo "[qdrant] 컨테이너 생성 (이미지 없으면 자동 다운로드)"
    docker run -d --name "$QDRANT_CONTAINER" \
      -p "${QDRANT_PORT}:6333" \
      qdrant/qdrant >/dev/null
  fi
  echo -n "[qdrant] 기동 대기"
  for _ in $(seq 1 30); do
    curl -sf "http://localhost:${QDRANT_PORT}/healthz" >/dev/null 2>&1 && { echo " 완료"; return; }
    echo -n "."
    sleep 1
  done
  echo " 시간 초과 (docker logs $QDRANT_CONTAINER 로 확인)"
}

start_fluent_bit() {
  need_docker
  if container_running "$FLUENTBIT_CONTAINER"; then
    echo "[fluent-bit] 이미 실행 중"
    return
  fi
  if container_exists "$FLUENTBIT_CONTAINER"; then
    echo "[fluent-bit] 기존 컨테이너 재시작"
    docker start "$FLUENTBIT_CONTAINER" >/dev/null
  else
    echo "[fluent-bit] 컨테이너 생성 (fluentbit/ 디렉토리 마운트)"
    # host.docker.internal: mac/windows는 기본 지원, 리눅스는 add-host로 보강
    docker run -d --name "$FLUENTBIT_CONTAINER" \
      -v "${REPO_ROOT}/fluentbit:/fluent-bit/etc" \
      -w /fluent-bit/etc \
      --add-host=host.docker.internal:host-gateway \
      fluent/fluent-bit:3.1 \
      -c /fluent-bit/etc/fluent-bit.conf >/dev/null
  fi
  sleep 1
  if container_running "$FLUENTBIT_CONTAINER"; then
    echo "[fluent-bit] 실행됨 (docker logs -f ${FLUENTBIT_CONTAINER} 로 확인)"
  else
    echo "[fluent-bit] 기동 실패, docker logs ${FLUENTBIT_CONTAINER} 로 확인"
  fi
}

stop_all() {
  echo "[fluent-bit] 컨테이너 정지.."
  docker stop "$FLUENTBIT_CONTAINER" >/dev/null 2>&1 || true
  echo "[elasticsearch] 컨테이너 정지.."
  docker stop "$ES_CONTAINER" >/dev/null 2>&1 || true
  echo "[qdrant] 컨테이너 정지.."
  docker stop "$QDRANT_CONTAINER" >/dev/null 2>&1 || true
}

print_env_hint() {
  cat <<EOF

app.py는 QDRANT_URL/ELASTICSEARCH_URL 기본값이 위 컨테이너를 가리키도록
되어 있어서 별도 export 없이 바로 연동된다. mock 백엔드는 없다 —
셋 중 하나라도 꺼져 있으면 관련 요청이 그대로 실패한다.

최초 1회 데이터 시딩:
  python -m qdrant.seed
  python -m elastic.seed_cases

앱 실행: scripts/run_app.sh
fluentbit -> 백엔드 파이프라인 확인은 TESTING.md 6번 참고.
EOF
}

cmd_status() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "docker 없음"
    return
  fi
  container_running "$FLUENTBIT_CONTAINER" && echo "fluent-bit: running" || echo "fluent-bit: stopped"
  container_running "$ES_CONTAINER" && echo "elasticsearch: running" || echo "elasticsearch: stopped"
  container_running "$QDRANT_CONTAINER" && echo "qdrant: running" || echo "qdrant: stopped"
}

case "${1:-up}" in
  up)
    start_elasticsearch
    start_qdrant
    start_fluent_bit
    print_env_hint
    ;;
  down)
    stop_all
    ;;
  status)
    cmd_status
    ;;
  *)
    echo "Usage: $0 up|down|status"
    exit 1
    ;;
esac

#!/usr/bin/env bash
# 로컬 개발용 fluent-bit / Elasticsearch / Qdrant 자동 설치·기동 스크립트 (macOS 기준)
#
# 사용법:
#   scripts/dev_infra.sh up       # 설치 필요하면 설치 후 3개 전부 기동
#   scripts/dev_infra.sh down     # 전부 정지
#   scripts/dev_infra.sh status   # 상태만 확인
#
# Elasticsearch/Qdrant는 Docker 컨테이너로, fluent-bit는 brew로 설치해서
# 로컬 프로세스로 띄운다. 전부 개발/테스트 전용 설정이다 (보안 비활성화).

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*|Windows_NT)
    if command -v pwsh >/dev/null 2>&1; then
      exec pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO_ROOT/scripts/dev_infra.ps1" "$@"
    elif command -v powershell.exe >/dev/null 2>&1; then
      exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$REPO_ROOT/scripts/dev_infra.ps1" "$@"
    else
      echo "PowerShell이 필요합니다. Windows PowerShell 5.1 또는 PowerShell 7을 설치해 주세요."
      exit 1
    fi
    ;;
esac

set -euo pipefail

ES_CONTAINER="hanati-es"
QDRANT_CONTAINER="hanati-qdrant"
ES_PORT="9200"
QDRANT_PORT="6333"
FLUENTBIT_LOG="/tmp/hanati-fluentbit.log"

need_brew() {
  command -v brew >/dev/null || { echo "brew 없음. https://brew.sh 에서 설치 후 재실행"; exit 1; }
}

need_docker() {
  command -v docker >/dev/null || { echo "docker 없음. Docker Desktop 설치 후 재실행"; exit 1; }
  docker info >/dev/null 2>&1 || { echo "docker 데몬이 안 떠 있음. Docker Desktop 실행 후 재실행"; exit 1; }
}

install_fluent_bit() {
  if command -v fluent-bit >/dev/null; then
    echo "[fluent-bit] 이미 설치됨"
    return
  fi
  echo "[fluent-bit] 설치 중.."
  need_brew
  brew install fluent-bit
}

start_fluent_bit() {
  if pgrep -f "fluent-bit -c" >/dev/null 2>&1; then
    echo "[fluent-bit] 이미 실행 중"
    return
  fi
  echo "[fluent-bit] 시작.."
  (cd "$REPO_ROOT/fluentbit" && nohup fluent-bit -c ./fluent-bit.conf > "$FLUENTBIT_LOG" 2>&1 &)
  sleep 1
  echo "[fluent-bit] 실행됨 (로그: $FLUENTBIT_LOG)"
}

stop_fluent_bit() {
  echo "[fluent-bit] 종료.."
  pkill -f "fluent-bit -c" 2>/dev/null || true
}

start_elasticsearch() {
  need_docker
  if docker ps --format '{{.Names}}' | grep -qx "$ES_CONTAINER"; then
    echo "[elasticsearch] 이미 실행 중"
    return
  fi
  if docker ps -a --format '{{.Names}}' | grep -qx "$ES_CONTAINER"; then
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
  if docker ps --format '{{.Names}}' | grep -qx "$QDRANT_CONTAINER"; then
    echo "[qdrant] 이미 실행 중"
    return
  fi
  if docker ps -a --format '{{.Names}}' | grep -qx "$QDRANT_CONTAINER"; then
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

stop_containers() {
  echo "[elasticsearch] 컨테이너 정지.."
  docker stop "$ES_CONTAINER" >/dev/null 2>&1 || true
  echo "[qdrant] 컨테이너 정지.."
  docker stop "$QDRANT_CONTAINER" >/dev/null 2>&1 || true
}

print_env_hint() {
  cat <<EOF

다음 환경변수로 앱을 실행하면 로컬 인프라를 사용한다:

  export QDRANT_URL=http://localhost:${QDRANT_PORT}
  export ELASTICSEARCH_URL=http://localhost:${ES_PORT}
  export ELASTICSEARCH_VERIFY_CERTS=false
  export CASE_SEARCHER_BACKEND=hybrid   # qdrant / elastic 도 가능

최초 1회 데이터 시딩:
  python -m qdrant.seed
  python -m elastic.seed_cases

fluentbit -> 백엔드 파이프라인 확인은 TESTING.md 6번 참고
(백엔드는 별도 터미널에서 'python app.py'로 직접 실행).
EOF
}

cmd_status() {
  pgrep -f "fluent-bit -c" >/dev/null 2>&1 && echo "fluent-bit: running" || echo "fluent-bit: stopped"
  if command -v docker >/dev/null 2>&1; then
    docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$ES_CONTAINER" && echo "elasticsearch: running" || echo "elasticsearch: stopped"
    docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$QDRANT_CONTAINER" && echo "qdrant: running" || echo "qdrant: stopped"
  else
    echo "elasticsearch: docker 없음"
    echo "qdrant: docker 없음"
  fi
}

case "${1:-up}" in
  up)
    install_fluent_bit
    start_elasticsearch
    start_qdrant
    start_fluent_bit
    print_env_hint
    ;;
  down)
    stop_fluent_bit
    stop_containers
    ;;
  status)
    cmd_status
    ;;
  *)
    echo "Usage: $0 up|down|status"
    exit 1
    ;;
esac

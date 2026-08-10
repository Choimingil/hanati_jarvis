#!/usr/bin/env bash
# 메인 서비스(app.py)와 시스템 메트릭 Agent를 함께 실행한다.
# venv가 없으면 만들고 의존성 설치까지 자동으로 한다.
#
# 사용법:
#   scripts/run_app.sh
#
# 백엔드 스위치는 환경변수로 미리 export 해두면 그대로 적용된다
# (scripts/dev_infra.sh up 실행 후 안내되는 값 참고):
#   CASE_SEARCHER_BACKEND=mock|qdrant|elastic|hybrid
#   LOG_REPOSITORY_BACKEND=mock|elastic
#   RECOMMENDATION_BACKEND=llm|mock
#   QDRANT_URL, ELASTICSEARCH_URL 등

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV_DIR="$REPO_ROOT/venv"

if [ ! -d "$VENV_DIR" ]; then
  echo "[venv] 없음 -> 생성 중.."
  python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "[deps] 설치 확인 중.."
pip install -q -r requirements.txt

echo "[app] 기동 (host=${API_HOST:-0.0.0.0} port=${API_PORT:-8080})"
echo "[app] case_search=${CASE_SEARCHER_BACKEND:-mock} storage=${LOG_REPOSITORY_BACKEND:-mock} recommendation=${RECOMMENDATION_BACKEND:-llm}"
echo "[app] 웹 콘솔: http://localhost:${API_PORT:-8080}/"

APP_PID=""
METRICS_PID=""
RETENTION_PID=""

# `wait -n`은 bash 4.3+ 전용이라 macOS 기본 /bin/bash(3.2, GPL 라이선스
# 문제로 안 올라감)에서는 "invalid option"으로 즉시 죽는다. 대신 죽은
# PID가 나올 때까지 폴링하는 방식으로 - PID 하나만 넘어와도 동작한다.
wait_for_any() {
  while true; do
    for pid in "$@"; do
      if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
        wait "$pid" 2>/dev/null
        return $?
      fi
    done
    sleep 1
  done
}

# app.py가 리스닝을 시작하기 전에 metrics agent가 첫 전송을 시도하면
# "system metrics send failed: <urlopen error [Errno 61] Connection
# refused>"가 뜬다(collector/agent.py는 기동 직후 sleep 없이 바로 첫
# 전송을 한다). agent를 띄우기 전에 포트가 열릴 때까지 기다려서 이 레이스를
# 없앤다.
wait_for_port() {
  local host="$1" port="$2" timeout="$3" waited=0
  while ! (exec 3<>"/dev/tcp/$host/$port") 2>/dev/null; do
    exec 3>&- 2>/dev/null || true
    waited=$((waited + 1))
    if [ "$waited" -ge "$timeout" ]; then
      return 1
    fi
    sleep 1
  done
  exec 3>&- 2>/dev/null || true
  return 0
}

cleanup() {
  trap - EXIT INT TERM

  if [ -n "$METRICS_PID" ] && kill -0 "$METRICS_PID" 2>/dev/null; then
    echo "[metrics] 종료 중.."
    kill "$METRICS_PID" 2>/dev/null || true
  fi

  if [ -n "$RETENTION_PID" ] && kill -0 "$RETENTION_PID" 2>/dev/null; then
    echo "[metrics-retention] 종료 중.."
    kill "$RETENTION_PID" 2>/dev/null || true
  fi

  if [ -n "$APP_PID" ] && kill -0 "$APP_PID" 2>/dev/null; then
    echo "[app] 종료 중.."
    kill "$APP_PID" 2>/dev/null || true
  fi

  wait "$METRICS_PID" 2>/dev/null || true
  wait "$RETENTION_PID" 2>/dev/null || true
  wait "$APP_PID" 2>/dev/null || true
}

# 이전 실행이 비정상 종료돼 포트를 계속 물고 있으면 새 app.py가 바인딩에
# 실패한다. 기동 전에 그 포트를 쓰고 있는 프로세스를 정리한다.
kill_port_listener() {
  local port="$1"
  local pids
  pids=$(lsof -ti "tcp:${port}" 2>/dev/null || true)
  if [ -z "$pids" ]; then
    return 0
  fi
  echo "[app] 포트 ${port} 사용 중인 기존 프로세스 종료: ${pids}"
  kill $pids 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    pids=$(lsof -ti "tcp:${port}" 2>/dev/null || true)
    if [ -z "$pids" ]; then
      return 0
    fi
    sleep 1
  done
  pids=$(lsof -ti "tcp:${port}" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "[app] 정상 종료 실패 - 강제 종료: ${pids}"
    kill -9 $pids 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

kill_port_listener "${API_PORT:-8080}"

python app.py &
APP_PID=$!

if [ "${METRICS_RETENTION_ENABLED:-true}" = "true" ]; then
  echo "[metrics-retention] 기동 (retention=${METRICS_RETENTION_DAYS:-14}d interval=${METRICS_RETENTION_INTERVAL_SECONDS:-86400}s)"
  python -m elastic.metric_retention &
  RETENTION_PID=$!
else
  echo "[metrics-retention] 비활성화됨 (METRICS_RETENTION_ENABLED=false)"
fi

if [ "${METRICS_AGENT_ENABLED:-true}" = "true" ]; then
  echo "[metrics] app 준비 대기 중.."
  if ! wait_for_port "127.0.0.1" "${API_PORT:-8080}" 20; then
    echo "[metrics] app 대기 시간 초과 - agent는 자체 재시도로 이어받음"
  fi
  echo "[metrics] psutil Agent 기동 (interval=${METRICS_COLLECT_INTERVAL_SECONDS:-30}s)"
  python -m collector.agent &
  METRICS_PID=$!
  if [ -n "$RETENTION_PID" ]; then
    wait_for_any "$APP_PID" "$METRICS_PID" "$RETENTION_PID"
  else
    wait_for_any "$APP_PID" "$METRICS_PID"
  fi
else
  echo "[metrics] 비활성화됨 (METRICS_AGENT_ENABLED=false)"
  wait "$APP_PID"
fi

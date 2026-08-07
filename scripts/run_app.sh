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

trap cleanup EXIT INT TERM

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
  echo "[metrics] psutil Agent 기동 (interval=${METRICS_COLLECT_INTERVAL_SECONDS:-30}s)"
  python -m collector.agent &
  METRICS_PID=$!
  if [ -n "$RETENTION_PID" ]; then
    wait -n "$APP_PID" "$METRICS_PID" "$RETENTION_PID"
  else
    wait -n "$APP_PID" "$METRICS_PID"
  fi
else
  echo "[metrics] 비활성화됨 (METRICS_AGENT_ENABLED=false)"
  wait "$APP_PID"
fi

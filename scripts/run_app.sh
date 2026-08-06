#!/usr/bin/env bash
# 메인 서비스(app.py) 실행 스크립트. venv 없으면 만들고 의존성 설치까지 자동으로 한다.
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

exec python app.py

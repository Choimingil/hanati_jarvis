#!/usr/bin/env bash
set -euo pipefail
SCRIPT_ID="check_jdbc_version"
log() {
  local level="$1"; shift
  printf '%s level=%s host=web01 service=order-api component=%s execution_mode=simulation message="[%s] %s"\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$level" "$SCRIPT_ID" "$*"
}

log INFO "Diagnostic probe started; target=web01/worker-3"
sleep 0.2
log INFO "Collected check jdbc version telemetry; probe_status=healthy latency_ms=27 error_count=0"
printf 'TEST_JDBC_VERSION=8.0\n'
sleep 0.2
log INFO "Diagnostic probe completed; result=success"
exit 0

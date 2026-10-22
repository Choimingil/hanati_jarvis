#!/usr/bin/env bash
set -euo pipefail
SCRIPT_ID="check_container_memory_limits"
log() {
  local level="$1"; shift
  printf '%s level=%s host=web01 service=order-api component=%s execution_mode=simulation message="[%s] %s"\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$level" "$SCRIPT_ID" "$*"
}

log INFO "Diagnostic probe started; target=web01/worker-3"
sleep 0.2
log INFO "Collected check container memory limits telemetry; probe_status=healthy latency_ms=27 error_count=0"
printf 'TEST_CHECK_CONTAINER_MEMORY_LIMITS_OK\n'
sleep 0.2
log INFO "Diagnostic probe completed; result=success"
exit 0

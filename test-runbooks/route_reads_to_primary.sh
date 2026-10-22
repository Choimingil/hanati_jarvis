#!/usr/bin/env bash
set -euo pipefail
SCRIPT_ID="route_reads_to_primary"
log() {
  local level="$1"; shift
  printf '%s level=%s host=web01 service=order-api component=%s execution_mode=simulation message="[%s] %s"\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$level" "$SCRIPT_ID" "$*"
}

log INFO "Runbook started; action=route reads to primary change_id=SIM-ROUTE_READS_TO_PRIMARY"
sleep 0.2
log INFO "Action step completed; validation=passed action=route reads to primary"
sleep 0.2
log INFO "Runbook completed; result=success recovery_confirmation=pending"
exit 0

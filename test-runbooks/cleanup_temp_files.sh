#!/usr/bin/env bash
set -euo pipefail
SCRIPT_ID="cleanup_temp_files"
log() {
  local level="$1"; shift
  printf '%s level=%s host=web01 service=order-api component=%s execution_mode=simulation message="[%s] %s"\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$level" "$SCRIPT_ID" "$*"
}

log INFO "Runbook started; action=cleanup temp files change_id=SIM-CLEANUP_TEMP_FILES"
sleep 0.2
log INFO "Action step completed; validation=passed action=cleanup temp files"
sleep 0.2
log INFO "Runbook completed; result=success recovery_confirmation=pending"
exit 0

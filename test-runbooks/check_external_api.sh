#!/usr/bin/env bash
set -euo pipefail
SCRIPT_ID="check_external_api"
log() {
  local level="$1"; shift
  printf '%s level=%s host=web01 service=order-api component=%s execution_mode=simulation message="[%s] %s"\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$level" "$SCRIPT_ID" "$SCRIPT_ID" "$*"
}


log INFO "phase=01/21 Probe accepted; incident context loaded; operation=check_external_api"
sleep 0.06
log INFO "phase=02/21 Resolving service endpoint and node identity; operation=check_external_api"
sleep 0.06
log INFO "phase=03/21 Opening read-only telemetry window; operation=check_external_api"
sleep 0.06
log DEBUG "phase=04/21 Checking recent request and error rates; operation=check_external_api"
sleep 0.06
log INFO "phase=05/21 Sampling host resource utilization; operation=check_external_api"
sleep 0.06
log INFO "phase=06/21 Comparing current values with baseline; operation=check_external_api"
sleep 0.06
log INFO "phase=07/21 Inspecting dependency response summary; operation=check_external_api"
sleep 0.06
log INFO "phase=08/21 Reviewing recent service health signals; operation=check_external_api"
sleep 0.06
log DEBUG "phase=09/21 Checking configured thresholds; operation=check_external_api"
sleep 0.06
log INFO "phase=10/21 Correlating warning and error counters; operation=check_external_api"
sleep 0.06
log INFO "phase=11/21 Validating observation time range; operation=check_external_api"
sleep 0.06
log INFO "phase=12/21 Collecting component-specific evidence; operation=check_external_api"
sleep 0.06
log DEBUG "phase=13/21 Checking for incomplete telemetry; operation=check_external_api"
sleep 0.06
log INFO "phase=14/21 Normalizing diagnostic measurements; operation=check_external_api"
sleep 0.06
log INFO "phase=15/21 Reviewing last-known healthy sample; operation=check_external_api"
sleep 0.06
log INFO "phase=16/21 Confirming probe remains read-only; operation=check_external_api"
sleep 0.06
log INFO "phase=17/21 Summarizing observed service indicators; operation=check_external_api"
sleep 0.06
log INFO "phase=18/21 Recording diagnostic evidence reference; operation=check_external_api"
sleep 0.06
log INFO "phase=19/21 Preparing operator-facing findings; operation=check_external_api"
sleep 0.06
log INFO "phase=20/21 No live service settings were changed; operation=check_external_api"
sleep 0.06
log WARN "phase=21/21 Diagnostic checks completed; result=simulated; operation=check_external_api"
printf 'TEST_CHECK_EXTERNAL_API_OK\n'
exit 0

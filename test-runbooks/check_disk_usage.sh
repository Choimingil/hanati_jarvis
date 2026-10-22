#!/usr/bin/env bash
set -euo pipefail
SCRIPT_ID="check_disk_usage"
log() {
  local level="$1"; shift
  printf '%s level=%s host=web01 service=order-api component=%s execution_mode=simulation message="[%s] %s"\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$level" "$SCRIPT_ID" "$SCRIPT_ID" "$*"
}


log INFO "phase=01/25 Probe accepted; incident context loaded; operation=check_disk_usage"
sleep 0.03
log INFO "phase=02/25 Resolving service endpoint and node identity; operation=check_disk_usage"
sleep 0.03
log INFO "phase=03/25 Opening read-only telemetry window; operation=check_disk_usage"
sleep 0.03
log DEBUG "phase=04/25 Checking recent request and error rates; operation=check_disk_usage"
sleep 0.03
log INFO "phase=05/25 Sampling host resource utilization; operation=check_disk_usage"
sleep 0.03
log INFO "phase=06/25 Comparing current values with baseline; operation=check_disk_usage"
sleep 0.03
log INFO "phase=07/25 Inspecting dependency response summary; operation=check_disk_usage"
sleep 0.03
log INFO "phase=08/25 Reviewing recent service health signals; operation=check_disk_usage"
sleep 0.03
log DEBUG "phase=09/25 Checking configured thresholds; operation=check_disk_usage"
sleep 0.03
log INFO "phase=10/25 Correlating warning and error counters; operation=check_disk_usage"
sleep 0.03
log INFO "phase=11/25 Validating observation time range; operation=check_disk_usage"
sleep 0.03
log INFO "phase=12/25 Collecting component-specific evidence; operation=check_disk_usage"
sleep 0.03
log DEBUG "phase=13/25 Checking for incomplete telemetry; operation=check_disk_usage"
sleep 0.03
log INFO "phase=14/25 Normalizing diagnostic measurements; operation=check_disk_usage"
sleep 0.03
log INFO "phase=15/25 Reviewing last-known healthy sample; operation=check_disk_usage"
sleep 0.03
log INFO "phase=16/25 Confirming probe remains read-only; operation=check_disk_usage"
sleep 0.03
log INFO "phase=17/25 Summarizing observed service indicators; operation=check_disk_usage"
sleep 0.03
log INFO "phase=18/25 Recording diagnostic evidence reference; operation=check_disk_usage"
sleep 0.03
log INFO "phase=19/25 Preparing operator-facing findings; operation=check_disk_usage"
sleep 0.03
log INFO "phase=20/25 No live service settings were changed; operation=check_disk_usage"
sleep 0.03
log WARN "phase=21/25 Diagnostic checks completed; result=simulated; operation=check_disk_usage"
sleep 0.03
log INFO "phase=22/25 Evidence returned for incident review; operation=check_disk_usage"
sleep 0.03
log INFO "phase=23/25 Cross-checking independent health signal; operation=check_disk_usage"
sleep 0.03
log INFO "phase=24/25 Comparing recent and baseline latency; operation=check_disk_usage"
sleep 0.03
log INFO "phase=25/25 Checking retry and timeout counters; operation=check_disk_usage"
printf 'TEST_DISK_USAGE_OK\n'
df -h | sed -n '1,5p'
exit 0

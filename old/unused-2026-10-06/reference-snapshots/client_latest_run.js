async function followLatestRun() {
  let data;
  try {
    data = await getJSON("/api/v1/log-generator/latest-run");
  } catch (e) {
    return;
  }
  if (data.status !== "ready" || data.run.run_id === clientRunId) return;

  const run = data.run;
  clientRunId = run.run_id;
  $("result").classList.add("hidden");
  $("guidance-result").classList.add("hidden");
  $("exec").classList.add("hidden");
  currentGuidance = null;
  selectedVerdict = null;
  clientRunPrefix = `장애 감지: ${run.label} (${formatTime(run.triggered_at)})`;
  setClientStatus("오류를 분석하는 중…");

  await waitForRecommendation(
    run.error_code, run.triggered_at, () => clientRunId === run.run_id
  );
}


"""운영자용 웹 UI.

`GET /` 에서 단일 페이지를 제공한다. 흐름은 다음과 같다.

1. 장애 시나리오(=log_generator/main.py가 발생시키는 오류)를 하나 골라
   "분석" 클릭 -> 서버가 `log_generator/trigger.py`로 그 시나리오를 실제
   실행해서 fluentbit가 tail하는 `fluentbit/application.log`에 그대로
   기록한다 (main.py를 직접 돌렸을 때와 동일한 코드 경로).
2. fluent-bit가 그 파일을 tail해서 `POST /api/v1/logs`로 백엔드에 전달 ->
   탐지 → 진단 → (LLM) 추천이 비동기로 이뤄진다. 화면은 그 결과가
   Elasticsearch에 쌓일 때까지 짧게 폴링한다.
3. LLM이 준 "오류 원인"과 신뢰도 높은 순 조치 제안을 Runbook 카드로 보여준다
   (장애/추정 원인/신뢰도/조치/예상 영향/과거 실행 이력/실패 시 대응)
4. 각 Runbook에서 "승인"하면 `POST /api/v1/remediations/approve` 로 해당
   스크립트를 실제로 호출하고 결과(stdout)를 보여준다. "거부"는 스크립트를
   실행하지 않고 감사 기록만 남긴다. "진단 요청"은 그 오류 코드의 진단
   스크립트를 다시 돌려서 최신 상태를 보여준다
"""

from flask import Blueprint, Response


web_blueprint = Blueprint("web", __name__)


_PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hanati Jarvis — 장애 대응 콘솔</title>
<style>
  :root {
    --bg: #f6f7f9; --card: #ffffff; --fg: #1c2333; --muted: #5b6472;
    --border: #e3e6eb; --accent: #3b6cf0; --accent-fg: #fff;
    --bar: #e7ecfb; --ok: #17915a; --err: #d1364a; --code-bg: #0f1524;
    --code-fg: #d8e0f0;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0e1117; --card: #171b22; --fg: #e6e9ef; --muted: #9aa4b2;
      --border: #262c36; --accent: #4d7cf6; --bar: #22304f;
      --code-bg: #0a0e16; --code-fg: #cdd6e6;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--fg);
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    line-height: 1.5;
  }
  .wrap { max-width: 860px; margin: 0 auto; padding: 28px 20px 64px; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .sub { color: var(--muted); margin: 0 0 24px; font-size: 14px; }
  .card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 12px; padding: 20px; margin-bottom: 18px;
  }
  label { font-size: 13px; color: var(--muted); display: block; margin-bottom: 6px; }
  select, button {
    font: inherit; color: inherit;
  }
  select {
    width: 100%; padding: 10px 12px; border-radius: 8px;
    border: 1px solid var(--border); background: var(--bg); color: var(--fg);
  }
  .row { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; }
  .row > div { flex: 1 1 260px; }
  button {
    background: var(--accent); color: var(--accent-fg); border: 0;
    padding: 11px 18px; border-radius: 8px; cursor: pointer; font-weight: 600;
    white-space: nowrap;
  }
  button.secondary {
    background: transparent; color: var(--accent);
    border: 1px solid var(--accent);
  }
  button:disabled { opacity: .55; cursor: default; }
  .hidden { display: none; }
  .cause {
    border-left: 3px solid var(--accent); padding: 4px 0 4px 14px;
    margin: 6px 0 4px; font-size: 15px;
  }
  .pill {
    display: inline-block; font-size: 12px; font-weight: 600;
    background: var(--bar); color: var(--accent); border-radius: 999px;
    padding: 3px 10px; margin-bottom: 10px;
  }
  .runbook {
    border: 1px solid var(--border); border-radius: 10px;
    padding: 16px; margin-top: 12px;
  }
  .runbook-tag {
    display: inline-block; font-size: 11px; font-weight: 700;
    color: var(--accent); letter-spacing: .02em; margin-bottom: 8px;
  }
  .runbook dl {
    display: grid; grid-template-columns: 88px 1fr; gap: 6px 12px;
    margin: 0; font-size: 14px;
  }
  .runbook dt { color: var(--muted); font-size: 13px; }
  .runbook dd { margin: 0; }
  .runbook .confidence-bar {
    height: 6px; background: var(--bar); border-radius: 999px;
    overflow: hidden; margin-top: 4px; max-width: 220px;
  }
  .runbook .confidence-bar > span {
    display: block; height: 100%; background: var(--accent);
  }
  .runbook .rollback { color: var(--err); }
  .runbook .buttons {
    display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap;
  }
  .runbook button.reject {
    background: transparent; color: var(--err); border: 1px solid var(--err);
  }
  .runbook button.diagnose {
    background: transparent; color: var(--muted); border: 1px solid var(--border);
  }
  .runbook.decided { opacity: .6; }
  .runbook .decision {
    font-size: 13px; font-weight: 700; margin-top: 10px;
  }
  pre {
    background: var(--code-bg); color: var(--code-fg); padding: 14px;
    border-radius: 8px; overflow-x: auto; font-size: 13px; margin: 10px 0 0;
    white-space: pre-wrap;
  }
  .logline { opacity: 0; animation: fadein .25s ease forwards; }
  .logline.WARN { color: #f5c451; }
  .logline.ERROR { color: #ff8080; }
  @keyframes fadein { to { opacity: 1; } }
  .sub-label { font-size: 12px; color: var(--muted); margin: 10px 0 0; font-weight: 600; }
  .sub-label:first-child { margin-top: 0; }
  pre.src-qdrant { color: #8ab4f8; }
  pre.src-elasticsearch { color: #7fe0c4; }
  .status-ok { color: var(--ok); font-weight: 700; }
  .status-err { color: var(--err); font-weight: 700; }
  .status-pending { color: var(--muted); font-weight: 600; }
  .muted { color: var(--muted); font-size: 13px; }
  .card-head {
    display: flex; align-items: center; justify-content: space-between; gap: 12px;
  }
  .panel-toggle {
    background: transparent; border: 0; color: var(--muted); cursor: pointer;
    padding: 4px 6px; font-size: 13px; border-radius: 6px; flex: 0 0 auto;
  }
  .panel-toggle:hover { background: var(--bar); }
  .panel-toggle .chev { display: inline-block; transition: transform .15s ease; }
  .card.collapsed .panel-body { display: none; }
  .card.collapsed .panel-toggle .chev { transform: rotate(-90deg); }
</style>
</head>
<body>
<div class="wrap">
  <h1>Hanati Jarvis — 장애 대응 콘솔</h1>
  <p class="sub">log_generator 시나리오 실행 → fluentbit 전달 → 오류 탐지 → 진단 → LLM 추천 → 조치 스크립트 실행</p>

  <div class="card">
    <div class="row">
      <div>
        <label for="scenario">장애 시나리오 (log_generator/main.py 시나리오)</label>
        <select id="scenario"></select>
      </div>
      <button id="analyze" disabled>분석</button>
    </div>
  </div>

  <div id="log" class="card hidden logs-section">
    <div class="card-head">
      <div><strong>log_generator 실행 로그</strong>
        <span class="muted">(fluentbit/application.log 기록분)</span></div>
      <button class="panel-toggle" type="button" aria-label="접기/펼치기"><span class="chev">▾</span></button>
    </div>
    <div class="panel-body">
      <pre id="log-output"></pre>
      <div id="wait-status" class="muted" style="margin-top:8px"></div>
    </div>
  </div>

  <div id="fluentbit-panel" class="card hidden logs-section">
    <div class="card-head">
      <div><strong>fluent-bit 컨테이너 로그</strong>
        <span class="muted">(docker logs hanati-fluentbit, 이번 실행 이후분)</span></div>
      <button class="panel-toggle" type="button" aria-label="접기/펼치기"><span class="chev">▾</span></button>
    </div>
    <div class="panel-body">
      <pre id="fluentbit-output"></pre>
    </div>
  </div>

  <div id="internal-panel" class="card hidden logs-section">
    <div class="card-head">
      <div><strong>Qdrant / Elasticsearch 컨테이너 로그</strong>
        <span class="muted">(docker logs, 이번 실행 이후분)</span></div>
      <button class="panel-toggle" type="button" aria-label="접기/펼치기"><span class="chev">▾</span></button>
    </div>
    <div class="panel-body">
      <div class="sub-label">Qdrant (hanati-qdrant)</div>
      <pre id="qdrant-output" class="src-qdrant"></pre>
      <div class="sub-label">Elasticsearch (hanati-es)</div>
      <pre id="es-output" class="src-elasticsearch"></pre>
    </div>
  </div>

  <div id="result" class="card hidden">
    <span id="errcode" class="pill"></span>
    <div><strong>현재 오류 원인</strong></div>
    <div id="cause" class="cause"></div>
    <div style="margin-top:18px"><strong>조치 제안 Runbook</strong>
      <span class="muted">(신뢰도 높은 순)</span></div>
    <div id="actions"></div>
  </div>

  <div id="exec" class="card hidden">
    <div><strong>실행 결과</strong> — <span id="exec-title" class="muted"></span></div>
    <div id="exec-status"></div>
    <pre id="exec-output"></pre>
  </div>
</div>

<script>
const $ = (id) => document.getElementById(id);
const sel = $("scenario");
let currentErrorCode = null;

document.querySelectorAll(".panel-toggle").forEach((btn) => {
  btn.addEventListener("click", () => {
    btn.closest(".card").classList.toggle("collapsed");
  });
});

async function getJSON(url) {
  const res = await fetch(url);
  return res.json();
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return { ok: res.ok, status: res.status, data: await res.json() };
}

(async function loadScenarios() {
  const scenarios = await getJSON("/api/v1/log-generator/scenarios");
  scenarios.forEach((s) => {
    const o = document.createElement("option");
    o.value = s.key; o.textContent = s.label; sel.appendChild(o);
  });
  $("analyze").disabled = false;
})();

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

let currentSince = null;

$("analyze").addEventListener("click", async () => {
  $("analyze").disabled = true;
  $("analyze").textContent = "시나리오 실행 중…";
  $("log").classList.remove("hidden");
  $("fluentbit-panel").classList.remove("hidden");
  $("internal-panel").classList.remove("hidden");
  $("result").classList.add("hidden");
  $("exec").classList.add("hidden");
  $("log-output").innerHTML = "";
  $("fluentbit-output").textContent = "";
  $("qdrant-output").textContent = "";
  $("es-output").textContent = "";
  $("wait-status").textContent = "";
  currentSince = null;

  try {
    const { data } = await postJSON("/api/v1/log-generator/run", {
      scenario: sel.value,
    });

    if (data.status !== "triggered") {
      $("wait-status").textContent = "실행 실패: " + JSON.stringify(data);
      return;
    }

    // 이번 실행 이후분만 폴링하도록 트리거 시각으로 스코프를 좁힌다
    // (안 그러면 이전 실행의 Qdrant/Elasticsearch/fluentbit 로그가 다시 보임)
    currentSince = data.triggered_at;

    data.events.forEach((e, i) => {
      const line = document.createElement("div");
      line.className = "logline " + e.level;
      line.style.animationDelay = (i * 60) + "ms";
      line.textContent = `[${e.level}] ${e.message}`;
      $("log-output").appendChild(line);
    });

    await waitForRecommendation(data.error_code, data.triggered_at);
  } catch (e) {
    $("wait-status").textContent = "실행 실패: " + e;
  } finally {
    $("analyze").disabled = false;
    $("analyze").textContent = "분석";
  }
});

async function pollActivity() {
  try {
    const params = new URLSearchParams();
    if (currentSince) params.set("since", currentSince);
    const data = await getJSON(
      `/api/v1/log-generator/activity?${params}`
    );
    $("fluentbit-output").textContent =
      (data.fluentbit_log || []).join("\\n");
    $("fluentbit-output").scrollTop = $("fluentbit-output").scrollHeight;
    $("qdrant-output").textContent =
      (data.qdrant_log || []).join("\\n");
    $("qdrant-output").scrollTop = $("qdrant-output").scrollHeight;
    $("es-output").textContent =
      (data.elasticsearch_log || []).join("\\n");
    $("es-output").scrollTop = $("es-output").scrollHeight;
  } catch (e) {
    // 폴링 실패는 조용히 무시하고 다음 주기에 재시도
  }
}

async function waitForRecommendation(errorCode, since) {
  $("wait-status").textContent =
    "fluent-bit가 로그를 전달하는 중… 추천 결과를 기다리는 중";

  for (let i = 0; i < 20; i++) {
    await sleep(1500);
    await pollActivity();
    const data = await getJSON(
      `/api/v1/log-generator/latest-recommendation?error_code=${encodeURIComponent(errorCode)}&since=${encodeURIComponent(since)}`
    );
    if (data.status === "ready") {
      $("wait-status").textContent = "";
      renderRecommendation(errorCode, data.recommendation);
      return;
    }
  }

  $("wait-status").textContent =
    "추천 결과 대기 시간 초과 — fluentbit/Elasticsearch/Qdrant 상태를 확인하세요.";
}

function renderRecommendation(errorCode, rec) {
  currentErrorCode = errorCode;
  const result = $("result");
  result.classList.remove("hidden");

  $("errcode").textContent = errorCode;
  $("cause").textContent = rec.cause || rec.summary || "";

  const runbooks = rec.runbooks || [];
  const box = $("actions");
  box.innerHTML = "";

  runbooks.forEach((rb) => {
    const pct = Math.max(0, Math.min(100, rb.confidence));
    const el = document.createElement("div");
    el.className = "runbook";
    el.innerHTML = `
      <div class="runbook-tag">조치 제안</div>
      <dl>
        <dt>장애</dt><dd>${rb.incident}</dd>
        <dt>추정 원인</dt><dd>${rb.estimated_cause}</dd>
        <dt>신뢰도</dt><dd>${pct}%
          <div class="confidence-bar"><span style="width:${pct}%"></span></div>
        </dd>
        <dt>조치</dt><dd>${rb.action}</dd>
        <dt>예상 영향</dt><dd>${rb.expected_impact}</dd>
        <dt>과거 실행</dt><dd>성공 ${rb.history.success}회 / 실패 ${rb.history.failure}회</dd>
        <dt>실패 시</dt><dd class="rollback">${rb.rollback}</dd>
      </dl>
      <div class="decision"></div>
      <div class="buttons">
        <button class="approve">승인</button>
        <button class="reject">거부</button>
        <button class="diagnose">진단 요청</button>
      </div>`;

    el.querySelector(".approve").addEventListener(
      "click", () => decideRunbook(rb.script_id, el, "approve")
    );
    el.querySelector(".reject").addEventListener(
      "click", () => decideRunbook(rb.script_id, el, "reject")
    );
    el.querySelector(".diagnose").addEventListener(
      "click", () => requestDiagnosis(errorCode, el)
    );

    box.appendChild(el);
  });
}

function setRunbookButtonsDisabled(el, disabled) {
  el.querySelectorAll(".buttons button").forEach((b) => {
    b.disabled = disabled;
  });
}

async function decideRunbook(scriptId, el, decision) {
  if (!currentErrorCode) return;
  setRunbookButtonsDisabled(el, true);

  const endpoint = decision === "approve"
    ? "/api/v1/remediations/approve"
    : "/api/v1/remediations/reject";

  const exec = $("exec");
  exec.classList.remove("hidden");
  $("exec-title").textContent = scriptId;
  $("exec-status").textContent = "";
  $("exec-output").textContent = "";

  try {
    const { status, data } = await postJSON(endpoint, {
      script_id: scriptId, error_code: currentErrorCode, approved_by: "web-ui",
    });
    const ok = data.status === "success" || data.status === "rejected";
    const s = $("exec-status");
    s.className = ok ? "status-ok" : "status-err";
    s.textContent = `${data.status}` + (data.returncode !== undefined
      ? ` (exit ${data.returncode})` : ` (HTTP ${status})`);
    $("exec-output").textContent =
      (data.stdout || "") + (data.stderr ? "\\n[stderr]\\n" + data.stderr :
        (data.reason ? "\\n" + data.reason : ""));

    el.classList.add("decided");
    el.querySelector(".decision").textContent =
      decision === "approve" ? "✓ 승인됨" : "✗ 거부됨";
  } catch (e) {
    $("exec-status").className = "status-err";
    $("exec-status").textContent = "요청 실패: " + e;
    setRunbookButtonsDisabled(el, false);
  }
}

async function requestDiagnosis(errorCode, el) {
  setRunbookButtonsDisabled(el, true);

  const exec = $("exec");
  exec.classList.remove("hidden");
  $("exec-title").textContent = "진단 요청 — " + errorCode;
  $("exec-status").textContent = "";
  $("exec-output").textContent = "";

  try {
    const { data } = await postJSON("/api/v1/remediations/diagnose", {
      error_code: errorCode,
    });
    const s = $("exec-status");
    s.className = data.status === "ok" ? "status-ok" : "status-err";
    s.textContent = data.status;
    $("exec-output").textContent = JSON.stringify(
      data.diagnosis_results || data, null, 2
    );
  } catch (e) {
    $("exec-status").className = "status-err";
    $("exec-status").textContent = "진단 요청 실패: " + e;
  } finally {
    setRunbookButtonsDisabled(el, false);
  }
}
</script>
</body>
</html>
"""


@web_blueprint.get("/")
def index() -> Response:
    return Response(_PAGE, mimetype="text/html")

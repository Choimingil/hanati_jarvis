"""운영자용 웹 UI.

같은 페이지를 두 모드로 제공한다.

- `GET /`, `GET /admin` (어드민): 아래 흐름 전체 + 장애 시나리오/수집·분석 로그
- `GET /client` (클라이언트): 오류 내용(원인·Runbook/리소스 가이드)만 표시.
  어드민이 시나리오를 실행하면 `/api/v1/log-generator/latest-run` 폴링으로
  같은 장애의 분석 결과를 따라 보여준다.

흐름은 다음과 같다.

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
<title>Hanati Jarvis — 장애 대응 콘솔__TITLE_SUFFIX__</title>
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
  .wrap { max-width: 1180px; margin: 0 auto; padding: 28px 20px 64px; }
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
  input, textarea {
    width: 100%; padding: 10px 12px; border-radius: 8px;
    border: 1px solid var(--border); background: var(--bg); color: var(--fg);
    font: inherit;
  }
  textarea { min-height: 76px; resize: vertical; }
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
  .runbook.decided, .runbook.locked { opacity: .6; }
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
  .guidance-summary {
    border-left: 3px solid #e59b22; padding: 5px 0 5px 14px;
    margin: 8px 0 16px;
  }
  .hypothesis {
    border: 1px solid var(--border); border-radius: 10px;
    padding: 16px; margin-top: 12px;
  }
  .hypothesis.primary { border-color: #e59b22; }
  .hypothesis-head {
    display: flex; justify-content: space-between; gap: 12px;
    align-items: center; margin-bottom: 10px;
  }
  .hypothesis-title { font-weight: 700; }
  .confidence { color: #e59b22; font-weight: 700; white-space: nowrap; }
  .confidence-track {
    height: 6px; border-radius: 999px; background: var(--bar);
    overflow: hidden; margin: 8px 0 12px;
  }
  .confidence-fill { height: 100%; background: #e59b22; }
  .guidance-list { margin: 6px 0 0; padding-left: 21px; font-size: 14px; }
  .guidance-list li { margin: 4px 0; }
  .guidance-section { margin-top: 14px; }
  .feedback-choices { display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0 14px; }
  button.feedback-choice {
    background: transparent; color: var(--accent);
    border: 1px solid var(--accent); padding: 8px 12px;
  }
  button.feedback-choice.selected { background: var(--accent); color: white; }
  .feedback-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .feedback-grid .full { grid-column: 1 / -1; }
  .check-row { display: flex; align-items: center; gap: 8px; font-size: 14px; }
  .check-row input { width: auto; }
  .console-head { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; flex-wrap:wrap; }
  .console-actions { display:flex; gap:8px; flex-wrap:wrap; }
  .incident-stats { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-bottom:16px; }
  .incident-stat { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:13px; }
  .incident-stat span { display:block; color:var(--muted); font-size:12px; }
  .incident-stat strong { display:block; margin-top:3px; }
  .log-tabs { display:flex; gap:8px; flex-wrap:wrap; }
  button.log-tab { background:transparent; color:var(--accent); border:1px solid var(--accent); padding:8px 12px; }
  button.log-tab.selected { background:var(--accent); color:var(--accent-fg); }
  .scenario-card { margin-top:18px; }
  body.mode-client .admin-only { display:none !important; }
  body.mode-admin .client-only { display:none !important; }
  @media (max-width:760px) { .incident-stats { grid-template-columns:repeat(2,minmax(0,1fr)); } }
  @media (max-width: 620px) {
    .feedback-grid { grid-template-columns: 1fr; }
    .feedback-grid .full { grid-column: auto; }
  }
</style>
</head>
<body class="mode-__MODE__">
<div class="wrap">
  <div class="console-head">
    <div><h1>Hanati Jarvis — 장애 대응 콘솔__TITLE_SUFFIX__</h1><p class="sub">로그·리소스 분석 → Runbook 추천 또는 Resource Guidance → 운영자 확인 → 안전한 조치·학습</p></div>
    <div class="console-actions"><button id="refresh-incidents" class="secondary">새로고침</button><button id="log-toggle" class="admin-only">로그 조회</button></div>
  </div>
  <div class="incident-stats">
    <div class="incident-stat"><span>진행 중</span><strong id="stat-open">0건</strong></div>
    <div class="incident-stat"><span>긴급</span><strong id="stat-critical">0건</strong></div>
    <div class="incident-stat"><span>미확인</span><strong id="stat-unack">0건</strong></div>
    <div class="incident-stat"><span>분석 중</span><strong id="stat-analyzing">0건</strong></div>
  </div>
  <div id="client-status" class="card client-only">
    <strong>장애 모니터링</strong>
    <div id="client-status-text" class="muted" style="margin-top:6px">발생한 장애가 없습니다. 장애가 감지되면 이 화면에 오류 내용이 표시됩니다.</div>
  </div>
  <div class="card scenario-card admin-only">
    <div class="row">
      <div>
        <label for="scenario">장애 시나리오 (log_generator/main.py 시나리오)</label>
        <select id="scenario"></select>
      </div>
      <button id="analyze" disabled>분석</button>
    </div>
  </div>
  <div id="log-tabs-panel" class="card hidden admin-only">
    <div class="card-head"><div><strong>수집·분석 로그</strong><span class="muted">(선택한 시점 이후분)</span></div><button id="log-close" class="panel-toggle" type="button">닫기</button></div>
    <div class="log-tabs" style="margin-top:12px">
      <button class="log-tab selected" data-panel="log">log_generator</button>
      <button class="log-tab" data-panel="fluentbit-panel">Fluent Bit</button>
      <button class="log-tab" data-panel="internal-panel">Elasticsearch/Qdrant</button>
    </div>
  </div>
  <div id="log" class="card hidden logs-section admin-only">
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

  <div id="fluentbit-panel" class="card hidden logs-section admin-only">
    <div class="card-head">
      <div><strong>fluent-bit → aiops 수신 로그</strong>
        <span class="muted">(Elasticsearch application-logs, 이번 실행 이후분)</span></div>
      <button class="panel-toggle" type="button" aria-label="접기/펼치기"><span class="chev">▾</span></button>
    </div>
    <div class="panel-body">
      <pre id="fluentbit-output"></pre>
    </div>
  </div>

  <div id="internal-panel" class="card hidden logs-section admin-only">
    <div class="card-head">
      <div><strong>Qdrant / Elasticsearch 저장 내용</strong>
        <span class="muted">(이번 실행 이후 저장분)</span></div>
      <button class="panel-toggle" type="button" aria-label="접기/펼치기"><span class="chev">▾</span></button>
    </div>
    <div class="panel-body">
      <div class="sub-label">Qdrant (incident_cases 컬렉션)</div>
      <pre id="qdrant-output" class="src-qdrant"></pre>
      <div class="sub-label">Elasticsearch (진단·추천)</div>
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

  <div id="guidance-result" class="card hidden">
    <span id="guidance-code" class="pill">RESOURCE GUIDANCE</span>
    <div><strong>리소스 기반 문제 제안</strong></div>
    <div id="guidance-summary" class="guidance-summary"></div>

    <div class="guidance-section"><strong>발생 로그</strong></div>
    <pre id="guidance-log"></pre>

    <div class="guidance-section"><strong>발견된 문제 가능성</strong>
      <span class="muted">(신뢰도 높은 순)</span></div>
    <div id="hypotheses"></div>

    <div class="guidance-section"><strong>같은 호스트의 최근 ERROR 로그</strong></div>
    <pre id="guidance-related-logs"></pre>

    <div class="guidance-section"><strong>운영자 판단</strong>
      <div class="muted">확인과 복구가 완료된 결과만 과거 장애 사례로 학습됩니다.</div>
    </div>
    <div id="feedback-choices" class="feedback-choices">
      <button class="feedback-choice" data-verdict="confirmed">원인 정확</button>
      <button class="feedback-choice" data-verdict="partial">일부 관련</button>
      <button class="feedback-choice" data-verdict="rejected">관련 없음</button>
      <button class="feedback-choice" data-verdict="needs_investigation">추가 조사</button>
    </div>
    <div class="feedback-grid">
      <div>
        <label for="feedback-root-cause">실제 원인</label>
        <textarea id="feedback-root-cause" placeholder="확인된 실제 원인"></textarea>
      </div>
      <div>
        <label for="feedback-action">수행한 조치</label>
        <textarea id="feedback-action" placeholder="실제로 수행한 조치"></textarea>
      </div>
      <div>
        <label for="feedback-operator">운영자</label>
        <input id="feedback-operator" value="web-ui">
      </div>
      <div class="check-row">
        <input id="feedback-recovered" type="checkbox">
        <label for="feedback-recovered" style="margin:0">조치 후 복구됨</label>
      </div>
      <div class="full">
        <button id="feedback-submit" disabled>분석 결과 저장</button>
        <span id="feedback-status" class="muted" style="margin-left:8px"></span>
      </div>
    </div>
  </div>

  <div id="exec" class="card hidden">
    <div><strong>실행 결과</strong> — <span id="exec-title" class="muted"></span></div>
    <div id="exec-status"></div>
    <pre id="exec-output"></pre>
  </div>
</div>

<script>
const MODE = "__MODE__";
const IS_CLIENT = MODE === "client";
const $ = (id) => document.getElementById(id);
const sel = $("scenario");
let currentErrorCode = null;
let currentRecommendation = null;
let currentGuidance = null;
let selectedVerdict = null;
let incidentItems = [];

document.querySelectorAll(".panel-toggle").forEach((btn) => {
  btn.addEventListener("click", () => {
    btn.closest(".card").classList.toggle("collapsed");
  });
});

function esc(value) {
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}
function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString("ko-KR");
}
async function loadIncidents() {
  try {
    const data = await getJSON("/api/v1/log-generator/incidents?minutes=60");
    incidentItems = data.incidents || [];
    $("stat-open").textContent = incidentItems.length + "건";
    $("stat-critical").textContent = incidentItems.filter((item) => item.severity === "CRITICAL").length + "건";
    $("stat-unack").textContent = incidentItems.filter((item) => item.status === "ACTION_REQUIRED").length + "건";
    $("stat-analyzing").textContent = incidentItems.filter((item) => item.status === "ANALYZING").length + "건";
  } catch (error) {
    /* stats stay at last known values */
  }
}
function showLogSource(panelId) {
  document.querySelectorAll(".logs-section").forEach((panel) => panel.classList.add("hidden"));
  const panel = $(panelId);
  if (panel) panel.classList.remove("hidden");
}
function setLogsVisible(visible) {
  $("log-tabs-panel").classList.toggle("hidden", !visible);
  if (visible) {
    const active = document.querySelector(".log-tab.selected");
    showLogSource(active.dataset.panel);
    pollActivity();
  } else {
    document.querySelectorAll(".logs-section").forEach((panel) => panel.classList.add("hidden"));
  }
  $("log-toggle").textContent = visible ? "로그 닫기" : "로그 조회";
}
$("refresh-incidents").addEventListener("click", loadIncidents);
$("log-toggle").addEventListener("click", () => setLogsVisible($("log-tabs-panel").classList.contains("hidden")));
$("log-close").addEventListener("click", () => setLogsVisible(false));
document.querySelectorAll(".log-tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".log-tab").forEach((candidate) => candidate.classList.toggle("selected", candidate === button));
    showLogSource(button.dataset.panel);
  });
});
loadIncidents();
setInterval(loadIncidents, 15000);

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

if (!IS_CLIENT) (async function loadScenarios() {
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
  setLogsVisible(true);
  $("result").classList.add("hidden");
  $("guidance-result").classList.add("hidden");
  $("exec").classList.add("hidden");
  $("log-output").innerHTML = "";
  $("fluentbit-output").textContent = "";
  $("qdrant-output").textContent = "";
  $("es-output").textContent = "";
  $("wait-status").textContent = "";
  currentSince = null;
  currentGuidance = null;
  selectedVerdict = null;

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

// 클라이언트 화면은 로그 패널이 없으므로 상태 문구를 상단 카드에 쓴다.
const statusEl = () => $(IS_CLIENT ? "client-status-text" : "wait-status");

async function waitForRecommendation(errorCode, since, isCurrent = () => true) {
  if (!IS_CLIENT) {
    statusEl().textContent =
      "fluent-bit가 로그를 전달하는 중… 추천 결과를 기다리는 중";
  }

  for (let i = 0; i < 80; i++) {
    await sleep(1500);
    if (!isCurrent()) return;
    if (!IS_CLIENT) await pollActivity();
    const data = await getJSON(
      `/api/v1/log-generator/latest-recommendation?error_code=${encodeURIComponent(errorCode)}&since=${encodeURIComponent(since)}`
    );
    if (!isCurrent()) return;
    if (data.status === "ready") {
      if (!IS_CLIENT) statusEl().textContent = "";
      renderRecommendation(errorCode, data.recommendation, data.decisions || []);
      await loadIncidents();
      return;
    }
  }

  statusEl().textContent = IS_CLIENT
    ? "분석 결과를 불러오지 못했습니다. 잠시 후 다시 확인하세요."
    : "추천 결과 대기 시간 초과 — fluentbit/Elasticsearch/Qdrant 상태를 확인하세요.";
}

// 클라이언트: 어드민에서 실행한 최신 장애 시나리오를 따라간다.
let clientRunId = null;
let clientRunPrefix = "";
function setClientStatus(state) {
  if (IS_CLIENT && clientRunPrefix) {
    $("client-status-text").textContent = `${clientRunPrefix} — ${state}`;
  }
}
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
if (IS_CLIENT) {
  followLatestRun();
  setInterval(followLatestRun, 3000);
}

function renderRecommendation(errorCode, rec, decisions = []) {
  if (rec && rec.status === "resource_guidance") {
    renderResourceGuidance(rec);
    setClientStatus("분석 완료");
    return;
  }
  currentErrorCode = errorCode;
  currentRecommendation = rec;
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

    const action = (rec.actions || []).find(
      (candidate) => candidate.script_id === rb.script_id
    );
    if (action) el.dataset.actionId = action.action_id;
    el.querySelector(".approve").addEventListener(
      "click", () => decideRunbook(rb.script_id, action, el, "approve")
    );
    el.querySelector(".reject").addEventListener(
      "click", () => decideRunbook(rb.script_id, action, el, "reject")
    );
    el.querySelector(".diagnose").addEventListener(
      "click", () => requestDiagnosis(errorCode, el)
    );

    // 이미 승인/거부한 Runbook은 새로고침해도 처리된 상태로 보여준다.
    const decided = action && decisions.find(
      (d) => d.action_id === action.action_id
    );
    if (decided) markDecided(el, decided.decision);

    box.appendChild(el);
  });

  // 한 추천에서는 조치 하나만 실행한다 - 이미 승인된 게 있으면 나머지를 잠근다.
  if (decisions.some((d) => d.decision === "approve")) lockOtherRunbooks();

  if (decisions.length) {
    const last = decisions[decisions.length - 1];
    showExecResult(last.script_id, last.result || {}, 200);
  }
  setClientStatus(decisions.some(
    (d) => d.decision === "approve" && d.result?.status === "success"
  ) ? "조치 완료" : "분석 완료");
}

const OTHER_ACTION_LOCKED = "다른 조치가 이미 실행되어 선택할 수 없습니다.";

function setDecisionButtonsDisabled(el, disabled) {
  el.querySelectorAll(".approve, .reject").forEach((b) => {
    b.disabled = disabled;
  });
}

// 아직 처리되지 않은 나머지 Runbook의 승인/거부를 막는다 (진단 요청은 허용).
function lockOtherRunbooks(exceptEl = null) {
  document.querySelectorAll("#actions .runbook").forEach((el) => {
    if (el === exceptEl || el.classList.contains("decided")) return;
    el.classList.add("locked");
    setDecisionButtonsDisabled(el, true);
    el.querySelector(".decision").textContent = OTHER_ACTION_LOCKED;
  });
}

function unlockOtherRunbooks() {
  document.querySelectorAll("#actions .runbook.locked").forEach((el) => {
    el.classList.remove("locked");
    setDecisionButtonsDisabled(el, false);
    el.querySelector(".decision").textContent = "";
  });
}

function markDecided(el, decision) {
  el.classList.add("decided");
  el.querySelector(".decision").textContent =
    decision === "approve" ? "✓ 승인됨" : "✗ 거부됨";
  setRunbookButtonsDisabled(el, true);
}

function showExecResult(scriptId, data, status) {
  $("exec").classList.remove("hidden");
  $("exec-title").textContent = scriptId;
  const ok = ["success", "rejected", "already_processed"].includes(data.status);
  const s = $("exec-status");
  s.className = ok ? "status-ok" : "status-err";
  s.textContent = `${data.status}` + (data.returncode !== undefined
    ? ` (exit ${data.returncode})` : ` (HTTP ${status})`);
  $("exec-output").textContent =
    (data.stdout || "") + (data.stderr ? "\\n[stderr]\\n" + data.stderr :
      (data.reason ? "\\n" + data.reason : ""));
}

function addList(container, title, items) {
  const section = document.createElement("div");
  section.className = "guidance-section";
  const heading = document.createElement("strong");
  heading.textContent = title;
  section.appendChild(heading);
  const list = document.createElement("ul");
  list.className = "guidance-list";
  (items || []).forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    list.appendChild(li);
  });
  section.appendChild(list);
  container.appendChild(section);
}

function renderResourceGuidance(guidance) {
  currentGuidance = guidance;
  selectedVerdict = null;
  currentErrorCode = guidance.original_error_code || null;
  $("result").classList.add("hidden");
  $("guidance-result").classList.remove("hidden");
  $("guidance-code").textContent =
    guidance.primary_problem_code || "RESOURCE GUIDANCE";
  $("guidance-summary").textContent = guidance.summary || "";
  $("guidance-log").textContent =
    `[${guidance.original_log?.level || "ERROR"}] `
    + (guidance.original_log?.message || "");

  const box = $("hypotheses");
  box.innerHTML = "";
  (guidance.hypotheses || []).forEach((hypothesis, index) => {
    const pct = Math.round(
      Math.max(0, Math.min(1, Number(hypothesis.confidence || 0))) * 100
    );
    const card = document.createElement("div");
    card.className = "hypothesis" + (index === 0 ? " primary" : "");

    const head = document.createElement("div");
    head.className = "hypothesis-head";
    const title = document.createElement("div");
    title.className = "hypothesis-title";
    title.textContent = `${index + 1}. ${hypothesis.title || hypothesis.problem_code}`;
    const confidence = document.createElement("div");
    confidence.className = "confidence";
    confidence.textContent = `${pct}%`;
    head.append(title, confidence);
    card.appendChild(head);

    const track = document.createElement("div");
    track.className = "confidence-track";
    const fill = document.createElement("div");
    fill.className = "confidence-fill";
    fill.style.width = `${pct}%`;
    track.appendChild(fill);
    card.appendChild(track);
    addList(card, "분석 근거", hypothesis.evidence);
    addList(card, "추가 확인 권장", hypothesis.suggested_diagnostics);
    box.appendChild(card);
  });

  const related = guidance.related_logs || [];
  $("guidance-related-logs").textContent = related.length
    ? related.map((log) =>
        `[${log.level || "ERROR"}] ${log.message || ""}`
      ).join("\\n")
    : "같은 호스트에서 최근 ERROR 로그를 찾지 못했습니다.";

  document.querySelectorAll(".feedback-choice").forEach((button) => {
    button.classList.remove("selected");
  });
  $("feedback-root-cause").value = "";
  $("feedback-action").value = "";
  $("feedback-recovered").checked = false;
  $("feedback-status").textContent = "";
  $("feedback-submit").disabled = true;
}

document.querySelectorAll(".feedback-choice").forEach((button) => {
  button.addEventListener("click", () => {
    selectedVerdict = button.dataset.verdict;
    document.querySelectorAll(".feedback-choice").forEach((candidate) => {
      candidate.classList.toggle("selected", candidate === button);
    });
    $("feedback-submit").disabled = false;
  });
});

$("feedback-submit").addEventListener("click", async () => {
  if (!currentGuidance || !selectedVerdict) return;
  const rootCause = $("feedback-root-cause").value.trim();
  const action = $("feedback-action").value.trim();
  const recovered = $("feedback-recovered").checked;
  if (selectedVerdict === "confirmed" && (!rootCause || !action || !recovered)) {
    $("feedback-status").className = "status-err";
    $("feedback-status").textContent =
      "원인 정확은 실제 원인·조치·복구 확인이 모두 필요합니다.";
    return;
  }

  $("feedback-submit").disabled = true;
  $("feedback-status").className = "status-pending";
  $("feedback-status").textContent = "저장 중…";
  try {
    const { ok, data } = await postJSON("/api/v1/guidance/feedback", {
      guidance_id: currentGuidance.guidance_id,
      operator: $("feedback-operator").value.trim() || "web-ui",
      verdict: selectedVerdict,
      confirmed_root_cause: rootCause || null,
      successful_action: action || null,
      recovered,
      confirmed_error_code: currentGuidance.original_error_code || null,
    });
    $("feedback-status").className = ok ? "status-ok" : "status-err";
    $("feedback-status").textContent = data.promoted_to_incident_case
      ? "검증된 장애 사례로 저장되고 Qdrant에 등록되었습니다."
      : (ok ? "운영자 피드백이 저장되었습니다." : JSON.stringify(data));
    if (!ok) $("feedback-submit").disabled = false;
  } catch (error) {
    $("feedback-status").className = "status-err";
    $("feedback-status").textContent = "저장 실패: " + error;
    $("feedback-submit").disabled = false;
  }
});

function setRunbookButtonsDisabled(el, disabled) {
  el.querySelectorAll(".buttons button").forEach((b) => {
    b.disabled = disabled;
  });
}

async function decideRunbook(scriptId, action, el, decision) {
  if (!currentErrorCode || !currentRecommendation || !action) {
    el.querySelector(".decision").textContent = "최신 Incident 추천을 다시 불러오세요.";
    return;
  }
  setRunbookButtonsDisabled(el, true);
  // 응답을 기다리는 동안 다른 조치를 누르지 못하게 먼저 잠근다.
  if (decision === "approve") lockOtherRunbooks(el);

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
      incident_id: currentRecommendation.incident_id,
      recommendation_id: currentRecommendation.recommendation_id,
      action_id: action.action_id,
      incident_version: currentRecommendation.incident_version,
      approved_by: "web-ui",
    });
    showExecResult(scriptId, data, status);
    if (data.status === "blocked" && data.approved_action_id) {
      // 다른 화면/사용자가 먼저 다른 조치를 승인한 경우
      const approvedEl = document.querySelector(
        `#actions .runbook[data-action-id="${data.approved_action_id}"]`
      );
      if (approvedEl) markDecided(approvedEl, "approve");
      el.classList.add("locked");
      setRunbookButtonsDisabled(el, false);
      setDecisionButtonsDisabled(el, true);
      el.querySelector(".decision").textContent =
        `${OTHER_ACTION_LOCKED} (실행된 조치: ${data.approved_script_id})`;
      lockOtherRunbooks(el);
      return;
    }
    if (decision === "approve" && !data.execution_id) {
      // 검증 실패 등으로 스크립트가 실행되지 않았으면 잠금을 푼다.
      setRunbookButtonsDisabled(el, false);
      unlockOtherRunbooks();
      return;
    }
    markDecided(el, decision);
    if (decision === "approve" && data.status === "success") {
      setClientStatus("조치 완료");
    }
    await loadIncidents();
  } catch (e) {
    $("exec-status").className = "status-err";
    $("exec-status").textContent = "요청 실패: " + e;
    setRunbookButtonsDisabled(el, false);
    if (decision === "approve") unlockOtherRunbooks();
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


def _render(mode: str, title_suffix: str) -> Response:
    page = (
        _PAGE.replace("__MODE__", mode)
        .replace("__TITLE_SUFFIX__", title_suffix)
    )
    return Response(page, mimetype="text/html")


@web_blueprint.get("/")
@web_blueprint.get("/admin")
def admin() -> Response:
    """장애 시나리오 실행·수집/분석 로그까지 보이는 운영자(어드민) 화면."""
    return _render("admin", " (Admin)")


@web_blueprint.get("/client")
def client() -> Response:
    """오류 내용(원인·Runbook/리소스 가이드)만 보이는 클라이언트 화면.

    어드민에서 시나리오를 실행하면 latest-run 폴링으로 같은 장애를 따라간다.
    """
    return _render("client", "")

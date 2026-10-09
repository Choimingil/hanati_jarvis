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
  .incident-stat { background:var(--card); color:var(--fg); border:1px solid var(--border); border-radius:10px; padding:13px; text-align:left; }
  .incident-stat:hover { border-color:var(--accent); }
  .incident-stat.selected { border-color:var(--accent); background:var(--bar); }
  .incident-stat:focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
  .incident-stat span { display:block; color:var(--muted); font-size:12px; }
  .incident-stat strong { display:block; margin-top:3px; }
  .incident-table-wrap { overflow-x:auto; margin-top:12px; }
  .incident-table { width:100%; border-collapse:collapse; font-size:14px; }
  .incident-table th, .incident-table td { padding:10px; border-bottom:1px solid var(--border); text-align:left; vertical-align:top; }
  .incident-table th { color:var(--muted); white-space:nowrap; }
  .incident-message { min-width:180px; overflow-wrap:anywhere; }
  button.incident-detail { background:transparent; color:var(--accent); text-align:left; white-space:normal; padding:0; width:100%; min-height:44px; }
  .incident-preview { display:block; font-weight:400; margin-top:4px; }
  .incident-table tr.recent-incident td { border-top:2px solid var(--err); border-bottom:2px solid var(--err); background:rgba(209,54,74,.08); }
  .incident-table tr.recent-incident td:first-child { border-left:2px solid var(--err); }
  .incident-table tr.recent-incident td:last-child { border-right:2px solid var(--err); }
  .recent-incident-badge { color:var(--err); font-size:12px; font-weight:700; margin-left:8px; }
  .card.recent-incident { border:2px solid var(--err); }
  .incident-fields { display:grid; grid-template-columns:100px 1fr; gap:8px 14px; margin:14px 0; font-size:14px; }
  .incident-fields dt { color:var(--muted); }
  .incident-fields dd { margin:0; overflow-wrap:anywhere; }
  .component-status { display:flex; gap:8px 18px; flex-wrap:wrap; margin-top:8px; font-size:13px; }
  .log-tabs { display:flex; gap:8px; flex-wrap:wrap; }
  button.log-tab { background:transparent; color:var(--accent); border:1px solid var(--accent); padding:8px 12px; }
  button.log-tab.selected { background:var(--accent); color:var(--accent-fg); }
  .scenario-card { margin-top:0; }
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
  <div class="card scenario-card admin-only">
    <div class="row">
      <div>
        <label for="scenario">장애 시나리오 (log_generator/main.py 시나리오)</label>
        <select id="scenario"></select>
      </div>
      <button id="analyze" disabled>분석</button>
    </div>
  </div>
  <div class="console-head">
    <div><h1>Hanati Jarvis — 장애 대응 콘솔__TITLE_SUFFIX__</h1><p class="sub">로그·리소스 분석 → Runbook 추천 또는 Resource Guidance → 운영자 확인 → 안전한 조치·학습</p></div>
    <div class="console-actions"><button id="refresh-incidents" class="secondary">새로고침</button><button id="log-toggle" class="admin-only">로그 조회</button></div>
  </div>
  <div class="card"><strong>수집·분석 상태</strong><div id="operations-status">상태 확인 중…</div><div id="operations-components" class="component-status"></div><div id="collection-hosts"></div></div>
  <div class="incident-stats" role="tablist" aria-label="장애 상태">
    <button id="incident-tab-open" type="button" class="incident-stat selected" role="tab" aria-selected="true" aria-controls="incident-list-panel" data-filter="open"><span>진행중</span><strong id="stat-open">0건</strong></button>
    <button id="incident-tab-critical" type="button" class="incident-stat" role="tab" aria-selected="false" aria-controls="incident-list-panel" tabindex="-1" data-filter="critical"><span>긴급</span><strong id="stat-critical">0건</strong></button>
    <button id="incident-tab-unack" type="button" class="incident-stat" role="tab" aria-selected="false" aria-controls="incident-list-panel" tabindex="-1" data-filter="unack"><span>미확인</span><strong id="stat-unack">0건</strong></button>
    <button id="incident-tab-analyzing" type="button" class="incident-stat" role="tab" aria-selected="false" aria-controls="incident-list-panel" tabindex="-1" data-filter="analyzing"><span>분석중</span><strong id="stat-analyzing">0건</strong></button>
  </div>
  <div id="incident-list-panel" class="card" role="tabpanel" aria-labelledby="incident-tab-open" tabindex="0">
    <div class="card-head"><strong id="incident-list-title">진행중 장애</strong><span class="muted">최근 10분</span></div>
    <div id="incident-list-status" class="muted" role="status">장애 목록을 불러오는 중…</div>
    <div id="incident-sync-status" class="muted client-only" role="status"></div>
    <div id="incident-list" class="incident-table-wrap"></div>
  </div>
  <div id="incident-detail-panel" class="card hidden" aria-labelledby="incident-detail-title" tabindex="-1">
    <div class="card-head"><strong id="incident-detail-title">장애 상세</strong><button id="incident-detail-close" class="secondary" type="button">닫기</button></div>
    <div id="incident-detail-load-status" class="muted" role="status"></div>
    <dl id="incident-detail-fields" class="incident-fields"></dl>
    <strong>발생 내용</strong><pre id="incident-detail-message"></pre>
    <div class="guidance-section"><strong>해당 장애의 최근 10분 로그 (최대 20건)</strong></div>
    <div id="incident-detail-logs-status" class="muted"></div>
    <pre id="incident-detail-logs"></pre>
  </div>
  <div id="log-tabs-panel" class="card hidden admin-only">
    <div class="card-head"><div><strong>수집·분석 로그</strong><span class="muted">(선택한 시점 이후분)</span></div><button id="log-close" class="panel-toggle" type="button">닫기</button></div>
    <div class="log-tabs" style="margin-top:12px">
      <button class="log-tab selected" data-panel="log">log_generator</button>
      <button class="log-tab" data-panel="fluentbit-panel">Fluent Bit</button>
      <button class="log-tab" data-panel="internal-panel">Elasticsearch/Qdrant</button>
      <button class="log-tab" data-panel="redis-panel">Redis</button>
      <button class="log-tab" data-panel="worker-panel">Worker</button>
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

  <div id="redis-panel" class="card hidden logs-section admin-only">
    <div class="card-head"><strong>Redis 큐 로그</strong><button class="panel-toggle" type="button" aria-label="접기/펼치기"><span class="chev">▾</span></button></div>
    <div class="panel-body"><p class="muted">현재 큐 상태와 조회 구간의 접수·재시도·실패 보관 기록</p><pre id="redis-output"></pre></div>
  </div>
  <div id="worker-panel" class="card hidden logs-section admin-only">
    <div class="card-head"><strong>Worker 처리 로그</strong><button class="panel-toggle" type="button" aria-label="접기/펼치기"><span class="chev">▾</span></button></div>
    <div class="panel-body"><p class="muted">현재 생존 신호와 조회 구간의 작업별 분석 시작·완료·오류 기록</p><pre id="worker-output"></pre></div>
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
    <button id="refresh-execution" class="secondary hidden">실행 결과 다시 확인</button>
    <button id="verify-execution" class="secondary hidden">업무 복구 확인</button>
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
let selectedIncidentFilter = "open";
let incidentsLoaded = false;
let selectedIncidentId = null;
let incidentDetailRequest = 0;
let detailRecommendationKey = null;
let incidentClockOffset = 0;
let incidentLoadInFlight = null;
let clientSyncInFlight = null;
let clientSyncedRun = null;
let clientRunCaughtUp = false;
let clientSyncDelayed = false;
let clientRunSelectionVersion = 0;
let autoSelectedIncidentId = null;
let manualSelectionVersion = 0;
let activityLoadInFlight = null;
const incidentFilters = {
  open: {label: "진행중", matches: (item) => item.status !== "RESOLVED"},
  critical: {label: "긴급", matches: (item) => item.severity === "CRITICAL"},
  unack: {label: "미확인", matches: (item) => item.status === "ACTION_REQUIRED"},
  analyzing: {label: "분석중", matches: (item) => item.status === "ANALYZING"},
};
let lastExecutionId = null;
function actionBody(action, el) {
  const selected = el.querySelector(".target-select").value;
  return {
    incident_id: currentRecommendation.incident_id,
    recommendation_id: currentRecommendation.recommendation_id,
    action_id: action.action_id,
    incident_version: currentRecommendation.incident_version,
    approved_by: "web-ui",
    target: selected === "" ? null : el.targets[Number(selected)],
    preflight_id: el.preflightId || null,
  };
}
function schedulePoll(callback, interval, maxDelay = 60000) {
  let delay=interval;
  async function tick() {
    if (!document.hidden) {
      try { const ok=await callback(); delay=ok===false ? Math.min(maxDelay,delay*2) : interval; }
      catch (_) { delay=Math.min(maxDelay,delay*2); }
    }
    setTimeout(tick,delay);
  }
  tick();
}
async function loadOperationsStatus() {
  try {
    const data = await getJSON("/api/v1/operations/status");
    $("operations-status").textContent = `${data.status} / 확인 시각: ${data.checked_at} / 대기 ${data.queue?.stream_length || 0}건 / 실패 보관 ${data.queue?.dead_letters || 0}건`;
    $("collection-hosts").textContent = (data.hosts || []).map(h => `${h.host}: ${h.status} (마지막 수집 ${h.last_sample_at || "없음"})${h.connections_access_denied ? " / 연결 조회 권한 부족" : ""}`).join(" · ");
    const names = {redis: "Redis", elasticsearch: "Elasticsearch", qdrant: "Qdrant", analysis_workers: "분석 Worker"};
    $("operations-components").innerHTML = Object.entries(data.components || {}).map(([key, value]) =>
      '<span class="' + (value.healthy ? 'status-ok' : 'status-err') + '">' + esc(names[key] || key) + ': ' + (value.healthy ? '연결 정상' : '확인 필요') + (value.error ? ' (' + esc(value.error) + ')' : '') + '</span>'
    ).join("");
  } catch (error) { $("operations-status").textContent = "상태 조회 실패 — 현재 표시된 데이터가 최신인지 확인하세요."; return false; }
}
schedulePoll(loadOperationsStatus,15000);
$("refresh-execution").addEventListener("click", async () => {
  if (!lastExecutionId) return;
  const data = await getJSON("/api/v1/remediations/executions/" + encodeURIComponent(lastExecutionId));
  showExecResult("실행 결과", {...data.result,execution_id:lastExecutionId},200);
});
$("verify-execution").addEventListener("click", async () => {
  if (!lastExecutionId) return;
  const {data} = await postJSON("/api/v1/remediations/verify", {execution_id:lastExecutionId});
  $("exec-output").textContent = JSON.stringify(data,null,2);
  $("exec-status").textContent = data.recovered ? "업무 복구 확인 완료" : "업무 복구 미확인";
  await loadIncidents();
});

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
function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("ko-KR");
}
function isRecentIncident(value) {
  const timestamp = Date.parse(value);
  const age = Date.now() + incidentClockOffset - timestamp;
  return Number.isFinite(timestamp) && age >= 0 && age < 60000;
}
function refreshRecentIncidents() {
  document.querySelectorAll("#incident-list tbody tr").forEach(row => {
    const recent = isRecentIncident(row.dataset.lastSeen);
    row.classList.toggle("recent-incident", recent);
    row.querySelector(".recent-incident-badge").classList.toggle("hidden", !recent);
  });
  $("incident-detail-panel").classList.toggle("recent-incident", isRecentIncident($("incident-detail-panel").dataset.lastSeen));
}
function renderIncidentDetails(incident) {
  const statuses = {DETECTED: "감지됨", ANALYZING: "분석중", ACTION_REQUIRED: "미확인 · 조치 필요", INVESTIGATING: "조사중", REMEDIATING: "조치중", MONITORING: "복구 확인중", RESOLVED: "해결됨", REOPENED: "재발"};
  const origin = incident.synthetic === true ? "모의 시나리오" : incident.source_type === "metric" ? "리소스 감지" : "수집 로그";
  const fields = [
    ["단위시스템", incident.service || "unknown"],
    ["환경", incident.environment || "unknown"],
    ["영향 호스트", (incident.affected_hosts || incident.hosts || []).join(", ") || "-"],
    ["발생 구간", (incident.sources || []).join(", ") || "-"],
    ["감지 유형", origin],
    ["장애 코드", incident.error_code || "UNKNOWN_ERROR"],
    ["장애 상태", statuses[incident.status] || incident.status || "-"],
    ["심각도", incident.severity || "-"],
    ["발생 수", String(incident.occurrence_count || 0) + "건"],
    ["최초 발생", formatDateTime(incident.first_seen)],
    ["최근 발생", formatDateTime(incident.last_seen)],
    ["장애 ID", incident.incident_id],
  ];
  $("incident-detail-fields").innerHTML = fields.map(([label, value]) => '<dt>' + esc(label) + '</dt><dd>' + esc(value) + '</dd>').join("");
  $("incident-detail-message").textContent = incident.latest_message || incident.representative_message || incident.normalized_message || "발생 내용 없음";
  $("incident-detail-panel").dataset.lastSeen = incident.last_seen || "";
  refreshRecentIncidents();
}
function closeIncidentDetails() {
  selectedIncidentId = null;
  incidentDetailRequest += 1;
  $("incident-detail-panel").classList.add("hidden");
  $("result").classList.add("hidden");
  $("guidance-result").classList.add("hidden");
  $("exec").classList.add("hidden");
  currentRecommendation = null;
  currentGuidance = null;
  detailRecommendationKey = null;
}
async function loadIncidentDetails(incident, scroll = false, refresh = false) {
  const requestId = ++incidentDetailRequest;
  selectedIncidentId = incident.incident_id;
  $("incident-detail-panel").classList.remove("hidden");
  if (!refresh) {
    $("result").classList.add("hidden");
    $("guidance-result").classList.add("hidden");
    $("exec").classList.add("hidden");
    currentRecommendation = null;
    currentGuidance = null;
    detailRecommendationKey = null;
  }
  renderIncidentDetails(incident);
  $("incident-detail-load-status").textContent = "최신 장애 정보를 확인하는 중…";
  $("incident-detail-logs-status").textContent = "";
  $("incident-detail-logs").textContent = "";
  if (scroll) {
    $("incident-detail-panel").scrollIntoView({behavior: "smooth", block: "start"});
    $("incident-detail-panel").focus({preventScroll: true});
  }
  try {
    const data = await getJSON("/api/v1/log-generator/incidents/" + encodeURIComponent(incident.incident_id));
    if (requestId !== incidentDetailRequest) return;
    const latest = data.incident;
    renderIncidentDetails(latest);
    $("incident-detail-load-status").textContent = "";
    $("incident-detail-logs-status").textContent = data.logs_status === "unavailable"
      ? "관련 로그 조회 실패 — 장애 정보는 조회되었습니다."
      : ((data.logs || []).length ? "" : "최근 10분 내 이 장애에 연결된 로그가 없습니다.");
    $("incident-detail-logs").textContent = (data.logs || []).map(log =>
      `[${formatDateTime(log.timestamp || log.received_at)}] ${log.service || latest.service} / ${log.host || "unknown"} / ${log.source || log.raw?.source || "log"}\\n${log.message || ""}`
    ).join("\\n\\n");
    clientRunPrefix = latest.service + " / " + latest.incident_id;
    const rec = latest.latest_recommendation;
    const recommendationKey = JSON.stringify([latest.incident_id, latest.status, latest.version, rec?.recommendation_id]);
    if (detailRecommendationKey !== recommendationKey) {
      $("result").classList.add("hidden");
      $("guidance-result").classList.add("hidden");
      currentRecommendation = null;
      currentGuidance = null;
      if (rec) {
        renderRecommendation(latest.error_code, rec);
        if (latest.status !== "ACTION_REQUIRED") {
          document.querySelectorAll("#actions .runbook").forEach(el => {
            el.actionable = false;
            setRunbookButtonsDisabled(el, true);
          });
        }
      }
      detailRecommendationKey = recommendationKey;
    }
    if (!rec) $("incident-detail-load-status").textContent = "분석 중이거나 조치 추천이 아직 없습니다.";
    setClientStatus("장애 상세 조회: " + latest.status);
  } catch (error) {
    if (requestId !== incidentDetailRequest) return;
    $("incident-detail-load-status").textContent = "최신 상세 조회 실패 — 목록에 있던 정보를 표시합니다. 장애 항목을 다시 눌러 재조회하세요.";
  }
}
$("incident-detail-close").addEventListener("click", () => {
  manualSelectionVersion += 1;
  autoSelectedIncidentId = null;
  closeIncidentDetails();
});
function renderIncidentList() {
  const filter = incidentFilters[selectedIncidentFilter];
  const items = incidentItems.filter(filter.matches);
  $("incident-list-title").textContent = filter.label + " 장애" + (incidentsLoaded ? " · " + items.length + "건" : "");
  $("incident-list").innerHTML = items.length
    ? '<table class="incident-table"><thead><tr><th scope="col">장애 내용</th><th scope="col">발생 수</th><th scope="col">최근 발생</th></tr></thead><tbody>' + items.map((item, index) => `
      <tr>
        <td class="incident-message"><button type="button" class="incident-detail" aria-controls="incident-detail-panel" data-index="${index}"><strong>${esc(item.error_code || "UNKNOWN_ERROR")}</strong><span class="recent-incident-badge hidden">최근 1분</span><span class="muted incident-preview">${esc(item.latest_message || item.representative_message || item.normalized_message || "")}</span></button></td>
        <td>${esc(item.occurrence_count)}</td><td>${esc(formatTime(item.last_seen))}</td>
      </tr>`
    ).join("") + "</tbody></table>"
    : (incidentsLoaded ? '<p class="muted">' + esc(filter.label) + ' 조건에 해당하는 장애가 없습니다.</p>' : "");
  $("incident-list").querySelectorAll(".incident-detail").forEach(button => button.addEventListener("click", () => {
    manualSelectionVersion += 1;
    autoSelectedIncidentId = null;
    const incident = items[Number(button.dataset.index)];
    loadIncidentDetails(incident, true);
  }));
  $("incident-list").querySelectorAll("tbody tr").forEach((row, index) => row.dataset.lastSeen = items[index].last_seen || "");
  refreshRecentIncidents();
}
function selectIncidentFilter(key) {
  if (!incidentFilters[key]) return;
  manualSelectionVersion += 1;
  autoSelectedIncidentId = null;
  if (selectedIncidentId && selectedIncidentFilter !== key) closeIncidentDetails();
  selectedIncidentFilter = key;
  document.querySelectorAll(".incident-stat").forEach(button => {
    const selected = button.dataset.filter === key;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  $("incident-list-panel").setAttribute("aria-labelledby", "incident-tab-" + key);
  renderIncidentList();
}
const incidentTabs = Array.from(document.querySelectorAll(".incident-stat"));
incidentTabs.forEach((button, index) => {
  button.addEventListener("click", () => selectIncidentFilter(button.dataset.filter));
  button.addEventListener("keydown", event => {
    let next;
    if (event.key === "ArrowRight") next = (index + 1) % incidentTabs.length;
    else if (event.key === "ArrowLeft") next = (index + incidentTabs.length - 1) % incidentTabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = incidentTabs.length - 1;
    else return;
    event.preventDefault();
    incidentTabs[next].focus();
    selectIncidentFilter(incidentTabs[next].dataset.filter);
  });
});
function loadIncidents() {
  if (!incidentLoadInFlight) {
    incidentLoadInFlight = fetchIncidents().finally(() => { incidentLoadInFlight = null; });
  }
  return incidentLoadInFlight;
}
async function fetchIncidents() {
  try {
    const data = await getJSON("/api/v1/log-generator/incidents?minutes=10");
    const serverTime = Date.parse(data.server_time);
    if (Number.isFinite(serverTime)) incidentClockOffset = serverTime - Date.now();
    incidentItems = data.incidents || [];
    incidentsLoaded = true;
    Object.entries(incidentFilters).forEach(([key, filter]) => {
      $("stat-" + key).textContent = incidentItems.filter(filter.matches).length + "건";
    });
    $("incident-list-status").textContent = "";
    renderIncidentList();
    if (selectedIncidentId) {
      const selected = incidentItems.find(item => item.incident_id === selectedIncidentId && incidentFilters[selectedIncidentFilter].matches(item));
      if (selected) await loadIncidentDetails(selected, false, true);
      else closeIncidentDetails();
    }
  } catch (error) {
    $("incident-list-status").textContent = incidentsLoaded
      ? "장애 목록 조회 실패 — 마지막 조회 결과를 표시하고 있습니다."
      : "장애 목록 조회 실패 — 새로고침으로 다시 시도하세요.";
    return false;
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
    pollActivity();
  });
});
schedulePoll(loadIncidents, IS_CLIENT ? 5000 : 2000);
schedulePoll(refreshRecentIncidents,1000);
schedulePoll(() => {
  if (!IS_CLIENT && !$("log-tabs-panel").classList.contains("hidden")) return pollActivity();
},2000);

async function getJSON(url) {
  const res = await fetch(url);
  const data = await res.json();
  if (!res.ok) throw new Error(data.reason || data.status || "조회 실패");
  return data;
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
  closeIncidentDetails();
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
  $("redis-output").textContent = "";
  $("worker-output").textContent = "";
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

function pollActivity() {
  if (!activityLoadInFlight) {
    activityLoadInFlight = fetchActivity().finally(() => { activityLoadInFlight = null; });
  }
  return activityLoadInFlight;
}
async function fetchActivity() {
  try {
    const since = currentSince;
    const params = new URLSearchParams();
    if (since) params.set("since", since);
    const data = await getJSON(
      `/api/v1/log-generator/activity?${params}`
    );
    if (since !== currentSince) return;
    $("fluentbit-output").textContent =
      (data.fluentbit_log || []).join("\\n");
    $("fluentbit-output").scrollTop = $("fluentbit-output").scrollHeight;
    $("qdrant-output").textContent =
      (data.qdrant_log || []).join("\\n");
    $("qdrant-output").scrollTop = $("qdrant-output").scrollHeight;
    $("es-output").textContent =
      (data.elasticsearch_log || []).join("\\n");
    $("es-output").scrollTop = $("es-output").scrollHeight;
    $("redis-output").textContent = (data.redis_log || []).join("\\n");
    $("worker-output").textContent = (data.worker_log || []).join("\\n");
    $("redis-output").scrollTop = $("redis-output").scrollHeight;
    $("worker-output").scrollTop = $("worker-output").scrollHeight;
  } catch (e) {
    $("wait-status").textContent = "로그 조회 지연 — 마지막 표시 데이터 이후 상태를 확인 중입니다.";
    return false;
  }
}

// Client synchronization messages live inside the incident list, without a separate card.
const statusEl = () => $(IS_CLIENT ? "incident-sync-status" : "wait-status");

async function waitForRecommendation(errorCode, since, isCurrent = () => true) {
  if (!IS_CLIENT) {
    statusEl().textContent =
      "fluent-bit가 로그를 전달하는 중… 추천 결과를 기다리는 중";
  }

  for (let i = 0; i < 80; i++) {
    await sleep(1500);
    if (!isCurrent()) return;
    if (!IS_CLIENT && !document.hidden) await pollActivity();
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
let clientRunPrefix = "";
function setClientStatus(state) {
  if (IS_CLIENT && clientRunPrefix) {
    $("incident-sync-status").textContent = `${clientRunPrefix} — ${state}`;
  }
}
function syncClientRun() {
  if (!clientSyncInFlight) {
    clientSyncInFlight = fetchClientRun().finally(() => { clientSyncInFlight = null; });
  }
  return clientSyncInFlight;
}
async function fetchClientRun() {
  const selectionVersion = manualSelectionVersion;
  try {
    const data = await getJSON("/api/v1/log-generator/latest-run");
    if (clientSyncDelayed) {
      if (data.status === "ready") setClientStatus("관리자 장애 동기화 연결 복구");
      else $("incident-sync-status").textContent = "";
      clientSyncDelayed = false;
    }
    if (data.status !== "ready") return;
    const run = data.run;
    const newRun = clientSyncedRun?.run_id !== run.run_id;
    if (newRun) {
      clientSyncedRun = run;
      clientRunCaughtUp = false;
      clientRunSelectionVersion = selectionVersion;
      clientRunPrefix = run.label || run.error_code;
      setClientStatus("관리자 시나리오 수신 — 장애 발생·분석 결과를 확인하는 중…");
    }
    if (run.phase === "failed") {
      if (newRun || clientSyncedRun.phase !== "failed") await loadIncidents();
      clientSyncedRun = run;
      setClientStatus("시나리오 실행 실패 — 발생한 로그가 있으면 장애 목록에서 확인하세요.");
      return;
    }
    clientSyncedRun = run;
    const age = Date.now() + incidentClockOffset - Date.parse(run.triggered_at);
    if (clientRunCaughtUp || age > 120000) return;
    if (await loadIncidents() === false) return false;
    const incident = incidentItems.find(item => item.error_code === run.error_code
      && item.synthetic === true && Date.parse(item.last_seen) >= Date.parse(run.triggered_at));
    if (!incident) return;
    if (selectionVersion === manualSelectionVersion
        && clientRunSelectionVersion === manualSelectionVersion
        && (!selectedIncidentId || selectedIncidentId === autoSelectedIncidentId)
        && incidentFilters[selectedIncidentFilter].matches(incident)) {
      if (selectedIncidentId !== incident.incident_id) {
        autoSelectedIncidentId = incident.incident_id;
        await loadIncidentDetails(incident);
      }
    }
    clientRunCaughtUp = run.phase === "completed" && Boolean(incident.latest_recommendation);
  } catch (error) {
    clientSyncDelayed = true;
    $("incident-sync-status").textContent = "관리자 장애 동기화 지연 — 연결을 다시 확인하고 있습니다.";
    return false;
  }
}
if (IS_CLIENT) schedulePoll(syncClientRun,1000,5000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    refreshRecentIncidents();
    loadIncidents();
    if (IS_CLIENT) syncClientRun();
  }
});
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
    const pct = Number.isFinite(Number(rb.confidence)) ? Math.max(0, Math.min(100, Number(rb.confidence))) : 0;
    const el = document.createElement("div");
    el.className = "runbook";
    el.innerHTML = `
      <div class="runbook-tag">조치 제안</div>
      <dl>
        <dt>장애</dt><dd>${esc(rb.incident)}</dd>
        <dt>추정 원인</dt><dd>${esc(rb.estimated_cause)}</dd>
        <dt>신뢰도</dt><dd>${pct}%
          <div class="confidence-bar"><span style="width:${pct}%"></span></div>
        </dd>
        <dt>조치</dt><dd>${esc(rb.action)}</dd>
        <dt>예상 영향</dt><dd>${esc(rb.expected_impact)}</dd>
        <dt>과거 실행</dt><dd>성공 ${Number(rb.history?.success || 0)}회 / 실패 ${Number(rb.history?.failure || 0)}회</dd>
        <dt>실패 시</dt><dd class="rollback">${esc(rb.rollback)}</dd>
      </dl>
      <label>조치 대상 (환경 / 서비스 / 호스트 / 인스턴스)</label>
      <select class="target-select"></select>
      <p class="muted">실행 전 검사는 대상과 실행 조건을 확인합니다. 검사 통과 후 별도 승인을 눌러야 실제 조치가 실행됩니다.</p>
      <div class="preflight-status muted" role="status"></div>
      <details><summary>검사 응답 상세</summary><pre class="preflight-output"></pre></details>
      <div class="decision"></div>
      <div class="buttons">
        <button class="preflight">실행 전 검사</button>
        <button class="approve" disabled>검사 결과 확인 후 승인</button>
        <button class="reject">거부</button>
        <button class="diagnose">진단 요청</button>
      </div>`;

    const action = (rec.actions || []).find(
      (candidate) => candidate.script_id === rb.script_id
    );
    if (action) el.dataset.actionId = action.action_id;
    el.action = action;
    el.actionable = true;
    el.preflightRequest = 0;
    const targetSelect = el.querySelector(".target-select");
    const targets = rec.targets || [];
    el.targets = targets;
    const empty = document.createElement("option");
    empty.value = ""; empty.textContent = targets.length ? "대상을 선택하세요" : "이 사건에 등록된 실행 대상이 없습니다";
    targetSelect.appendChild(empty);
    targetSelect.disabled = !targets.length;
    targets.forEach((target, index) => {
      const option = document.createElement("option"); option.value = String(index);
      option.textContent = [target.environment, target.service, target.host, target.instance].join(" / ");
      targetSelect.appendChild(option);
    });
    targetSelect.addEventListener("change", () => {
      el.preflightRequest += 1;
      el.preflightPending = false;
      el.preflightId = null; el.querySelector(".approve").disabled = true;
      el.querySelector(".preflight-output").textContent = "";
      el.querySelector(".preflight-status").className = "preflight-status muted";
      el.querySelector(".preflight-status").textContent = preflightHint(el);
      setRunbookButtonsDisabled(el, false);
    });
    el.querySelector(".preflight").addEventListener("click", async () => {
      const requestId = ++el.preflightRequest;
      el.preflightPending = true;
      el.preflightId = null;
      setRunbookButtonsDisabled(el, true);
      el.querySelector(".preflight-status").className = "preflight-status status-pending";
      el.querySelector(".preflight-status").textContent = "실행 조건을 확인하는 중…";
      try {
        const {ok, data} = await postJSON("/api/v1/remediations/preflight", actionBody(action,el));
        if (requestId !== el.preflightRequest || !el.isConnected) return;
        el.querySelector(".preflight-output").textContent = JSON.stringify(data,null,2);
        el.preflightId = ok && data.status === "ready" ? data.preflight_id : null;
        renderPreflightStatus(el, data);
        if (el.preflightId) {
          const proofId = el.preflightId;
          setTimeout(() => {
            if (el.preflightId !== proofId || !el.isConnected) return;
            el.preflightId = null;
            el.querySelector(".preflight-status").className = "preflight-status status-pending";
            el.querySelector(".preflight-status").textContent = "검사 유효 시간이 지났습니다. 실행 전 검사를 다시 수행하세요.";
            setRunbookButtonsDisabled(el, false);
          }, (Number(data.expires_in_seconds) || 120) * 1000);
        }
      } catch (error) {
        if (requestId !== el.preflightRequest || !el.isConnected) return;
        el.preflightId = null;
        el.querySelector(".preflight-status").className = "preflight-status status-err";
        el.querySelector(".preflight-status").textContent = "검사 요청 실패 — 연결 상태를 확인하고 다시 검사하세요.";
        el.querySelector(".preflight-output").textContent = "검사 실패: " + error;
      } finally {
        if (requestId === el.preflightRequest) {
          el.preflightPending = false;
          setRunbookButtonsDisabled(el, false);
        }
      }
    });
    el.querySelector(".approve").addEventListener(
      "click", () => decideRunbook(rb.script_id, action, el, "approve")
    );
    el.querySelector(".reject").addEventListener(
      "click", () => decideRunbook(rb.script_id, action, el, "reject")
    );
    el.querySelector(".diagnose").addEventListener(
      "click", () => requestDiagnosis(action, el)
    );

    // 이미 승인/거부한 Runbook은 새로고침해도 처리된 상태로 보여준다.
    const decided = action && decisions.find(
      (d) => d.action_id === action.action_id
    );
    if (decided) markDecided(el, decided.decision);

    box.appendChild(el);
    el.querySelector(".preflight-status").textContent = preflightHint(el);
    setRunbookButtonsDisabled(el, el.classList.contains("decided"));
  });

  // 한 추천에서는 조치 하나만 실행한다 - 이미 승인된 게 있으면 나머지를 잠근다.
  if (decisions.some((d) => d.decision === "approve")) lockOtherRunbooks();

  if (decisions.length) {
    const last = decisions[decisions.length - 1];
    showExecResult(last.script_id, last.result || {}, 200);
  }
  setClientStatus(decisions.some(
    (d) => d.decision === "approve" && d.result?.status === "success"
  ) ? "명령 실행 완료 — 업무 복구 확인 필요" : "분석 완료");
}

const OTHER_ACTION_LOCKED = "다른 조치가 이미 실행되어 선택할 수 없습니다.";

function preflightHint(el) {
  if (!el.action) return "이 추천에는 자동 실행 가능한 조치가 없습니다. 분석 내용과 진단 항목을 확인하세요.";
  if (!el.targets.length) return "이 장애의 환경·서비스·호스트와 일치하는 실행 대상이 등록되지 않았습니다. 모의 장애는 실제 컨테이너에 자동 연결되지 않습니다.";
  return el.querySelector(".target-select").value === ""
    ? "조치 대상을 먼저 선택한 뒤 실행 전 검사를 누르세요."
    : "실행 전 검사로 조건을 확인하세요. 검사만으로는 조치가 실행되지 않습니다.";
}
function renderPreflightStatus(el, data) {
  const checks = {redundancy:"이중화 컨테이너 정상", maintenance:"점검 상태 아님", rollback_ready:"실행 상태 복원 가능", host_idle:"진행 중인 실행 없음"};
  const reasons = {
    "action not enabled in host manifest":"Agent 설정에서 이 작업이 비활성화되어 있습니다.",
    "target not bound to recommendation":"선택한 대상이 이 장애의 추천과 연결되지 않았습니다.",
    "agent machine credential not configured":"실행 Agent 인증 값이 설정되지 않았습니다.",
    "agent machine credential rejected":"실행 Agent가 인증을 거절했습니다. 인증 설정을 확인하세요.",
    "stale recommendation":"장애 또는 추천이 갱신되었습니다. 최신 장애 상세에서 다시 검사하세요.",
    "expired recommendation":"추천 유효 시간이 지났습니다. 최신 분석 결과가 필요합니다.",
    "incident is not actionable":"현재 장애 상태에서는 조치를 실행할 수 없습니다.",
    "host is executing or waiting for business recovery confirmation":"대상이 다른 조치를 실행 중이거나 복구 확인을 기다리고 있습니다.",
    "dependency unavailable; inspect service status":"실행 Agent 또는 저장소에 연결할 수 없습니다. 기동·연결 상태를 확인하세요.",
    "container is not the registered Compose service":"등록한 Compose 프로젝트·서비스와 실제 컨테이너가 다릅니다.",
    "container image differs from approved image":"실제 컨테이너 이미지가 승인된 이미지와 다릅니다.",
  };
  const failed = (data.checks || []).filter(check => !check.passed);
  const status = el.querySelector(".preflight-status");
  status.className = "preflight-status " + (el.preflightId ? "status-ok" : "status-err");
  status.textContent = el.preflightId
    ? "검사 통과 — 실제 조치는 아직 실행되지 않았습니다. " + (Number(data.expires_in_seconds) || 120) + "초 이내에 ‘검사 결과 확인 후 승인’을 누르세요."
    : "검사 차단 — " + (failed.length
      ? failed.map(check => (checks[check.name] || check.name) + " 조건 미충족").join(" / ")
      : (reasons[data.reason] || data.reason || data.status || "응답 상세를 확인하세요."));
  if (failed.some(check => check.name === "redundancy")) status.textContent += " 건강한 별도 이중화 컨테이너가 필요합니다. 기본 단일 구성에서는 재시작이 차단됩니다.";
}

function setDecisionButtonsDisabled(el, disabled) {
  if (!disabled) {
    setRunbookButtonsDisabled(el, false);
    return;
  }
  el.querySelectorAll(".approve, .reject, .preflight").forEach((b) => {
    b.disabled = disabled || (b.classList.contains("approve") && !el.preflightId);
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
  lastExecutionId = data.execution_id || null;
  $("refresh-execution").classList.toggle("hidden", !lastExecutionId);
  $("verify-execution").classList.toggle("hidden", !lastExecutionId || data.status !== "success");
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
    const value = Number(hypothesis.confidence || 0);
    const pct = Number.isFinite(value) ? Math.round(Math.max(0,Math.min(1,value))*100) : 0;
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
    const targetRequired = b.matches(".preflight, .approve, .diagnose");
    b.disabled = disabled || el.actionable === false || !el.action || el.preflightPending || el.executionPending
      || el.classList.contains("decided")
      || (el.classList.contains("locked") && b.matches(".preflight, .approve, .reject"))
      || (targetRequired && el.querySelector(".target-select").value === "")
      || (b.classList.contains("approve") && !el.preflightId);
  });
}

async function decideRunbook(scriptId, action, el, decision) {
  if (!currentErrorCode || !currentRecommendation || !action) {
    el.querySelector(".decision").textContent = "최신 Incident 추천을 다시 불러오세요.";
    return;
  }
  el.executionPending = true;
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
    const { status, data } = await postJSON(endpoint, actionBody(action,el));
    showExecResult(scriptId, data, status);
    if (data.status === "blocked" && data.approved_action_id) {
      // 다른 화면/사용자가 먼저 다른 조치를 승인한 경우
      const approvedEl = document.querySelector(
        `#actions .runbook[data-action-id="${CSS.escape(data.approved_action_id)}"]`
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
      setClientStatus("명령 실행 완료 — 업무 복구 확인 필요");
    }
    await loadIncidents();
  } catch (e) {
    $("exec-status").className = "status-err";
    $("exec-status").textContent = "요청 실패: " + e;
    setRunbookButtonsDisabled(el, false);
    if (decision === "approve") unlockOtherRunbooks();
  } finally {
    el.executionPending = false;
    setRunbookButtonsDisabled(el, false);
  }
}

async function requestDiagnosis(action, el) {
  if (!action) return;
  try {
    const {data} = await postJSON("/api/v1/remediations/diagnose", actionBody(action,el));
    $("exec").classList.remove("hidden");
    $("exec-output").textContent = JSON.stringify(data,null,2);
    $("exec-status").textContent = data.status;
  } catch (error) { el.querySelector(".decision").textContent = "진단 실패: " + error; }
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

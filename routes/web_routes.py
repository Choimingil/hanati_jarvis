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
  @media (max-width: 620px) {
    .feedback-grid { grid-template-columns: 1fr; }
    .feedback-grid .full { grid-column: auto; }
  }
</style>
</head>
<body>
<div class="wrap">
  <h1>Hanati Jarvis — 장애 대응 콘솔</h1>
  <p class="sub">로그·리소스 분석 → Runbook 추천 또는 Resource Guidance → 운영자 확인 → 안전한 조치·학습</p>

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
const $ = (id) => document.getElementById(id);
const sel = $("scenario");
let currentErrorCode = null;
let currentGuidance = null;
let selectedVerdict = null;

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
  if (rec && rec.status === "resource_guidance") {
    renderResourceGuidance(rec);
    return;
  }
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
      ).join("\n")
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

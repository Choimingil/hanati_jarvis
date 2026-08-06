"""운영자용 웹 UI.

`GET /` 에서 단일 페이지를 제공한다. 흐름은 다음과 같다.

1. 장애 시나리오(=log_generator/main.py가 발생시키는 오류)를 하나 골라
   "분석" 클릭 -> 서버가 `log_generator/trigger.py`로 그 시나리오를 실제
   실행해서 fluentbit가 tail하는 `fluentbit/application.log`에 그대로
   기록한다 (main.py를 직접 돌렸을 때와 동일한 코드 경로).
2. fluent-bit가 그 파일을 tail해서 `POST /api/v1/logs`로 백엔드에 전달 ->
   탐지 → 진단 → (LLM) 추천이 비동기로 이뤄진다. 화면은 그 결과가
   Elasticsearch에 쌓일 때까지 짧게 폴링한다.
3. LLM이 준 "오류 원인"과 "추천도 높은 순 조치 스크립트 리스트"를 보여준다
4. 그중 하나를 "실행"하면 `POST /api/v1/remediations/approve` 로 해당
   스크립트를 실제로 호출하고 결과(stdout)를 보여준다
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
  .action {
    border: 1px solid var(--border); border-radius: 10px;
    padding: 14px; margin-top: 12px; display: flex; gap: 14px;
    align-items: center; flex-wrap: wrap;
  }
  .action .meta { flex: 1 1 320px; min-width: 0; }
  .action .name { font-weight: 700; font-family: ui-monospace, monospace; }
  .action .reason { color: var(--muted); font-size: 13px; margin-top: 2px; }
  .rank { font-size: 12px; color: var(--muted); }
  .scorebar {
    height: 8px; background: var(--bar); border-radius: 999px;
    overflow: hidden; margin-top: 8px;
  }
  .scorebar > span { display: block; height: 100%; background: var(--accent); }
  .score-num { font-variant-numeric: tabular-nums; font-weight: 700; }
  pre {
    background: var(--code-bg); color: var(--code-fg); padding: 14px;
    border-radius: 8px; overflow-x: auto; font-size: 13px; margin: 10px 0 0;
    white-space: pre-wrap;
  }
  .logline { opacity: 0; animation: fadein .25s ease forwards; }
  .logline.WARN { color: #f5c451; }
  .logline.ERROR { color: #ff8080; }
  @keyframes fadein { to { opacity: 1; } }
  .status-ok { color: var(--ok); font-weight: 700; }
  .status-err { color: var(--err); font-weight: 700; }
  .status-pending { color: var(--muted); font-weight: 600; }
  .muted { color: var(--muted); font-size: 13px; }
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

  <div id="log" class="card hidden">
    <div><strong>log_generator 실행 로그</strong>
      <span class="muted">(fluentbit/application.log 기록분)</span></div>
    <pre id="log-output"></pre>
    <div id="wait-status" class="muted" style="margin-top:8px"></div>
  </div>

  <div id="result" class="card hidden">
    <span id="errcode" class="pill"></span>
    <div><strong>현재 오류 원인</strong></div>
    <div id="cause" class="cause"></div>
    <div style="margin-top:18px"><strong>추천 조치 스크립트</strong>
      <span class="muted">(추천도 높은 순)</span></div>
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

$("analyze").addEventListener("click", async () => {
  $("analyze").disabled = true;
  $("analyze").textContent = "시나리오 실행 중…";
  $("log").classList.remove("hidden");
  $("result").classList.add("hidden");
  $("exec").classList.add("hidden");
  $("log-output").innerHTML = "";
  $("wait-status").textContent = "";

  try {
    const { data } = await postJSON("/api/v1/log-generator/run", {
      scenario: sel.value,
    });

    if (data.status !== "triggered") {
      $("wait-status").textContent = "실행 실패: " + JSON.stringify(data);
      return;
    }

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

async function waitForRecommendation(errorCode, since) {
  $("wait-status").textContent =
    "fluent-bit가 로그를 전달하는 중… 추천 결과를 기다리는 중";

  for (let i = 0; i < 20; i++) {
    await sleep(1500);
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

  const actions = rec.ranked_actions || [];
  const box = $("actions");
  box.innerHTML = "";

  actions.forEach((a, idx) => {
    const pct = Math.round(Math.max(0, Math.min(1, a.score)) * 100);
    const el = document.createElement("div");
    el.className = "action";
    el.innerHTML = `
      <div class="meta">
        <div class="rank">#${idx + 1} · 추천도 <span class="score-num">${a.score}</span></div>
        <div class="name">${a.script_id}</div>
        <div class="reason">${a.reason || ""}</div>
        <div class="scorebar"><span style="width:${pct}%"></span></div>
      </div>`;
    const btn = document.createElement("button");
    btn.className = idx === 0 ? "" : "secondary";
    btn.textContent = "실행";
    btn.addEventListener("click", () => runScript(a.script_id, btn));
    el.appendChild(btn);
    box.appendChild(el);
  });
}

async function runScript(scriptId, btn) {
  if (!currentErrorCode) return;
  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = "실행 중…";

  const exec = $("exec");
  exec.classList.remove("hidden");
  $("exec-title").textContent = scriptId;
  $("exec-status").textContent = "";
  $("exec-output").textContent = "";

  try {
    const { status, data } = await postJSON("/api/v1/remediations/approve", {
      script_id: scriptId, error_code: currentErrorCode, approved_by: "web-ui",
    });
    const ok = data.status === "success";
    const s = $("exec-status");
    s.className = ok ? "status-ok" : "status-err";
    s.textContent = `${data.status}` + (data.returncode !== undefined
      ? ` (exit ${data.returncode})` : ` (HTTP ${status})`);
    $("exec-output").textContent =
      (data.stdout || "") + (data.stderr ? "\\n[stderr]\\n" + data.stderr :
        (data.reason ? "\\n" + data.reason : ""));
  } catch (e) {
    $("exec-status").className = "status-err";
    $("exec-status").textContent = "실행 실패: " + e;
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}
</script>
</body>
</html>
"""


@web_blueprint.get("/")
def index() -> Response:
    return Response(_PAGE, mimetype="text/html")

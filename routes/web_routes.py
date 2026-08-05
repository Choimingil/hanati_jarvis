"""운영자용 웹 UI.

`GET /` 에서 단일 페이지를 제공한다. 흐름은 다음과 같다.

1. 장애 시나리오(=log_generator가 만드는 오류)를 하나 골라 "분석" 클릭
2. `POST /api/v1/logs` 로 로그를 보내 탐지 → 진단 → (LLM) 추천을 받는다
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
  select, textarea, button {
    font: inherit; color: inherit;
  }
  select, textarea {
    width: 100%; padding: 10px 12px; border-radius: 8px;
    border: 1px solid var(--border); background: var(--bg); color: var(--fg);
  }
  textarea { resize: vertical; min-height: 46px; margin-top: 10px; }
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
  }
  .status-ok { color: var(--ok); font-weight: 700; }
  .status-err { color: var(--err); font-weight: 700; }
  .muted { color: var(--muted); font-size: 13px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Hanati Jarvis — 장애 대응 콘솔</h1>
  <p class="sub">로그 → 오류 탐지 → 진단 → LLM 추천 → 조치 스크립트 실행</p>

  <div class="card">
    <div class="row">
      <div>
        <label for="scenario">장애 시나리오 (log_generator가 발생시키는 오류)</label>
        <select id="scenario"></select>
      </div>
      <button id="analyze">분석</button>
    </div>
    <textarea id="custom" placeholder="직접 로그 메시지를 입력하려면 여기에 (선택)"></textarea>
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
const SCENARIOS = [
  { label: "디스크 부족 (DISK_FULL)", message: "No space left on device." },
  { label: "DNS 해석 실패 (DNS_RESOLUTION_FAILURE)", message: "Failed to resolve service endpoint." },
  { label: "DB 커넥션 실패 (DB_CONNECTION_FAILURE)", message: "Database connection failed." },
  { label: "외부 API 장애 (EXTERNAL_API_FAILURE)", message: "Received HTTP 503 from external API." },
  { label: "메모리 릭 (MEMORY_LEAK)", message: "OutOfMemoryError encountered." },
  { label: "Redis 연결 끊김 (REDIS_CONNECTION_FAILURE)", message: "Redis connection lost." },
];

const sel = document.getElementById("scenario");
SCENARIOS.forEach((s, i) => {
  const o = document.createElement("option");
  o.value = i; o.textContent = s.label; sel.appendChild(o);
});

const $ = (id) => document.getElementById(id);
let currentErrorCode = null;

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return { ok: res.ok, status: res.status, data: await res.json() };
}

$("analyze").addEventListener("click", async () => {
  const custom = $("custom").value.trim();
  const message = custom || SCENARIOS[sel.value].message;

  $("analyze").disabled = true;
  $("analyze").textContent = "분석 중…";
  $("exec").classList.add("hidden");

  try {
    const { data } = await postJSON("/api/v1/logs", {
      level: "ERROR", message, service: "order-api", host: "web01",
    });
    const r = Array.isArray(data) ? data[0] : data;
    renderResult(r);
  } catch (e) {
    alert("분석 실패: " + e);
  } finally {
    $("analyze").disabled = false;
    $("analyze").textContent = "분석";
  }
});

function renderResult(r) {
  const result = $("result");
  result.classList.remove("hidden");

  if (!r || r.status !== "recommended") {
    currentErrorCode = null;
    $("errcode").textContent = r ? r.status : "no-response";
    $("cause").textContent = r && r.message
      ? `'${r.message}' — 등록된 대응 규칙이 없습니다.`
      : "추천을 생성할 수 없습니다.";
    $("actions").innerHTML = "";
    return;
  }

  currentErrorCode = r.error_code;
  const rec = r.recommendation || {};
  $("errcode").textContent = r.error_code;
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

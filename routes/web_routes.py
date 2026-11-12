"""운영자용 웹 UI.

같은 페이지를 두 모드로 제공한다.

- `GET <ADMIN_PAGE_PATH>` (어드민, 기본값 `/ops-console-ee6bdb251722`):
  아래 흐름 전체 + 장애 시나리오/수집·분석 로그/수집·분석 상태.
  추측하기 쉬운 `/admin` 경로는 제공하지 않는다.
- `GET /`, `GET /client` (클라이언트): 오류 내용(원인·Runbook/리소스 가이드)만 표시.
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
4. 각 Runbook에서 "결재 요청"하면 `POST /api/v1/approvals`로 결재 대기열에 올리고,
   관리자가 어드민 화면 "결재 대기"에서 승인하면 기존 승인 실행 경로로 해당
   스크립트를 실제로 호출하고 결과(stdout)를 보여준다. "거부"는 스크립트를
   실행하지 않고 감사 기록만 남긴다. 시나리오 스크립트의 정상 종료와 파일
   검증이 확인되면 자동으로 시뮬레이션 처리를 완료한다.
"""

from flask import Blueprint, Response

from config import ADMIN_PAGE_PATH


web_blueprint = Blueprint("web", __name__)


_PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jarvis__TITLE_SUFFIX__</title>
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
  .hidden { display: none !important; }
  .incident-processing { border-left: 4px solid var(--accent); padding: 12px 16px; margin: 12px 0; background: var(--bar); border-radius: 8px; }
  .incident-processing.completed { border-color: var(--ok); }
  .incident-processing strong { display: block; }
  .completed-incident-detail { display: block; width: 100%; text-align: left; margin-top: 8px; white-space: normal; }
  .completed-incident-detail span { display: block; font-weight: 400; }
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
  .console-head { display:flex; align-items:center; gap:14px; flex-wrap:wrap; margin-bottom:20px; }
  .console-head h1 { margin:0; }
  .head-right { margin-left:auto; display:flex; align-items:center; gap:10px; }
  .head-right #log-toggle { padding:8px 14px; }
  .console-actions { display:flex; gap:8px; flex-wrap:wrap; }
  .incident-stats { display:flex; gap:8px; flex-wrap:wrap; }
  .incident-stat { background:var(--card); color:var(--fg); border:1px solid var(--border); border-radius:999px; padding:6px 14px; display:inline-flex; align-items:baseline; gap:6px; font-weight:600; }
  .incident-stat:hover { border-color:var(--accent); }
  .incident-stat.selected { border-color:var(--accent); background:var(--bar); }
  .incident-stat:focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
  .incident-stat span { color:var(--muted); font-size:13px; }
  .incident-stat.selected span { color:var(--accent); }
  .incident-stat strong { font-size:14px; }
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
  .card.completed-incident { border:2px solid var(--ok); }
  .incident-fields { display:grid; grid-template-columns:100px 1fr; gap:8px 14px; margin:14px 0; font-size:14px; }
  .incident-fields dt { color:var(--muted); }
  .incident-fields dd { margin:0; overflow-wrap:anywhere; }
  .component-status { display:flex; gap:8px 18px; flex-wrap:wrap; margin-top:8px; font-size:13px; }
  .log-tabs { display:flex; gap:8px; flex-wrap:wrap; }
  button.log-tab { background:transparent; color:var(--accent); border:1px solid var(--accent); padding:8px 12px; }
  button.log-tab.selected { background:var(--accent); color:var(--accent-fg); }
  .scenario-card { margin-top:0; }
  .scenario-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:8px; flex-wrap:wrap; }
  .scenario-heading label { margin:0; }
  .badge { display:inline-block; font-size:11px; font-weight:700; border-radius:999px; padding:2px 8px; margin-left:6px; vertical-align:middle; }
  .badge.approval { background:#fff1d6; color:#9a5b00; }
  .badge.hold { background:#e8e3fb; color:#5a3fc0; }
  .badge.rule { background:#fde4e7; color:var(--err); }
  .incident-processing.on-hold { border-color:#7b61d9; }
  .card.held-incident { border:2px solid #7b61d9; }
  .workflow-table { width:100%; border-collapse:collapse; font-size:13px; margin-top:10px; }
  .workflow-table th, .workflow-table td { padding:8px; border-bottom:1px solid var(--border); text-align:left; vertical-align:top; }
  .workflow-table th { color:var(--muted); white-space:nowrap; }
  .workflow-table button { padding:6px 12px; font-size:13px; }
  .workflow-actions { display:flex; gap:6px; flex-wrap:wrap; }
  button.danger { background:transparent; color:var(--err); border:1px solid var(--err); }
  .history-summary { border-left:3px solid var(--ok); padding:6px 0 6px 12px; margin:8px 0; font-size:14px; }
  .hold-controls { display:flex; gap:8px; flex-wrap:wrap; align-items:flex-end; margin:12px 0; }
  .hold-controls input { flex:1 1 260px; width:auto; }
  .notification { padding:8px 10px; border-bottom:1px solid var(--border); font-size:13px; }
  .notification.unread { background:var(--bar); }
  .notification strong { display:block; }
  .bell-wrap { position:relative; }
  button.bell { position:relative; background:transparent; color:var(--fg); border:1px solid var(--border); border-radius:999px; width:38px; height:38px; padding:0; display:inline-flex; align-items:center; justify-content:center; }
  button.bell:hover, button.bell[aria-expanded="true"] { background:var(--bar); border-color:var(--accent); color:var(--accent); }
  button.bell svg { width:19px; height:19px; flex:0 0 19px; }
  .bell-count { position:absolute; top:-5px; right:-6px; min-width:18px; height:18px; padding:0 5px; border-radius:999px; background:var(--err); color:#fff; font-size:11px; font-weight:700; line-height:18px; text-align:center; }
  #notification-panel { position:absolute; top:calc(100% + 8px); right:0; z-index:20; width:min(380px, calc(100vw - 32px)); margin:0; padding:14px; box-shadow:0 10px 28px rgba(0,0,0,.18); }
  #notification-list { max-height:360px; overflow-y:auto; margin-top:8px; }
  #incident-detail-panel:focus { outline:none; }
  #incident-detail-load-status:not(:empty) { margin:0 0 12px; }
  .banner-tools { display:flex; gap:8px; align-items:center; }
  .banner-tools > button.secondary { padding:6px 12px; font-size:13px; }
  #result .hold-controls { margin:0 0 12px; }
  #result.incident-open { border:2px solid var(--err); }
  #result.incident-open #errcode { background:rgba(209,54,74,.12); color:var(--err); }
  #result.incident-resolved { border:2px solid var(--ok); }
  #result.incident-resolved #errcode { background:rgba(23,145,90,.14); color:var(--ok); }
  .state-badge { display:inline-block; font-size:12px; font-weight:700; border-radius:999px; padding:3px 10px; margin-left:6px; vertical-align:top; }
  #result.incident-open .state-badge { background:var(--err); color:#fff; }
  #result.incident-resolved .state-badge { background:var(--ok); color:#fff; }
  .scenario-card { border:1px solid var(--border); border-radius:10px; padding:16px; margin-top:12px; }
  .scenario-summary { display:grid; grid-template-columns:88px 1fr; gap:6px 12px; margin:0 0 14px; font-size:14px; }
  .scenario-summary dt { color:var(--muted); font-size:13px; }
  .scenario-summary dd { margin:0; }
  .scenario-cols { display:grid; grid-template-columns:minmax(170px,1.3fr) 92px minmax(120px,1.3fr) minmax(100px,1fr) 124px minmax(100px,1fr); gap:10px; align-items:start; }
  .scenario-head { font-size:12px; color:var(--muted); font-weight:600; padding:8px 10px; border-bottom:1px solid var(--border); margin-top:8px; }
  .runbook.scenario-row { border:0; border-bottom:1px solid var(--border); border-radius:0; padding:0; margin:0; }
  .runbook.scenario-row.selected { background:var(--bar); }
  .scenario-row .scenario-cols { padding:10px; font-size:14px; }
  .scenario-pick { display:flex; gap:8px; align-items:flex-start; margin:0; color:var(--fg); font-size:14px; cursor:pointer; }
  .scenario-pick input { width:auto; margin-top:3px; }
  .scenario-pick .scenario-kind { display:block; font-size:11px; font-weight:700; color:var(--accent); }
  .scenario-pick .decision { font-size:12px; margin-top:4px; }
  .scenario-row .confidence-bar { height:6px; background:var(--card); border-radius:999px; overflow:hidden; margin-top:4px; }
  .scenario-row .confidence-bar > span { display:block; height:100%; background:var(--accent); }
  .scenario-row .rollback { color:var(--err); }
  .scenario-actions { padding:0 10px 14px 34px; }
  .scenario-manual { display:none; align-items:center; justify-content:space-between; gap:12px; padding:12px 10px; flex-wrap:wrap; }
  .wrap.manual-switchable .scenario-manual { display:flex; }
  .runbook.scenario-row:not(.selected) .scenario-actions { display:none; }
  .scenario-actions .target-row label { margin:0 0 4px; }
  .scenario-actions .buttons { margin-top:10px; }
  @media (max-width:760px) {
    .scenario-head { display:none; }
    .scenario-cols { grid-template-columns:1fr 1fr; }
    .scenario-cols > :first-child { grid-column:1 / -1; }
    .scenario-row .cell::before { content:attr(data-label); display:block; font-size:11px; color:var(--muted); }
    .scenario-actions { padding-left:10px; }
  }
  button.icon-btn { position:relative; background:transparent; color:var(--muted); border:1px solid var(--border); border-radius:8px; width:36px; height:34px; padding:0; display:inline-flex; align-items:center; justify-content:center; }
  button.icon-btn:hover, button.icon-btn[aria-expanded="true"] { color:var(--accent); border-color:var(--accent); background:var(--bar); }
  button.icon-btn svg { width:18px; height:18px; flex:0 0 18px; }
  .icon-count { position:absolute; top:-6px; right:-7px; min-width:17px; height:17px; padding:0 4px; border-radius:999px; background:var(--accent); color:#fff; font-size:10px; font-weight:700; line-height:17px; text-align:center; }
  .history-panel { border:1px solid var(--border); border-radius:10px; padding:12px 14px; margin:4px 0 14px; background:var(--bg); }
  .history-panel .workflow-table { margin-top:6px; }
  .exec-section { border-top:1px solid var(--border); margin-top:16px; padding-top:14px; }
  .exec-section .exec-actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }
  .exec-section .exec-actions button { padding:7px 12px; font-size:13px; }
  .hold-form { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-top:10px; }
  .hold-form input { flex:1 1 240px; width:auto; padding:8px 10px; }
  .hold-form button { padding:8px 12px; font-size:13px; }

  pre.log-scroll { max-height: calc(13px * 1.5 * 5 + 28px); overflow-y: auto; line-height: 1.5; }
  .banner-head { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; }
  .banner-head button { padding:6px 12px; font-size:13px; }
  .manual-switch, #manual-back { display:none; }
  .wrap.manual-switchable .manual-switch, .wrap.manual-switchable #manual-back { display:inline-block; }
  .wrap.manual-switchable:not(.manual-switched) #manual-remediation { display:none; }
  .wrap.manual-switched #result, .wrap.manual-switched #guidance-result { display:none; }
  body.mode-client .admin-only { display:none !important; }
  body.mode-admin .client-only { display:none !important; }
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
        <div class="scenario-heading"><label for="scenario">장애 시나리오</label>__CREATE_ERROR_BUTTON__</div>
        <select id="scenario"></select>
      </div>
      <button id="analyze" disabled>분석</button>
    </div>
  </div>
  <div class="console-head">
    <h1>Jarvis__TITLE_SUFFIX__</h1>
    <div class="incident-stats" role="tablist" aria-label="장애 상태">
      <button id="incident-tab-open" type="button" class="incident-stat selected" role="tab" aria-selected="true" aria-controls="incident-list-panel" data-filter="open"><span>진행중</span><strong id="stat-open">0건</strong></button>
      <button id="incident-tab-approval" type="button" class="incident-stat" role="tab" aria-selected="false" aria-controls="incident-list-panel" tabindex="-1" data-filter="approval"><span>결재 대기</span><strong id="stat-approval">0건</strong></button>
      <button id="incident-tab-hold" type="button" class="incident-stat" role="tab" aria-selected="false" aria-controls="incident-list-panel" tabindex="-1" data-filter="hold"><span>보류</span><strong id="stat-hold">0건</strong></button>
    </div>
    <div class="head-right">
      <button id="log-toggle" class="admin-only" type="button">로그 조회</button>
      <div class="bell-wrap">
        <button id="notification-bell" class="bell" type="button" aria-label="알림" aria-haspopup="true" aria-expanded="false" aria-controls="notification-panel"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg><span id="notification-count" class="bell-count hidden"></span></button>
        <div id="notification-panel" class="card hidden" role="dialog" aria-label="알림">
          <div class="card-head"><div><strong>알림</strong><span class="muted"> 예외 처리·결재·보류</span></div><button id="notification-read" class="secondary" type="button" style="padding:6px 10px;font-size:13px">모두 읽음</button></div>
          <div id="notification-list" class="muted">알림을 불러오는 중…</div>
        </div>
      </div>
    </div>
  </div>
  <div id="approval-panel" class="card admin-only">
    <div class="card-head"><div><strong>결재 대기</strong><span id="approval-count" class="badge approval">0건</span><span class="muted"> 운영자 결재 요청 → 관리자 승인 시 조치 실행</span></div>
      <div style="display:flex;gap:6px;align-items:center"><label for="approver" style="margin:0">결재자</label><input id="approver" value="admin" maxlength="200" style="width:120px;padding:6px 8px"></div></div>
    <div id="approval-status" class="muted" role="status"></div>
    <div id="approval-list"></div>
    <details id="approval-history-box"><summary>최근 결재 처리 이력</summary><div id="approval-history"></div></details>
  </div>
  <div id="rule-panel" class="card admin-only">
    <div class="card-head"><div><strong>에러별 예외 처리 규칙</strong><span class="muted"> 즉시 해결이 어려운 오류는 자동 보류하고 발생 시 알림만 보냅니다</span></div></div>
    <div id="rule-list"></div>
    <form id="rule-form" class="feedback-grid" style="margin-top:12px">
      <div><label for="rule-code">오류 코드</label><input id="rule-code" required maxlength="120" placeholder="예: LEGACY_INTERFACE_TIMEOUT"></div>
      <div><label for="rule-interval">알림 간격(초, 0=매 발생)</label><input id="rule-interval" type="number" min="0" max="86400" value="300"></div>
      <div><label for="rule-service">단위시스템 (비우면 전체)</label><input id="rule-service" maxlength="200"></div>
      <div><label for="rule-environment">환경 (비우면 전체)</label><input id="rule-environment" maxlength="200"></div>
      <div class="full"><label for="rule-reason">예외 처리 사유</label><input id="rule-reason" required maxlength="1000" placeholder="예: 대외기관 개선 전까지 즉시 조치 불가"></div>
      <div class="full"><button id="rule-submit" type="submit">예외 처리 규칙 등록</button> <span id="rule-status" class="muted" role="status"></span></div>
    </form>
  </div>
  <div id="operations-panel" class="card admin-only"><strong>수집·분석 상태</strong><div id="operations-status" role="status">상태 확인 중…</div><div id="operations-components" class="component-status"></div></div>
  <div id="incident-list-panel" class="card" role="tabpanel" aria-labelledby="incident-tab-open" tabindex="0">
    <div class="card-head"><strong id="incident-list-title">진행중 장애</strong><span class="muted">최근 10분</span></div>
    <div id="incident-list-status" class="muted" role="status">장애 목록을 불러오는 중…</div>
    <div id="incident-sync-status" class="hidden" role="status"></div>
    <div id="incident-list" class="incident-table-wrap"></div>
    <details id="completed-incidents" class="hidden"><summary id="completed-incidents-title">처리 완료 이력</summary><div id="completed-incidents-list"></div></details>
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
      <pre id="log-output" class="log-scroll"></pre>
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
      <pre id="fluentbit-output" class="log-scroll"></pre>
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
      <pre id="qdrant-output" class="src-qdrant log-scroll"></pre>
      <div class="sub-label">Elasticsearch (진단·추천)</div>
      <pre id="es-output" class="src-elasticsearch log-scroll"></pre>
    </div>
  </div>

  <div id="redis-panel" class="card hidden logs-section admin-only">
    <div class="card-head"><strong>Redis 큐 로그</strong><button class="panel-toggle" type="button" aria-label="접기/펼치기"><span class="chev">▾</span></button></div>
    <div class="panel-body"><p class="muted">현재 큐 상태와 조회 구간의 접수·재시도·실패 보관 기록</p><pre id="redis-output" class="log-scroll"></pre></div>
  </div>
  <div id="worker-panel" class="card hidden logs-section admin-only">
    <div class="card-head"><strong>Worker 처리 로그</strong><button class="panel-toggle" type="button" aria-label="접기/펼치기"><span class="chev">▾</span></button></div>
    <div class="panel-body"><p class="muted">현재 생존 신호와 조회 구간의 작업별 분석 시작·완료·오류 기록</p><pre id="worker-output" class="log-scroll"></pre></div>
  </div>

  <div id="incident-detail-panel" class="hidden" tabindex="-1"><div id="incident-detail-load-status" class="muted" role="status"></div></div>

  <div id="result" class="card hidden">
    <div class="banner-head"><div><span id="errcode" class="pill"></span><span id="result-state" class="state-badge"></span></div>
      <div class="banner-tools"><button id="history-toggle" class="icon-btn" type="button" aria-expanded="false" aria-controls="history-panel" aria-label="과거 유사 장애 조치 이력" title="과거 유사 장애 조치 이력"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/></svg><span id="history-count" class="icon-count hidden"></span></button><button id="incident-detail-close" class="secondary" type="button">닫기</button></div></div>
    <div id="incident-processing" class="incident-processing hidden" role="status"><strong id="incident-processing-title"></strong><div id="incident-processing-message"></div><div id="incident-processing-meta" class="muted"></div></div>
    <div id="hold-controls" class="hold-controls hidden">
      <button id="release-button" type="button" class="secondary hidden">보류 해제</button>
      <button id="rule-from-incident" type="button" class="danger admin-only">이 오류 예외 처리 등록</button>
      <span id="hold-status" class="muted" role="status"></span>
    </div>
    <div id="history-panel" class="history-panel hidden">
      <div><strong>과거 유사 장애 조치 이력</strong> <span class="muted">(같은 오류 코드 · 기간 제한 없음)</span></div>
      <div id="incident-history-summary" class="history-summary hidden"></div>
      <div id="incident-history"></div>
    </div>
    <div><strong>현재 오류 원인</strong></div>
    <div id="cause" class="cause"></div>
    <div class="guidance-section"><strong>해당 장애의 최근 10분 로그</strong> <span class="muted">(최대 20건)</span></div>
    <div id="incident-detail-logs-status" class="muted"></div>
    <pre id="incident-detail-logs" class="log-scroll"></pre>
    <div style="margin-top:18px"><strong>조치 제안 Runbook</strong></div>
    <div class="scenario-card">
      <div id="scenario-tag" class="runbook-tag">조치 제안</div>
      <dl class="scenario-summary"><dt>장애</dt><dd id="scenario-incident"></dd><dt>추정 원인</dt><dd id="scenario-cause"></dd></dl>
      <div><strong>조치 시나리오 리스트</strong> <span class="muted">(같은 오류에 대한 조치 방법 · 신뢰도 높은 순 · 하나를 선택해 결재 요청)</span></div>
      <div class="scenario-cols scenario-head" aria-hidden="true"><span>시나리오</span><span>신뢰도</span><span>조치</span><span>예상 영향</span><span>과거 실행</span><span>실패 시</span></div>
      <div id="actions" role="radiogroup" aria-label="조치 시나리오 리스트"></div>
      <div class="scenario-manual manual-only-row">
        <div><strong>수동 조치</strong><div class="muted">위 시나리오 대신 서버에서 직접 조치한 뒤 조치 방법과 호출한 셸(서버·경로·실행 계정)을 등록합니다.</div></div>
        <button class="manual-switch secondary" type="button">수동 조치 선택</button>
      </div>
    </div>
    <div id="exec" class="exec-section hidden">
      <div><strong>실행 결과</strong> — <span id="exec-title" class="muted"></span></div>
      <div id="exec-status"></div>
      <pre id="exec-output" class="log-scroll"></pre>
      <div class="exec-actions">
        <button id="refresh-execution" class="secondary hidden" type="button">실행 결과 다시 확인</button>
        <button id="verify-execution" class="secondary hidden" type="button">업무 복구 확인</button>
      </div>
    </div>
    <div id="result-autoclose" class="muted hidden" role="status" style="margin-top:10px"></div>
  </div>

  <div id="manual-remediation" class="card hidden">
    <div class="banner-head"><strong>수동 조치 등록</strong><button id="manual-back" type="button" class="secondary">← 뒤로 가기</button></div>
    <p id="manual-flow" class="muted">수동 조치 → 조치 방법과 호출한 셸(서버·경로·실행 계정) 등록 → 복구 확인</p>
    <p id="manual-target" class="muted"></p>
    <form id="manual-form" class="feedback-grid hidden">
      <div class="full"><label for="manual-method">수행한 조치 방법</label><textarea id="manual-method" required maxlength="8000" placeholder="어떤 단위시스템에서 무엇을 확인하고 어떻게 조치했는지 입력하세요."></textarea></div>
      <div><label for="manual-host">셸을 호출한 서버 (에러 발생 서버)</label><select id="manual-host" required></select></div>
      <div><label for="manual-account">실행 계정</label><input id="manual-account" required maxlength="64" placeholder="예: appuser" autocomplete="off"></div>
      <div class="full"><label for="manual-shell-path">호출한 셸 경로 (절대 경로)</label><input id="manual-shell-path" required maxlength="1024" placeholder="예: /app/scripts/restart_orders.sh" autocomplete="off" spellcheck="false"><p class="muted">기록용 정보입니다. 이 화면에서 셸을 실행하지 않습니다.</p></div>
      <div><label for="manual-operator">조치 운영자</label><input id="manual-operator" required maxlength="200" value="web-ui"></div>
      <div class="check-row"><input id="manual-recovered" type="checkbox" required><label for="manual-recovered" style="margin:0">운영자가 서비스 복구를 확인했습니다.</label></div>
      <div class="full"><p class="muted">서비스 복구 확인을 체크해야 등록할 수 있습니다. 등록하면 해당 오류가 처리 완료되고 이 등록 영역은 닫힙니다.</p><button id="manual-register" type="submit" disabled>조치 방법 등록</button><span id="manual-register-status" class="muted" role="status"></span></div>
    </form>
    <div id="manual-history"></div>
  </div>

  <div id="guidance-result" class="card hidden">
    <div class="banner-head"><span id="guidance-code" class="pill">RESOURCE GUIDANCE</span><button type="button" class="secondary manual-switch">수동 조치</button></div>
    <div><strong>리소스 기반 문제 제안</strong></div>
    <div id="guidance-summary" class="guidance-summary"></div>

    <div class="guidance-section"><strong>발생 로그</strong></div>
    <pre id="guidance-log" class="log-scroll"></pre>

    <div class="guidance-section"><strong>발견된 문제 가능성</strong>
      <span class="muted">(신뢰도 높은 순)</span></div>
    <div id="hypotheses"></div>

    <div class="guidance-section"><strong>같은 호스트의 최근 ERROR 로그</strong></div>
    <pre id="guidance-related-logs" class="log-scroll"></pre>

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
let currentDetailedIncident = null;
let currentProcessing = null;
let verificationPending = false;
let incidentDetailRequest = 0;
let incidentDetailInFlight = null;
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
  open: {label: "진행중", matches: (item) => item.status !== "RESOLVED" && item.status !== "ON_HOLD"},
  approval: {label: "결재 대기", matches: (item) => item.pending_approval === true},
  hold: {label: "보류", matches: (item) => item.status === "ON_HOLD"},
};
let currentApprovals = [];
let currentHistory = null;
let holdPending = false;
let lastExecutionId = null;
let currentManualIncident = null;
let manualRegistrationId = null;
let manualRegisterPending = false;
function actionBody(action, el) {
  const selected = el.querySelector(".target-select").value;
  return {
    incident_id: currentRecommendation.incident_id,
    recommendation_id: currentRecommendation.recommendation_id,
    action_id: action.action_id,
    incident_version: currentRecommendation.incident_version,
    approved_by: "web-ui",
    requested_by: IS_CLIENT ? "operator" : "web-ui",
    target: selected === "" ? null : el.targets[Number(selected)],
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
    const status = {healthy: "수집·분석 정상", ready: "수집·분석 정상", degraded: "수집·분석 확인 필요"}[data.status] || "상태 확인 필요";
    $("operations-status").textContent = `${status} · 대기 ${data.queue?.stream_length || 0}건 · 실패 보관 ${data.queue?.dead_letters || 0}건`;
    const names = {redis: "Redis", elasticsearch: "Elasticsearch", qdrant: "Qdrant", analysis_workers: "분석 Worker"};
    $("operations-components").innerHTML = Object.entries(data.components || {}).map(([key, value]) =>
      '<span class="' + (value.healthy ? 'status-ok' : 'status-err') + '">' + esc(names[key] || key) + ': ' + (value.healthy ? '연결 정상' : '확인 필요') + '</span>'
    ).join("");
  } catch (error) { $("operations-status").textContent = "상태 조회 실패 — 현재 표시된 데이터가 최신인지 확인하세요."; return false; }
}
if (!IS_CLIENT) schedulePoll(loadOperationsStatus,15000);
$("refresh-execution").addEventListener("click", async () => {
  if (!lastExecutionId) return;
  const executionId = lastExecutionId;
  const data = await getJSON("/api/v1/remediations/executions/" + encodeURIComponent(executionId));
  if (lastExecutionId === executionId) showExecResult("실행 결과", {...data.result,execution_id:executionId},200,currentProcessing);
});
$("verify-execution").addEventListener("click", async () => {
  if (!lastExecutionId || verificationPending) return;
  const executionId = lastExecutionId;
  verificationPending = true;
  $("verify-execution").disabled = true;
  try {
    const {data} = await postJSON("/api/v1/remediations/verify", {execution_id:executionId});
    if (lastExecutionId === executionId) {
      $("exec-output").textContent = JSON.stringify(data,null,2);
      $("exec-status").textContent = data.execution_mode === "simulation" ? (data.recovered ? "스크립트 결과 확인 완료" : "스크립트 결과 미확인") : (data.recovered ? "업무 복구 확인 완료" : "업무 복구 미확인");
      if (data.incident?.incident_id === selectedIncidentId) renderIncidentDetails(data.incident, data.processing);
    }
    await loadIncidents();
  } catch (error) {
    if (lastExecutionId === executionId) $("exec-status").textContent = "복구 확인 요청 실패 — 연결 상태를 확인하고 다시 시도하세요.";
  } finally {
    verificationPending = false;
    $("verify-execution").disabled = false;
  }
});

document.querySelectorAll(".panel-toggle").forEach((btn) => {
  btn.addEventListener("click", () => {
    const collapsed = btn.closest(".card").classList.toggle("collapsed");
    if (btn.hasAttribute("aria-expanded")) btn.setAttribute("aria-expanded", String(!collapsed));
    const label = btn.querySelector(".toggle-label");
    if (label) label.textContent = collapsed ? "펼치기" : "접기";
  });
});

// 에러 배너(Runbook/리소스 가이드) ↔ 수동 조치 화면 전환.
// 배너와 수동 조치 영역이 함께 표시 가능할 때만 전환 버튼을 노출하고,
// 수동 조치 화면에서는 "뒤로 가기"로 이전 조치 제안 화면으로 돌아간다.
let manualViewActive = false;
const pageWrap = document.querySelector(".wrap");
function syncManualView() {
  const banner = !$("result").classList.contains("hidden") || !$("guidance-result").classList.contains("hidden");
  const manual = !$("manual-remediation").classList.contains("hidden");
  const switchable = banner && manual;
  if (!switchable) manualViewActive = false;
  pageWrap.classList.toggle("manual-switchable", switchable);
  pageWrap.classList.toggle("manual-switched", switchable && manualViewActive);
}
function setManualView(active) {
  manualViewActive = active;
  syncManualView();
  const target = active ? $("manual-remediation")
    : (!$("result").classList.contains("hidden") ? $("result") : $("guidance-result"));
  target.scrollIntoView({behavior: "smooth", block: "start"});
}
const manualViewObserver = new MutationObserver(syncManualView);
["result", "guidance-result", "manual-remediation"].forEach(id =>
  manualViewObserver.observe($(id), {attributes: true, attributeFilter: ["class"]}));
document.addEventListener("click", event => {
  if (event.target.closest(".manual-switch")) setManualView(true);
});
$("manual-back").addEventListener("click", () => setManualView(false));

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
function environmentLabel(value) {
  return value === "simulation" ? "시나리오" : (value || "unknown");
}
function renderIncidentProcessing(incident, processing = null) {
  const completed = incident.status === "RESOLVED";
  const actionCompleted = incident.status === "MONITORING";
  const held = incident.status === "ON_HOLD";
  const state = processing || incident.processing || {};
  $("incident-processing").classList.toggle("hidden", !completed && !actionCompleted && !held);
  $("incident-processing").classList.toggle("completed", completed);
  $("incident-processing").classList.toggle("on-hold", held);
  if (held) {
    const hold = incident.hold || {};
    $("incident-processing-title").textContent = state.label || "보류";
    $("incident-processing-message").textContent = state.message || "보류된 장애입니다.";
    $("incident-processing-meta").textContent = ["보류 시각: " + formatDateTime(hold.held_at), "보류자: " + (hold.operator || "-"), "사유: " + (hold.reason || "-")].join(" · ");
    return;
  }
  $("incident-processing-title").textContent = completed ? "처리 완료" : "조치 완료 · 복구 확인 대기";
  $("incident-processing-message").textContent = state.message || (completed ? "처리가 완료된 장애입니다." : "조치가 완료되었습니다. 서비스 복구 확인 후 처리가 완료됩니다.");
  const meta = [];
  if (state.completed_at || incident.recovered_at) meta.push((completed ? "완료 시각: " : "조치 시각: ") + formatDateTime(state.completed_at || incident.recovered_at));
  if (state.operator) meta.push("처리 운영자: " + state.operator);
  if (state.method) meta.push("조치 내용: " + state.method);
  const confirmations = {operator_report:"운영자 확인",business_probe:"서비스 복구 검사",simulation:"등록 스크립트 결과 확인"};
  if (confirmations[state.confirmation]) meta.push("확인 방식: " + confirmations[state.confirmation]);
  $("incident-processing-meta").textContent = meta.join(" · ");
}
function isOlderIncident(incident) {
  return currentDetailedIncident?.incident_id === incident.incident_id
    && Number.isFinite(incident.version) && Number.isFinite(currentDetailedIncident.version)
    && incident.version < currentDetailedIncident.version;
}
function renderIncidentDetails(incident, processing = null) {
  if (isOlderIncident(incident)) return;
  currentDetailedIncident = incident;
  $("incident-detail-panel").classList.toggle("completed-incident", incident.status === "RESOLVED");
  $("incident-detail-panel").classList.toggle("held-incident", incident.status === "ON_HOLD");
  currentProcessing = processing || incident.processing || (incident.status === "RESOLVED" ? {state:"completed"} : null);
  paintResultState(incident.status === "RESOLVED");
  $("incident-detail-panel").dataset.lastSeen = incident.last_seen || "";
  renderIncidentProcessing(incident, processing);
  refreshRecentIncidents();
}
// 과거 유사 장애 조치 이력은 "현재 오류 원인" 배너 우측 상단 아이콘으로 연다.
function setHistoryOpen(open) {
  $("history-panel").classList.toggle("hidden", !open);
  $("history-toggle").setAttribute("aria-expanded", String(open));
}
$("history-toggle").addEventListener("click", () => setHistoryOpen($("history-panel").classList.contains("hidden")));
function closeIncidentDetails() {
  selectedIncidentId = null;
  currentDetailedIncident = null;
  currentProcessing = null;
  lastExecutionId = null;
  incidentDetailRequest += 1;
  incidentDetailInFlight = null;
  $("incident-detail-panel").classList.add("hidden");
  $("result").classList.add("hidden");
  $("guidance-result").classList.add("hidden");
  $("exec").classList.add("hidden");
  $("manual-remediation").classList.add("hidden");
  $("hold-controls").classList.add("hidden");
  currentApprovals = [];
  currentHistory = null;
  currentManualIncident = null;
  currentRecommendation = null;
  currentGuidance = null;
  detailRecommendationKey = null;
}
function newManualRegistrationId() {
  return "MANUAL-" + (globalThis.crypto?.randomUUID?.() || Date.now() + "-" + Math.random().toString(36).slice(2));
}
const SHELL_PATH_PATTERN = new RegExp("^/[A-Za-z0-9_./+@%=,:-]{0,1023}$");
const ACCOUNT_PATTERN = /^[A-Za-z_][A-Za-z0-9_.-]{0,63}$/;
function manualShell() {
  return {host: $("manual-host").value, path: $("manual-shell-path").value.trim(), account: $("manual-account").value.trim()};
}
function manualShellValid() {
  const shell = manualShell();
  return Boolean(shell.host) && SHELL_PATH_PATTERN.test(shell.path) && !shell.path.split("/").includes("..") && ACCOUNT_PATTERN.test(shell.account);
}
function updateManualRegisterButton() {
  $("manual-register").disabled = manualRegisterPending || !currentManualIncident?.manualAllowed
    || !$("manual-recovered").checked || !$("manual-method").value.trim() || !$("manual-operator").value.trim() || !manualShellValid();
  $("manual-form").querySelectorAll("input, textarea, select").forEach(input => input.disabled = manualRegisterPending);
}
const MANUAL_REASONS = {
  "incident changed; reload details before registering": "장애 정보가 갱신되었습니다. 최신 상세를 확인한 뒤 다시 등록하세요.",
  "manual registration unavailable for this incident": "현재 장애 상태에서는 수동 조치를 등록할 수 없습니다.",
  "invalid executed_shell path": "셸 경로는 /로 시작하는 절대 경로로 입력하세요.",
  "invalid executed_shell account": "실행 계정 형식을 확인하세요.",
  "executed_shell host must be an affected host": "에러가 발생한 서버를 선택하세요.",
};
function shellLabel(shell) {
  return shell ? shell.host + ":" + shell.path + " (실행 계정 " + shell.account + ")" : "";
}
function renderManualRemediation(incident, available) {
  const changed = currentManualIncident?.incident_id !== incident.incident_id;
  const learned = (incident.latest_recommendation?.actions || []).some(action => action.learned_script === true);
  currentManualIncident = {...incident, manualAllowed: available && !learned && incident.status !== "RESOLVED"};
  if (changed) {
    manualRegistrationId = newManualRegistrationId();
    $("manual-method").value = "";
    $("manual-shell-path").value = "";
    $("manual-account").value = "";
    $("manual-recovered").checked = false;
    $("manual-register-status").textContent = "";
  }
  const hosts = incident.affected_hosts || incident.hosts || [];
  const selectedHost = $("manual-host").value;
  if ($("manual-host").dataset.hosts !== JSON.stringify(hosts)) {
    $("manual-host").dataset.hosts = JSON.stringify(hosts);
    $("manual-host").replaceChildren(...hosts.map(host => { const o = document.createElement("option"); o.value = o.textContent = host; return o; }));
    if (hosts.includes(selectedHost)) $("manual-host").value = selectedHost;
  }
  const history = incident.manual_actions || [];
  $("manual-remediation").classList.toggle("hidden", learned || incident.status === "RESOLVED" || (!available && !history.length));
  $("manual-form").classList.toggle("hidden", !available);
  $("manual-flow").textContent = available ? "수동 조치 후 조치 방법과, 에러 발생 서버에서 호출한 셸의 경로·실행 계정을 등록하세요. 복구를 확인하면 처리 완료되고 과거 조치 이력에 남습니다." : "이 장애에 등록된 수동 조치 방법과 복구 확인 이력입니다.";
  $("manual-target").textContent = [environmentLabel(incident.environment), incident.service, ...(incident.affected_hosts || [])].join(" / ");
  $("manual-history").innerHTML = history.length
    ? '<strong>등록된 수동 조치 이력</strong>' + history.slice().reverse().map(item =>
      '<details><summary>' + esc(formatDateTime(item.registered_at)) + ' · ' + esc(item.operator)
      + ' · ' + (item.recovered ? '운영자 복구 확인' : '복구 확인 대기') + '</summary><pre>' + esc(item.method) + '</pre>' + (item.executed_shell ? '<div class="muted">호출한 셸: ' + esc(shellLabel(item.executed_shell)) + '</div>' : '') + (item.attachment ? '<a href="/api/v1/remediations/scripts/' + encodeURIComponent(item.attachment.script_id) + '?incident_id=' + encodeURIComponent(incident.incident_id) + '">첨부 스크립트: ' + esc(item.attachment.filename) + '</a>' : '') + '</details>'
    ).join("") : "";
  updateManualRegisterButton();
}
["manual-method", "manual-host", "manual-shell-path", "manual-account", "manual-operator", "manual-recovered"].forEach(id => $(id).addEventListener("input", () => {
  manualRegistrationId = newManualRegistrationId();
  $("manual-register-status").textContent = "";
  updateManualRegisterButton();
}));
$("manual-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (manualRegisterPending || $("manual-register").disabled || !currentManualIncident) return;
  const incident = currentManualIncident;
  manualRegisterPending = true;
  updateManualRegisterButton();
  $("manual-register-status").className = "status-pending";
  $("manual-register-status").textContent = "등록 중…";
  try {
    // 화면에서 수동 조치를 등록하는 것 자체가 "수행 완료" 신고이므로 performed는 항상 true로 보낸다.
    const {ok, data} = await postJSON("/api/v1/remediations/manual", {
      incident_id: incident.incident_id, incident_version: incident.version,
      registration_id: manualRegistrationId, operator: $("manual-operator").value.trim(),
      method: $("manual-method").value.trim(), performed: true,
      recovered: $("manual-recovered").checked, executed_shell: manualShell(),
    });
    if (currentManualIncident?.incident_id === incident.incident_id) {
      $("manual-register-status").className = ok ? "status-ok" : "status-err";
      $("manual-register-status").textContent = ok ? "조치가 등록되었습니다." : ("등록 실패: " + (MANUAL_REASONS[data.reason] || data.reason || data.status));
      if (ok && !isOlderIncident(data.incident)) {
        $("manual-method").value = "";
        $("manual-shell-path").value = "";
        $("manual-account").value = "";
        $("manual-recovered").checked = false;
        manualRegistrationId = newManualRegistrationId();
        renderManualRemediation(data.incident, data.incident.status === "MONITORING");
        renderIncidentDetails(data.incident);
      }
    }
    await loadIncidents();
  } catch (error) {
    if (currentManualIncident?.incident_id === incident.incident_id) {
      $("manual-register-status").className = "status-err";
      $("manual-register-status").textContent = error.message || "등록 응답을 받지 못했습니다. 같은 요청으로 다시 등록하세요.";
    }
  } finally {
    manualRegisterPending = false;
    updateManualRegisterButton();
  }
});
const REANALYZING_STATUSES = new Set(["DETECTED", "ANALYZING", "REOPENED"]);
function refreshSelectedIncident() {
  if (!selectedIncidentId) return Promise.resolve(true);
  return loadIncidentDetails({incident_id: selectedIncidentId}, false, true);
}
function loadIncidentDetails(incident, scroll = false, refresh = false) {
  if (refresh && incidentDetailInFlight?.incidentId === incident.incident_id) return incidentDetailInFlight.promise;
  const request = {incidentId: incident.incident_id, promise: null};
  incidentDetailInFlight = request;
  request.promise = fetchIncidentDetails(incident, scroll, refresh).finally(() => {
    if (incidentDetailInFlight === request) incidentDetailInFlight = null;
  });
  return request.promise;
}
async function fetchIncidentDetails(incident, scroll, refresh) {
  const requestId = ++incidentDetailRequest;
  selectedIncidentId = incident.incident_id;
  $("incident-detail-panel").classList.remove("hidden");
  if (!refresh) {
    setHistoryOpen(false);
    $("result").classList.add("hidden");
    $("guidance-result").classList.add("hidden");
    $("exec").classList.add("hidden");
    currentRecommendation = null;
    currentGuidance = null;
    lastExecutionId = null;
    detailRecommendationKey = null;
    $("manual-remediation").classList.add("hidden");
    renderIncidentDetails(incident);
    $("incident-detail-load-status").textContent = "최신 장애 정보를 확인하는 중…";
    $("incident-detail-logs-status").textContent = "";
    $("incident-detail-logs").textContent = "";
  }
  if (scroll) {
    $("incident-detail-panel").scrollIntoView({behavior: "smooth", block: "start"});
    $("incident-detail-panel").focus({preventScroll: true});
  }
  try {
    const data = await getJSON("/api/v1/log-generator/incidents/" + encodeURIComponent(incident.incident_id));
    if (requestId !== incidentDetailRequest) return;
    const latest = data.incident;
    // A read started before local completion must not undo the newer state.
    if (isOlderIncident(latest)) return true;
    renderIncidentDetails(latest, data.processing);
    currentApprovals = data.approvals || [];
    renderHoldControls(latest, data);
    renderIncidentHistory(data.history, data.history_status);
    // 같은 오류가 다시 발생해 재분석 중이면 이전 발생분의 추천·결재·실행 결과(처리 완료 등)를 보여주지 않는다.
    const reanalyzing = REANALYZING_STATUSES.has(latest.status);
    renderManualRemediation(latest, !reanalyzing && data.manual_action_available === true && latest.status !== "ON_HOLD");
    if (reanalyzing) $("manual-remediation").classList.add("hidden");
    $("incident-detail-load-status").textContent = "";
    $("incident-detail-logs-status").textContent = data.logs_status === "unavailable"
      ? "관련 로그 조회 실패 — 장애 정보는 조회되었습니다."
      : ((data.logs || []).length ? "" : "최근 10분 내 이 장애에 연결된 로그가 없습니다.");
    $("incident-detail-logs").textContent = (data.logs || []).map(log =>
      `[${formatDateTime(log.timestamp || log.received_at)}] ${log.service || latest.service} / ${log.host || "unknown"} / ${log.source || log.raw?.source || "log"}\\n${log.message || ""}`
    ).join("\\n\\n");
    clientRunPrefix = latest.service + " / " + latest.incident_id;
    const rec = reanalyzing ? null : latest.latest_recommendation;
    const recommendationKey = JSON.stringify([latest.incident_id, latest.status, latest.version, rec?.recommendation_id, (data.decisions || []).map(d => [d.execution_id, d.result?.status]), currentApprovals.map(a => [a.approval_id, a.status, a.last_error])]);
    if (detailRecommendationKey !== recommendationKey) {
      $("result").classList.add("hidden");
      $("guidance-result").classList.add("hidden");
      currentRecommendation = null;
      currentGuidance = null;
      if (rec) {
        renderRecommendation(latest.error_code, rec, data.decisions || [], data.processing);
        if (latest.status !== "ACTION_REQUIRED" && !(latest.status === "INVESTIGATING" && latest.synthetic === true && latest.environment === "simulation" && rec.targets?.length)) {
          document.querySelectorAll("#actions .runbook").forEach(el => {
            el.actionable = false;
            setRunbookButtonsDisabled(el, true);
          });
        }
      }
      detailRecommendationKey = recommendationKey;
    }
    if (reanalyzing) {
      $("exec").classList.add("hidden");
      lastExecutionId = null;
    } else if (data.execution && rec && data.execution.recommendation_id === rec.recommendation_id
        && (data.decisions || []).some(d => d.decision === "approve" && d.execution_id === data.execution.execution_id)) {
      showExecResult(data.execution.script_id || "실행 결과", {...data.execution.result,execution_id:data.execution.execution_id}, 200, data.processing);
    }
    if (data.executions_status === "unavailable") $("incident-detail-load-status").textContent = "조치 이력 조회 지연 — 저장된 장애 상태를 표시합니다.";
    else if (reanalyzing) $("incident-detail-load-status").textContent = "장애가 발생해 분석하는 중입니다. 분석이 끝나면 조치 시나리오가 표시됩니다.";
    else if (!rec && latest.status !== "RESOLVED" && latest.status !== "MONITORING") $("incident-detail-load-status").textContent = "분석 중이거나 조치 추천이 아직 없습니다.";
    setClientStatus(latest.status === "RESOLVED" ? "처리 완료" : latest.status === "MONITORING" ? "조치 완료 — 복구 확인 대기" : "장애 상세 조회: " + latest.status);
    return true;
  } catch (error) {
    if (requestId !== incidentDetailRequest) return;
    $("incident-detail-load-status").textContent = "최신 상세 조회 실패 — 마지막 조회 결과를 유지하고 자동으로 다시 확인합니다.";
    return false;
  }
}
$("incident-detail-close").addEventListener("click", () => {
  manualSelectionVersion += 1;
  autoSelectedIncidentId = null;
  closeIncidentDetails();
});
function renderIncidentList() {
  renderCompletedIncidents();
  const filter = incidentFilters[selectedIncidentFilter];
  const items = incidentItems.filter(filter.matches);
  $("incident-list-title").textContent = filter.label + " 장애" + (incidentsLoaded ? " · " + items.length + "건" : "");
  $("incident-list").innerHTML = items.length
    ? '<table class="incident-table"><thead><tr><th scope="col">장애 내용</th><th scope="col">발생 수</th><th scope="col">최근 발생</th></tr></thead><tbody>' + items.map((item, index) => `
      <tr>
        <td class="incident-message"><button type="button" class="incident-detail" aria-controls="incident-detail-panel" data-index="${index}"><strong>${esc(item.error_code || "UNKNOWN_ERROR")}</strong><span class="recent-incident-badge hidden">최근 1분</span>${item.pending_approval ? '<span class="badge approval">결재 대기</span>' : ''}${item.status === "ON_HOLD" ? '<span class="badge ' + (item.hold?.source === "exception_rule" ? 'rule">예외 처리 · 보류' : 'hold">보류') + '</span>' : ''}<span class="muted incident-preview">${esc(item.latest_message || item.representative_message || item.normalized_message || "")}</span></button></td>
        <td>${esc(item.occurrence_count)}</td><td>${esc(formatTime(item.last_seen))}</td>
      </tr>`
    ).join("") + "</tbody></table>"
    : "";
  $("incident-list").querySelectorAll(".incident-detail").forEach(button => button.addEventListener("click", () => {
    manualSelectionVersion += 1;
    autoSelectedIncidentId = null;
    const incident = items[Number(button.dataset.index)];
    loadIncidentDetails(incident, true);
  }));
  $("incident-list").querySelectorAll("tbody tr").forEach((row, index) => row.dataset.lastSeen = items[index].last_seen || "");
  refreshRecentIncidents();
}
function renderCompletedIncidents() {
  const completed = incidentItems.filter(item => item.status === "RESOLVED");
  $("completed-incidents").classList.toggle("hidden", !completed.length);
  $("completed-incidents-title").textContent = "처리 완료 이력 · 최근 10분 · " + completed.length + "건";
  $("completed-incidents-list").innerHTML = completed.map((item, index) =>
    '<button type="button" class="completed-incident-detail secondary" data-index="' + index + '"><strong>' + esc(item.error_code || "UNKNOWN_ERROR")
    + '</strong><span>' + esc(item.service || "unknown") + ' · 처리 완료 · ' + esc(formatDateTime(item.processing?.completed_at || item.recovered_at)) + '</span></button>'
  ).join("");
  $("completed-incidents-list").querySelectorAll(".completed-incident-detail").forEach(button => button.addEventListener("click", () => {
    manualSelectionVersion += 1;
    autoSelectedIncidentId = null;
    loadIncidentDetails(completed[Number(button.dataset.index)], true);
  }));
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
    await refreshSelectedIncident();
  } catch (error) {
    $("incident-list-status").textContent = incidentsLoaded
      ? "장애 목록 조회 실패 — 마지막 조회 결과를 표시하고 있습니다."
      : "장애 목록 조회 지연 — 연결을 다시 확인하고 있습니다.";
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
// Track the opened incident even when the recent list expires or is unavailable.
schedulePoll(refreshSelectedIncident,2000,5000);
schedulePoll(refreshRecentIncidents,1000);
schedulePoll(() => {
  if (!IS_CLIENT && !$("log-tabs-panel").classList.contains("hidden")) return pollActivity();
},2000);

async function getJSON(url) {
  const res = await fetch(url, {cache: "no-store"});
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

let scenarioRunPending = false;
async function loadScenarios(selected = sel.value) {
  const scenarios = await getJSON("/api/v1/log-generator/scenarios");
  sel.replaceChildren();
  scenarios.forEach((s) => {
    const o = document.createElement("option");
    o.value = s.key; o.textContent = s.label; sel.appendChild(o);
  });
  if ([...sel.options].some(option => option.value === selected)) sel.value = selected;
  $("analyze").disabled = scenarioRunPending || !sel.options.length;
}
if (!IS_CLIENT) loadScenarios();

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

let currentSince = null;

let pendingErrorRequestId = null;
async function executeSelectedScenario(createNew = false) {
  if (scenarioRunPending) return;
  scenarioRunPending = true;
  closeIncidentDetails();
  $("analyze").disabled = true;
  if ($("create-error")) $("create-error").disabled = true;
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
    if (createNew && !pendingErrorRequestId) {
      pendingErrorRequestId = globalThis.crypto?.randomUUID?.()
        || "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, char => {
          const value = Math.random() * 16 | 0;
          return (char === "x" ? value : (value & 3 | 8)).toString(16);
        });
    }
    const { data } = await postJSON(createNew ? "/api/v1/log-generator/scenarios/new" : "/api/v1/log-generator/run",
      createNew ? {request_id: pendingErrorRequestId} : {scenario: sel.value});
    if (data.scenario) await loadScenarios(data.scenario.key);
    if (createNew && data.status === "triggered") pendingErrorRequestId = null;

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
    scenarioRunPending = false;
    $("analyze").disabled = !sel.options.length;
    $("analyze").textContent = "분석";
    if ($("create-error")) $("create-error").disabled = false;
  }
}
$("analyze").addEventListener("click", () => executeSelectedScenario());
$("create-error")?.addEventListener("click", () => executeSelectedScenario(true));

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
  const selectionVersion = manualSelectionVersion;
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
      if (selectionVersion !== manualSelectionVersion) return;
      const incidentId = data.recommendation?.incident_id;
      if (incidentId) {
        await loadIncidentDetails(incidentItems.find(item => item.incident_id === incidentId)
          || {incident_id:incidentId, error_code:errorCode});
      } else renderRecommendation(errorCode, data.recommendation, data.decisions || [], data.processing);
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
    refreshSelectedIncident();
    if (IS_CLIENT) syncClientRun();
  }
});
function renderRecommendation(errorCode, rec, decisions = [], processing = null) {
  $("guidance-result").classList.add("hidden");
  currentGuidance = null;
  if (rec?.status === "manual_required") {
    currentErrorCode = errorCode;
    currentRecommendation = rec;
    $("result").classList.add("hidden");
    setClientStatus("수동 조치 및 스크립트 등록 필요");
    return;
  }
  if (rec && rec.status === "resource_guidance") {
    renderResourceGuidance(rec);
    setClientStatus("분석 완료");
    if (!(rec.runbooks || []).length) return;
  }
  currentErrorCode = errorCode;
  currentRecommendation = rec;
  const result = $("result");
  result.classList.remove("hidden");

  $("errcode").textContent = errorCode;
  $("cause").textContent = rec.cause || rec.summary || "";

  // 같은 오류에 대한 조치 방법들을 "조치 시나리오 리스트"로 신뢰도 높은 순으로 보여준다.
  // 시나리오(행)마다 신뢰도·조치·예상 영향·과거 실행·실패 시가 일대일로 매핑되고, 선택한 시나리오로 결재를 요청한다.
  const runbooks = (rec.runbooks || []).map((rb, index) => ({rb, index}))
    .sort((a, b) => (Number(b.rb.confidence) || 0) - (Number(a.rb.confidence) || 0) || a.index - b.index)
    .map(item => item.rb);
  const box = $("actions");
  box.innerHTML = "";

  runbooks.forEach((rb, order) => {
    const pct = Number.isFinite(Number(rb.confidence)) ? Math.max(0, Math.min(100, Number(rb.confidence))) : 0;
    const el = document.createElement("div");
    el.className = "runbook scenario-row";
    el.rb = rb;
    el.innerHTML = `
      <div class="scenario-cols">
        <label class="scenario-pick"><input type="radio" name="scenario-pick" class="scenario-radio">
          <span><strong>${order + 1}. ${esc(rb.script_id || "조치")}</strong><span class="scenario-kind"></span><span class="decision"></span></span></label>
        <div class="cell" data-label="신뢰도">${rb.learned_script ? "운영자 확인 스크립트" : rb.registered_script ? "등록 스크립트 · 평가 없음" : pct + "%"}
          <div class="confidence-bar"><span style="width:${pct}%"></span></div></div>
        <div class="cell" data-label="조치">${esc(rb.action)}</div>
        <div class="cell" data-label="예상 영향">${esc(rb.expected_impact)}</div>
        <div class="cell" data-label="과거 실행">성공 ${Number(rb.history?.success || 0)}회 / 실패 ${Number(rb.history?.failure || 0)}회</div>
        <div class="cell rollback" data-label="실패 시">${esc(rb.rollback)}</div>
      </div>
      <div class="scenario-actions">
        <div class="target-row"><label>실행 대상</label><select class="target-select"></select></div>
        <div class="approval-status muted" role="status"></div>
        <div class="buttons">
          <button class="approve" disabled>결재 요청</button>
          <button class="reject">거부</button>
          <button class="hold-open secondary" type="button">보류</button>
        </div>
        <div class="hold-form hidden">
          <input class="hold-form-reason" maxlength="1000" placeholder="보류 사유 (예: 대외기관 조치 대기, 변경 작업 일정 필요)" aria-label="보류 사유">
          <button class="hold-confirm" type="button">보류 확정</button>
          <button class="hold-cancel secondary" type="button">취소</button>
          <span class="hold-form-status muted" data-base-class="hold-form-status" role="status"></span>
        </div>
      </div>`;

    const action = (rec.actions || []).find(
      (candidate) => candidate.script_id === rb.script_id
    );
    if (action) el.dataset.actionId = action.action_id;
    el.dataset.scriptId = rb.script_id || "";
    el.action = action;
    el.actionable = !["completed", "action_completed"].includes(processing?.state);
    el.kind = action?.learned_script ? "학습된 첨부 스크립트" : action?.execution_mode === "simulation" ? "등록 스크립트 실행" : "조치 제안";
    el.querySelector(".scenario-kind").textContent = el.kind;
    el.querySelector(".scenario-radio").addEventListener("change", () => selectScenario(el));
    const targetSelect = el.querySelector(".target-select");
    const targets = action?.targets || rec.targets || [];
    el.targets = targets;
    const empty = document.createElement("option");
    empty.value = ""; empty.textContent = targets.length ? "대상을 선택하세요" : "이 사건에 등록된 실행 대상이 없습니다";
    targetSelect.appendChild(empty);
    targetSelect.disabled = !targets.length;
    targets.forEach((target, index) => {
      const option = document.createElement("option"); option.value = String(index);
      option.textContent = [environmentLabel(target.environment), target.service, target.host, target.instance].join(" / ") + (target.instance === "log-generator-scripts" ? " (등록 셸 스크립트)" : "");
      targetSelect.appendChild(option);
    });
    // 실행 대상이 하나뿐이면 시나리오 선택만으로 결재를 요청할 수 있게 자동으로 고른다.
    if (targets.length === 1) targetSelect.value = "0";
    el.querySelector(".target-row").classList.toggle("hidden", targets.length < 2);
    targetSelect.addEventListener("change", () => {
      el.querySelector(".approval-status").className = "approval-status muted";
      el.querySelector(".approval-status").textContent = approvalHint(el);
      setRunbookButtonsDisabled(el, false);
    });
    el.querySelector(".approve").addEventListener(
      "click", () => decideRunbook(rb.script_id, action, el, "approve")
    );
    el.querySelector(".reject").addEventListener(
      "click", () => decideRunbook(rb.script_id, action, el, "reject")
    );
    el.querySelector(".hold-open").addEventListener("click", () => {
      el.querySelector(".hold-form").classList.remove("hidden");
      el.querySelector(".hold-form-reason").focus();
    });
    el.querySelector(".hold-cancel").addEventListener("click", () => {
      el.querySelector(".hold-form").classList.add("hidden");
      el.querySelector(".hold-form-status").textContent = "";
    });
    el.querySelector(".hold-confirm").addEventListener("click", () =>
      changeHold("hold", el.querySelector(".hold-form-reason"), el.querySelector(".hold-form-status")));

    // 이미 승인/거부한 Runbook은 새로고침해도 처리된 상태로 보여준다.
    const decided = action && decisions.find(
      (d) => d.action_id === action.action_id
    );
    if (decided) markDecided(el, decided.decision, decided.result?.status, processing);

    box.appendChild(el);
    el.querySelector(".approval-status").textContent = processing?.state === "completed" ? "이 장애는 처리가 완료되었습니다."
      : decided?.result?.status === "success" ? "조치가 완료되었습니다. 서비스 복구 상태를 확인하세요."
      : decided?.decision === "reject" ? "거부한 조치입니다." : approvalHint(el);
    if (!decided) applyApprovalState(el, rb.script_id);
    setRunbookButtonsDisabled(el, el.classList.contains("decided"));
  });

  // 한 추천에서는 조치 하나만 실행한다 - 이미 승인(또는 결재 대기)된 게 있으면 나머지를 잠근다.
  const runbookEls = [...box.querySelectorAll(".runbook")];
  const pendingEl = runbookEls.find(el => el.approvalPending);
  if (decisions.some((d) => d.decision === "approve")) lockOtherRunbooks();
  else if (pendingEl) lockOtherRunbooks(pendingEl);

  // 결재 대기·처리된 시나리오가 있으면 그것을, 아니면 같은 추천에서 보던 시나리오(없으면 최고 신뢰도)를 선택한다.
  const focusEl = pendingEl || runbookEls.find(el => el.classList.contains("decided") && !el.classList.contains("locked"))
    || (scenarioSelectionKey?.recommendationId === rec.recommendation_id
        && runbookEls.find(el => el.dataset.scriptId === scenarioSelectionKey.scriptId))
    || runbookEls[0];
  if (focusEl) selectScenario(focusEl, rec.recommendation_id);
  paintResultState(processing?.state === "completed");

  updateResultAutoClose(rec.incident_id, processing);

  // 실행 결과는 결재 승인으로 실제 실행된 조치만 보여준다 (거부·결재 대기·이전 발생분 제외).
  const executed = decisions.filter((d) => d.decision === "approve" && (d.execution_id || d.result?.execution_id));
  if (executed.length) {
    const last = executed[executed.length - 1];
    showExecResult(last.script_id, {...last.result,execution_id:last.execution_id || last.result?.execution_id}, 200, processing);
  } else {
    $("exec").classList.add("hidden");
    lastExecutionId = null;
  }
  setClientStatus(processing?.state === "completed" ? "처리 완료" : decisions.some(
    (d) => d.decision === "approve" && d.result?.status === "success"
  ) ? "명령 실행 완료 — 업무 복구 확인 필요" : "분석 완료");
}

// 결재 승인 → 스크립트 실행 결과는 배너 하단에 보여준다. 처리 완료되면 배너를 자동으로 닫되,
// 이 화면에서 실행을 지켜본 경우에는 실행 결과를 확인할 수 있도록 잠시 뒤에 닫는다.
const RESULT_AUTOCLOSE_MS = 15000;
let liveResultIncidentId = null;
const closedResultIncidents = new Set();
let resultAutoCloseTimer = null;
function updateResultAutoClose(incidentId, processing) {
  const completed = processing?.state === "completed";
  const notice = $("result-autoclose");
  if (!completed) {
    liveResultIncidentId = incidentId;
    closedResultIncidents.delete(incidentId);
    notice.classList.add("hidden");
    return;
  }
  if (liveResultIncidentId !== incidentId || closedResultIncidents.has(incidentId)) {
    $("result").classList.add("hidden");
    return;
  }
  notice.textContent = "조치가 완료되었습니다. 실행 결과 확인 후 " + (RESULT_AUTOCLOSE_MS / 1000) + "초 뒤 이 배너는 자동으로 닫힙니다.";
  notice.classList.remove("hidden");
  if (resultAutoCloseTimer?.incidentId === incidentId) return;
  if (resultAutoCloseTimer) clearTimeout(resultAutoCloseTimer.id);
  resultAutoCloseTimer = {incidentId, id: setTimeout(() => {
    resultAutoCloseTimer = null;
    closedResultIncidents.add(incidentId);
    liveResultIncidentId = null;
    if (currentRecommendation?.incident_id === incidentId) $("result").classList.add("hidden");
  }, RESULT_AUTOCLOSE_MS)};
}

let scenarioSelectionKey = null;
function selectScenario(el, recommendationId = currentRecommendation?.recommendation_id) {
  document.querySelectorAll("#actions .runbook").forEach(row => {
    const selected = row === el;
    row.classList.toggle("selected", selected);
    row.querySelector(".scenario-radio").checked = selected;
    if (!selected) row.querySelector(".hold-form").classList.add("hidden");
  });
  scenarioSelectionKey = {recommendationId, scriptId: el.dataset.scriptId};
  $("scenario-tag").textContent = el.kind || "조치 제안";
  $("scenario-incident").textContent = el.rb?.incident || "-";
  $("scenario-cause").textContent = el.rb?.estimated_cause || "-";
}
// 장애 진행 중에는 빨간색, 처리 완료(해결)되면 초록색으로 배너를 표시한다.
function paintResultState(resolved) {
  $("result").classList.toggle("incident-resolved", resolved);
  $("result").classList.toggle("incident-open", !resolved);
  $("result-state").textContent = resolved ? "장애 해결" : "장애 발생";
}

const OTHER_ACTION_LOCKED = "다른 조치가 이미 실행(또는 결재 대기)되어 선택할 수 없습니다.";
const APPROVAL_LABELS = {PENDING: "결재 대기", EXECUTING: "결재 승인 · 실행 중", APPROVED: "결재 승인", REJECTED: "결재 반려", FAILED: "결재 승인 후 실행 불가", EXPIRED: "결재 만료 (새 분석으로 대체)"};

function applyApprovalState(el, scriptId) {
  const approval = currentApprovals.find(item => item.script_id === scriptId
    && (!item.recommendation_id || item.recommendation_id === currentRecommendation?.recommendation_id
        || ["PENDING", "EXECUTING"].includes(item.status)));
  el.approvalPending = Boolean(approval && ["PENDING", "EXECUTING"].includes(approval.status));
  if (!approval) return;
  const status = el.querySelector(".approval-status");
  if (el.approvalPending) {
    status.className = "approval-status status-pending";
    status.textContent = "⏳ 결재 대기 — " + (approval.requested_by || "-") + " · " + formatDateTime(approval.requested_at)
      + " 요청. 관리자 결재 승인 후 조치가 실행됩니다." + (approval.last_error ? " (직전 승인 시도 차단: " + approvalBlockReason({reason: approval.last_error}).replace("실행 차단 — ", "") + ")" : "");
    el.querySelector(".decision").textContent = "⏳ 결재 대기중";
    if (approval.target) {
      const index = el.targets.findIndex(target => JSON.stringify(target) === JSON.stringify(approval.target));
      if (index >= 0) el.querySelector(".target-select").value = String(index);
    }
  } else if (approval.status === "REJECTED" || approval.status === "FAILED") {
    status.className = "approval-status status-err";
    status.textContent = (APPROVAL_LABELS[approval.status]) + " — " + (approval.decided_by || "-")
      + (approval.decision_reason ? " · 사유: " + approval.decision_reason : "")
      + (approval.last_error ? " · " + approvalBlockReason({reason: approval.last_error}).replace("실행 차단 — ", "") : "")
      + " · 대상을 확인하고 다시 결재를 요청할 수 있습니다.";
  }
}

function approvalHint(el) {
  if (!el.action) return "이 추천에는 자동 실행 가능한 조치가 없습니다. 분석 내용과 진단 항목을 확인하세요.";
  if (!el.targets.length) return "이 조치에 등록된 실행 대상이 없습니다. 장애 상세의 수동 조치 등록에서 수행한 조치 방법을 입력하세요.";
  return el.querySelector(".target-select").value === ""
    ? "조치 대상을 먼저 선택한 뒤 ‘결재 요청’을 누르세요."
    : "‘결재 요청’을 누르면 관리자 결재 승인 후 선택한 대상에 조치가 실행됩니다.";
}
function approvalBlockReason(data) {
  const checks = {redundancy:"이중화 컨테이너 정상", maintenance:"점검 상태 아님", rollback_ready:"실행 상태 복원 가능", host_idle:"진행 중인 실행 없음"};
  const reasons = {
    "action not enabled in host manifest":"Agent 설정에서 이 작업이 비활성화되어 있습니다.",
    "target not bound to recommendation":"선택한 대상이 이 장애의 추천과 연결되지 않았습니다.",
    "agent machine credential not configured":"실행 Agent 인증 값이 설정되지 않았습니다.",
    "agent machine credential rejected":"실행 Agent가 인증을 거절했습니다. 인증 설정을 확인하세요.",
    "stale recommendation":"장애 또는 추천이 갱신되었습니다. 최신 장애 상세에서 다시 승인하세요.",
    "expired recommendation":"추천 유효 시간이 지났습니다. 최신 분석 결과가 필요합니다.",
    "incident is not actionable":"현재 장애 상태(보류·완료 등)에서는 조치를 실행할 수 없습니다.",
    "action not allowed for incident":"최신 분석 결과에 이 조치·대상이 없습니다. 다시 결재를 요청하세요.",
    "recommendation does not belong to incident":"장애의 최신 추천이 바뀌었습니다. 다시 결재를 요청하세요.",
    "invalid requested_by":"결재 요청자를 확인하세요.",
    "superseded by newer analysis":"같은 오류가 다시 발생해 새로 분석되었습니다. 새 조치 제안에서 다시 결재를 요청하세요.",
    "incident resolved":"장애가 이미 처리 완료되어 결재가 만료되었습니다.",
    "not_found":"결재 건을 찾을 수 없습니다. 목록을 새로 불러온 뒤 다시 시도하세요.",
    "host is executing or waiting for business recovery confirmation":"대상이 다른 조치를 실행 중이거나 복구 확인을 기다리고 있습니다.",
    "dependency unavailable; inspect service status":"실행 Agent 또는 저장소에 연결할 수 없습니다. 기동·연결 상태를 확인하세요.",
    "container is not the registered Compose service":"등록한 Compose 프로젝트·서비스와 실제 컨테이너가 다릅니다.",
    "container image differs from approved image":"실제 컨테이너 이미지가 승인된 이미지와 다릅니다.",
  };
  const failed = (data.checks || []).filter(check => !check.passed);
  let message = "실행 차단 — " + (failed.length
      ? failed.map(check => (checks[check.name] || check.name) + " 조건 미충족").join(" / ")
      : (reasons[data.reason] || data.reason || reasons[data.status] || data.status || "응답 상세를 확인하세요."));
  if (failed.some(check => check.name === "redundancy")) message += " 건강한 별도 이중화 컨테이너가 필요합니다. 기본 단일 구성에서는 재시작이 차단됩니다.";
  return message;
}

// 보류는 결재 요청과 별개로 장애 단위로 가능 여부를 판단한다.
let holdState = {holdable: false, pending: false, held: false};
function updateRunbookHoldButton(el) {
  const blocked = holdPending || !holdState.holdable || holdState.pending || holdState.held;
  el.querySelector(".hold-open").disabled = blocked;
  el.querySelectorAll(".hold-confirm, .hold-form-reason").forEach(input => input.disabled = blocked);
  el.querySelector(".hold-open").title = holdState.pending ? "결재 대기 중에는 보류할 수 없습니다. 결재 반려 후 보류하세요."
    : holdState.held ? "이미 보류된 장애입니다." : !holdState.holdable ? "조치 실행 중이거나 완료된 장애는 보류할 수 없습니다." : "";
  if (blocked && !holdPending) el.querySelector(".hold-form").classList.add("hidden");
}
function setDecisionButtonsDisabled(el, disabled) {
  if (!disabled) {
    setRunbookButtonsDisabled(el, false);
    return;
  }
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

function markDecided(el, decision, resultStatus = null, processing = null) {
  el.classList.add("decided");
  el.querySelector(".decision").textContent =
    decision === "approve" ? (processing?.state === "completed" ? "✓ 처리 완료" : resultStatus === "success" ? "✓ 조치 완료 · 복구 확인 대기" : "✓ 승인됨") : "✗ 거부됨";
  setRunbookButtonsDisabled(el, true);
}

function showExecResult(scriptId, data, status, processing = null) {
  $("exec").classList.remove("hidden");
  $("exec-title").textContent = scriptId;
  lastExecutionId = data.execution_id || null;
  $("refresh-execution").classList.toggle("hidden", !lastExecutionId);
  $("verify-execution").classList.toggle("hidden", !lastExecutionId || data.status !== "success" || (processing && (processing.state !== "action_completed" || processing.confirmation !== "pending_execution")));
  $("verify-execution").textContent = data.execution_mode === "simulation" ? "스크립트 결과 확인" : "업무 복구 확인";
  const ok = ["success", "rejected", "already_processed"].includes(data.status);
  const s = $("exec-status");
  s.className = ok ? "status-ok" : "status-err";
  const labels = {success:"명령 실행 완료",rejected:"거부됨",failed:"실행 실패",timeout:"실행 시간 초과",blocked:"실행 차단",unknown:"실행 결과 확인 필요",running:"실행중",reserved:"실행 대기"};
  s.textContent = (processing?.state === "completed" ? "처리 완료 · " : "") + (labels[data.status] || data.status) + (data.returncode !== undefined
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
  updateRunbookHoldButton(el);
  el.querySelectorAll(".buttons .approve, .buttons .reject").forEach((b) => {
    const targetRequired = b.matches(".approve");
    b.disabled = disabled || el.actionable === false || !el.action || el.executionPending
      || el.classList.contains("decided") || el.approvalPending
      || (el.classList.contains("locked") && b.matches(".approve, .reject"))
      || (targetRequired && el.querySelector(".target-select").value === "");
  });
  el.querySelector(".target-select").disabled = Boolean(el.executionPending) || Boolean(el.approvalPending)
    || el.classList.contains("decided") || el.actionable === false || !el.targets.length;
}

async function requestApproval(scriptId, action, el) {
  const incidentId = currentRecommendation.incident_id;
  el.executionPending = true;
  setRunbookButtonsDisabled(el, true);
  lockOtherRunbooks(el);
  const status = el.querySelector(".approval-status");
  status.className = "approval-status status-pending";
  status.textContent = "결재를 요청하는 중…";
  try {
    const { data } = await postJSON("/api/v1/approvals", actionBody(action, el));
    if (!el.isConnected || (selectedIncidentId && selectedIncidentId !== incidentId)) return;
    if (data.approval && ["pending", "already_pending"].includes(data.status)) {
      currentApprovals = [data.approval, ...currentApprovals.filter(item => item.approval_id !== data.approval.approval_id)];
      el.executionPending = false;
      applyApprovalState(el, scriptId);
      status.textContent = (data.status === "already_pending" ? "이미 결재 대기중인 요청이 있습니다. " : "결재 요청 완료 — ") + "관리자 결재 승인 후 조치가 실행됩니다.";
      setClientStatus("결재 요청 — 관리자 승인 대기");
      await loadIncidents();
      if (!IS_CLIENT) loadApprovals();
      return;
    }
    status.className = "approval-status status-err";
    status.textContent = approvalBlockReason(data).replace("실행 차단", "결재 요청 차단");
    unlockOtherRunbooks();
  } catch (error) {
    status.className = "approval-status status-err";
    status.textContent = "결재 요청 실패 — 연결 상태를 확인하고 다시 시도하세요.";
    unlockOtherRunbooks();
  } finally {
    el.executionPending = false;
    setRunbookButtonsDisabled(el, false);
  }
}

async function decideRunbook(scriptId, action, el, decision) {
  if (!currentErrorCode || !currentRecommendation || !action) {
    el.querySelector(".decision").textContent = "최신 Incident 추천을 다시 불러오세요.";
    return;
  }
  // 운영자의 '결재 요청'은 실행하지 않고 결재 대기열에 올린다. 실행은 관리자 결재 승인 시점.
  if (decision === "approve") return requestApproval(scriptId, action, el);
  const incidentId = currentRecommendation.incident_id;
  el.executionPending = true;
  setRunbookButtonsDisabled(el, true);
  el.querySelector(".approval-status").className = "approval-status status-pending";
  el.querySelector(".approval-status").textContent = decision === "approve" ? "승인한 대상에 명령을 실행하는 중…" : "거부를 처리하는 중…";
  // 응답을 기다리는 동안 다른 조치를 누르지 못하게 먼저 잠근다.
  if (decision === "approve") lockOtherRunbooks(el);

  const endpoint = decision === "approve"
    ? "/api/v1/remediations/approve"
    : "/api/v1/remediations/reject";

  // 실행 결과 영역은 실제 실행(승인)일 때만 연다. 거부는 시나리오 행의 상태로만 표시한다.
  if (decision === "approve") {
    $("exec").classList.remove("hidden");
    $("exec-title").textContent = scriptId;
    $("exec-status").textContent = "";
    $("exec-output").textContent = "";
  }

  try {
    const { status, data } = await postJSON(endpoint, actionBody(action,el));
    if (!el.isConnected || (selectedIncidentId && selectedIncidentId !== incidentId)) {
      await refreshSelectedIncident();
      return;
    }
    if (decision === "approve") showExecResult(scriptId, data, status);
    if (decision === "approve" && !data.execution_id) {
      el.querySelector(".approval-status").className = "approval-status status-err";
      el.querySelector(".approval-status").textContent = approvalBlockReason(data);
    } else {
      el.querySelector(".approval-status").className = "approval-status " + (data.status === "success" ? "status-ok" : "muted");
      el.querySelector(".approval-status").textContent = data.status === "success"
        ? "명령 실행 완료 — 아래 ‘업무 복구 확인’을 눌러 복구 상태를 확인하세요."
        : "요청 처리 결과: " + data.status;
    }
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
    markDecided(el, decision, data.status);
    if (decision === "approve" && data.status === "success") {
      setClientStatus("명령 실행 완료 — 업무 복구 확인 필요");
    }
    await loadIncidents();
  } catch (e) {
    if (!el.isConnected || (selectedIncidentId && selectedIncidentId !== incidentId)) return;
    el.querySelector(".approval-status").className = "approval-status status-err";
    el.querySelector(".approval-status").textContent = "승인·조치 요청 실패 — 연결 상태와 실행 결과를 확인하세요.";
    if (decision === "approve") {
      $("exec-status").className = "status-err";
      $("exec-status").textContent = "요청 실패: " + e;
    }
    setRunbookButtonsDisabled(el, false);
    if (decision === "approve") unlockOtherRunbooks();
  } finally {
    el.executionPending = false;
    setRunbookButtonsDisabled(el, false);
  }
}

// ---------------------------------------------------------------- 장애 이력
const METHOD_LABELS = {script: "등록 스크립트", learned_script: "학습된 첨부 스크립트", manual: "수동 조치", hold: "보류", unknown: "기록"};
const CONFIRMATION_LABELS = {operator_report: "운영자 확인", business_probe: "서비스 복구 검사", simulation: "스크립트 결과 확인", exception_rule: "예외 처리 규칙", manual: "운영자 보류"};
function renderIncidentHistory(history, status) {
  currentHistory = history || null;
  const entries = (history && history.entries) || [];
  const summary = history && history.summary;
  $("history-count").classList.toggle("hidden", !entries.length);
  $("history-count").textContent = entries.length > 9 ? "9+" : String(entries.length);
  $("history-toggle").setAttribute("aria-label", "과거 유사 장애 조치 이력" + (entries.length ? " " + entries.length + "건" : ""));
  $("incident-history-summary").classList.toggle("hidden", !summary);
  $("incident-history-summary").textContent = summary
    ? "같은 오류 처리 완료 " + summary.resolved_count + "회 · 가장 많이 사용한 조치: " + summary.most_common_method
      + " (" + summary.most_common_count + "회) · 최근 조치: " + summary.latest_method + " (" + formatDateTime(summary.latest_resolved_at) + ")"
    : "";
  if (status === "unavailable") {
    $("incident-history").innerHTML = '<p class="muted">장애 이력 조회 실패 — 잠시 후 자동으로 다시 확인합니다.</p>';
    return;
  }
  $("incident-history").innerHTML = entries.length
    ? '<table class="workflow-table"><thead><tr><th>일시</th><th>구분</th><th>단위시스템 / 환경</th><th>조치 방법</th><th>운영자</th><th>확인 방식</th></tr></thead><tbody>'
      + entries.map(item => '<tr><td>' + esc(formatDateTime(item.resolved_at)) + (item.same_incident ? '<span class="badge hold">이 장애</span>' : '') + '</td><td>'
        + esc(METHOD_LABELS[item.method_type] || item.method_type) + '</td><td>' + esc((item.service || "-") + " / " + environmentLabel(item.environment)) + '</td><td>'
        + esc(item.method) + (item.script_id ? '<div class="muted">' + esc(item.script_id) + '</div>' : '') + (item.attachment ? '<div class="muted">첨부: ' + esc(item.attachment) + '</div>' : '') + (item.executed_shell ? '<div class="muted">호출한 셸: ' + esc(shellLabel(item.executed_shell)) + '</div>' : '')
        + (item.kind === "hold" && item.released_at ? '<div class="muted">해제: ' + esc(formatDateTime(item.released_at)) + '</div>' : '')
        + '</td><td>' + esc(item.operator || "-") + '</td><td>' + esc(CONFIRMATION_LABELS[item.confirmation] || item.confirmation || "-") + '</td></tr>').join("")
      + '</tbody></table>'
    : '<p class="muted">같은 오류의 과거 조치 이력이 없습니다. 이번 조치가 완료되면 이력으로 남습니다.</p>';
}

// ---------------------------------------------------------------- 보류
function renderHoldControls(incident, data) {
  const held = incident.status === "ON_HOLD";
  const pending = (data.approvals || []).some(item => ["PENDING", "EXECUTING"].includes(item.status));
  const holdable = !held && !["RESOLVED", "REMEDIATING"].includes(incident.status) && !incident.active_execution_id;
  holdState = {holdable, pending, held};
  document.querySelectorAll("#actions .runbook").forEach(updateRunbookHoldButton);
  // 보류는 조치 시나리오의 "보류" 버튼(누르면 사유 입력칸 표시)으로 하고, 여기서는 해제·예외 처리만 한다.
  $("hold-controls").classList.toggle("hidden", !held && !holdable);
  $("release-button").classList.toggle("hidden", !held);
  $("release-button").disabled = holdPending;
  const ruleBtn = $("rule-from-incident");
  ruleBtn.classList.toggle("hidden", Boolean(data.exception_rule) || incident.error_code === "UNKNOWN_ERROR");
  ruleBtn.disabled = holdPending;
  if (!holdPending) {
    $("hold-status").className = "muted";
    $("hold-status").textContent = data.exception_rule
      ? "예외 처리 규칙 적용 대상: " + data.exception_rule.reason
      : pending ? "결재 대기 중에는 보류할 수 없습니다. 결재 반려 후 보류하세요." : "";
  }
}
async function changeHold(kind, reasonInput = null, statusEl = $("hold-status")) {
  if (!selectedIncidentId || holdPending) return;
  const incidentId = selectedIncidentId;
  const reason = reasonInput ? reasonInput.value.trim() : "";
  if (kind === "hold" && !reason) {
    statusEl.className = (statusEl.dataset.baseClass || "") + " " + "status-err";
    statusEl.textContent = "보류 사유를 입력하세요.";
    reasonInput?.focus();
    return;
  }
  holdPending = true;
  $("release-button").disabled = true;
  document.querySelectorAll("#actions .runbook").forEach(updateRunbookHoldButton);
  statusEl.className = (statusEl.dataset.baseClass || "") + " " + "status-pending";
  statusEl.textContent = kind === "hold" ? "보류 처리 중…" : "보류 해제 중…";
  try {
    const { ok, data } = await postJSON("/api/v1/incidents/" + encodeURIComponent(incidentId) + "/" + kind,
      {operator: IS_CLIENT ? "operator" : ($("approver").value.trim() || "admin"), reason});
    if (selectedIncidentId !== incidentId) return;
    statusEl.className = (statusEl.dataset.baseClass || "") + " " + (ok ? "status-ok" : "status-err");
    statusEl.textContent = ok ? (kind === "hold" ? "보류했습니다. ‘보류’ 탭에서 계속 확인할 수 있습니다." : "보류를 해제했습니다. 조치를 진행하세요.")
      : ({"approval pending; reject the approval before holding": "결재 대기 중입니다. 결재 반려 후 보류하세요.",
          "incident cannot be held in its current state": "조치 실행 중이거나 완료된 장애는 보류할 수 없습니다.",
          "incident changed; reload details": "장애 정보가 갱신되었습니다. 다시 시도하세요."}[data.reason] || "처리 실패: " + (data.reason || data.status));
    if (ok && reasonInput) reasonInput.value = "";
  } catch (error) {
    statusEl.className = (statusEl.dataset.baseClass || "") + " " + "status-err";
    statusEl.textContent = "요청 실패 — 연결 상태를 확인하세요.";
  } finally {
    holdPending = false;
    document.querySelectorAll("#actions .runbook").forEach(updateRunbookHoldButton);
    await loadIncidents();
  }
}
$("release-button").addEventListener("click", () => changeHold("release"));
$("rule-from-incident").addEventListener("click", async () => {
  const incident = currentDetailedIncident;
  if (!incident) return;
  const DEFAULT_RULE_REASON = "즉시 해결이 어려운 오류 — 보류 후 발생 알림";
  const input = typeof globalThis.prompt === "function" ? globalThis.prompt("예외 처리 사유를 입력하세요.", DEFAULT_RULE_REASON) : DEFAULT_RULE_REASON;
  if (input === null) return;
  const reason = String(input || "").trim() || DEFAULT_RULE_REASON;
  holdPending = true;
  $("hold-status").className = "status-pending";
  $("hold-status").textContent = "예외 처리 규칙을 등록하는 중…";
  try {
    const { ok, data } = await postJSON("/api/v1/exception-rules", {
      error_code: incident.error_code, service: incident.service, environment: incident.environment,
      reason, notify_interval_seconds: 300, created_by: $("approver").value.trim() || "admin", incident_id: incident.incident_id,
    });
    $("hold-status").className = ok ? "status-ok" : "status-err";
    $("hold-status").textContent = ok ? "예외 처리 규칙을 등록했습니다." + ((data.held_incidents || []).length ? " 이 장애를 보류했습니다." : "") : "등록 실패: " + (data.reason || data.status);
    loadRules();
  } catch (error) {
    $("hold-status").className = "status-err";
    $("hold-status").textContent = "요청 실패 — 연결 상태를 확인하세요.";
  } finally {
    holdPending = false;
    await loadIncidents();
  }
});

// ------------------------------------------------------- 결재 대기 (admin)
let approvalDecisionPending = false;
function approvalTarget(item) {
  const target = item.target || {};
  return [environmentLabel(target.environment), target.service, target.host, target.instance].filter(Boolean).join(" / ");
}
async function loadApprovals() {
  if (IS_CLIENT) return;
  try {
    const [pending, recent] = await Promise.all([
      getJSON("/api/v1/approvals?status=PENDING,EXECUTING"),
      getJSON("/api/v1/approvals?status=APPROVED,REJECTED,FAILED,EXPIRED&limit=10"),
    ]);
    const items = pending.approvals || [];
    $("approval-count").textContent = items.length + "건";
    $("approval-list").innerHTML = items.length
      ? '<table class="workflow-table"><thead><tr><th>요청 시각</th><th>장애</th><th>조치 / 대상</th><th>요청자</th><th>결재</th></tr></thead><tbody>'
        + items.map(item => '<tr><td>' + esc(formatDateTime(item.requested_at)) + '</td><td><strong>' + esc(item.error_code) + '</strong><div class="muted">' + esc(item.service) + ' · ' + esc(item.incident_id) + '</div></td><td>'
          + esc(item.script_id) + '<div class="muted">' + esc(approvalTarget(item)) + '</div>' + (item.last_error ? '<div class="status-err">직전 시도 차단: ' + esc(approvalBlockReason({reason: item.last_error}).replace("실행 차단 — ", "")) + '</div>' : '')
          + '</td><td>' + esc(item.requested_by) + (item.comment ? '<div class="muted">' + esc(item.comment) + '</div>' : '') + '</td><td><div class="workflow-actions">'
          + (item.status === "EXECUTING" ? '<span class="status-pending">실행 중…</span>' : '<button type="button" class="approval-approve" data-id="' + esc(item.approval_id) + '">승인</button><button type="button" class="danger approval-reject" data-id="' + esc(item.approval_id) + '">반려</button>')
          + '</div></td></tr>').join("") + '</tbody></table>'
      : '<p class="muted">결재 대기 중인 조치가 없습니다.</p>';
    $("approval-list").querySelectorAll(".approval-approve").forEach(button => button.addEventListener("click", () => decideApproval(button.dataset.id, "approve")));
    $("approval-list").querySelectorAll(".approval-reject").forEach(button => button.addEventListener("click", () => decideApproval(button.dataset.id, "reject")));
    $("approval-list").querySelectorAll("button").forEach(button => button.disabled = approvalDecisionPending);
    const done = recent.approvals || [];
    $("approval-history").innerHTML = done.length
      ? '<table class="workflow-table"><tbody>' + done.map(item => '<tr><td>' + esc(formatDateTime(item.decided_at)) + '</td><td>' + esc(APPROVAL_LABELS[item.status] || item.status)
        + '</td><td>' + esc(item.error_code) + ' · ' + esc(item.script_id) + '</td><td>' + esc(item.decided_by || "-") + '</td><td>' + esc(item.result_status || item.decision_reason || item.last_error || "") + '</td></tr>').join("") + '</tbody></table>'
      : '<p class="muted">처리된 결재가 없습니다.</p>';
  } catch (error) {
    $("approval-status").textContent = "결재 목록 조회 실패 — 자동으로 다시 확인합니다.";
    return false;
  }
}
async function decideApproval(approvalId, decision) {
  if (approvalDecisionPending) return;
  const approver = $("approver").value.trim();
  if (!approver) { $("approval-status").className = "status-err"; $("approval-status").textContent = "결재자를 입력하세요."; return; }
  let reason = "";
  if (decision === "reject") {
    reason = (globalThis.prompt ? globalThis.prompt("반려 사유를 입력하세요.", "") : "") || "";
  }
  approvalDecisionPending = true;
  $("approval-list").querySelectorAll("button").forEach(button => button.disabled = true);
  $("approval-status").className = "status-pending";
  $("approval-status").textContent = decision === "approve" ? "결재 승인 — 조치를 실행하는 중…" : "반려 처리 중…";
  try {
    const { ok, data } = await postJSON("/api/v1/approvals/" + encodeURIComponent(approvalId) + "/" + decision, {approver, reason});
    const approval = data.approval || {};
    if (decision === "reject") {
      $("approval-status").className = ok ? "status-ok" : "status-err";
      $("approval-status").textContent = ok ? "반려했습니다." : "반려 실패: " + (data.reason || data.status);
    } else if (approval.status === "APPROVED") {
      $("approval-status").className = data.status === "success" ? "status-ok" : "status-err";
      $("approval-status").textContent = "결재 승인 · 조치 실행 결과: " + (data.status === "success" ? "명령 실행 완료" : data.status) + (data.execution_mode === "simulation" ? " (등록 스크립트)" : "");
    } else {
      $("approval-status").className = "status-err";
      $("approval-status").textContent = (approval.status === "FAILED" ? "결재 종료 — " : "실행 차단 · 결재 대기 유지 — ") + approvalBlockReason(data).replace("실행 차단 — ", "");
    }
    if (approval.incident_id && approval.incident_id === selectedIncidentId) detailRecommendationKey = null;
  } catch (error) {
    $("approval-status").className = "status-err";
    $("approval-status").textContent = "결재 요청 처리 실패 — 연결 상태를 확인하세요.";
  } finally {
    approvalDecisionPending = false;
    await Promise.all([loadApprovals(), loadIncidents(), loadNotifications()]);
  }
}

// ------------------------------------------------ 에러별 예외 처리 규칙 (admin)
async function loadRules() {
  if (IS_CLIENT) return;
  try {
    const data = await getJSON("/api/v1/exception-rules");
    const rules = data.rules || [];
    $("rule-list").innerHTML = rules.length
      ? '<table class="workflow-table"><thead><tr><th>오류 코드</th><th>적용 범위</th><th>사유</th><th>알림 간격</th><th>등록</th><th></th></tr></thead><tbody>'
        + rules.map(rule => '<tr><td><strong>' + esc(rule.error_code) + '</strong></td><td>' + esc((rule.service || "전체 단위시스템") + " / " + (rule.environment ? environmentLabel(rule.environment) : "전체 환경"))
          + '</td><td>' + esc(rule.reason) + '</td><td>' + (rule.notify_interval_seconds ? esc(rule.notify_interval_seconds) + "초" : "매 발생") + '</td><td>' + esc(rule.created_by) + '<div class="muted">' + esc(formatDateTime(rule.created_at))
          + '</div></td><td><button type="button" class="danger rule-delete" data-id="' + esc(rule.rule_id) + '">삭제</button></td></tr>').join("") + '</tbody></table>'
      : '<p class="muted">등록된 예외 처리 규칙이 없습니다.</p>';
    $("rule-list").querySelectorAll(".rule-delete").forEach(button => button.addEventListener("click", async () => {
      button.disabled = true;
      await fetch("/api/v1/exception-rules/" + encodeURIComponent(button.dataset.id), {method: "DELETE"});
      loadRules();
    }));
  } catch (error) {
    $("rule-list").innerHTML = '<p class="muted">규칙 조회 실패 — 자동으로 다시 확인합니다.</p>';
    return false;
  }
}
$("rule-form").addEventListener("submit", async event => {
  event.preventDefault();
  $("rule-submit").disabled = true;
  $("rule-status").className = "status-pending";
  $("rule-status").textContent = "등록 중…";
  try {
    const { ok, data } = await postJSON("/api/v1/exception-rules", {
      error_code: $("rule-code").value.trim(), service: $("rule-service").value.trim() || null,
      environment: $("rule-environment").value.trim() || null, reason: $("rule-reason").value.trim(),
      notify_interval_seconds: Number.parseInt($("rule-interval").value || "0", 10), created_by: $("approver").value.trim() || "admin",
    });
    $("rule-status").className = ok ? "status-ok" : "status-err";
    $("rule-status").textContent = ok ? (data.status === "exists" ? "같은 범위의 규칙이 이미 있습니다." : "등록했습니다. 이후 감지되는 같은 오류는 자동 보류·알림됩니다.") : "등록 실패: " + (data.reason || data.status);
    if (ok) ["rule-code", "rule-service", "rule-environment", "rule-reason"].forEach(id => $(id).value = "");
    loadRules();
  } catch (error) {
    $("rule-status").className = "status-err";
    $("rule-status").textContent = "요청 실패 — 연결 상태를 확인하세요.";
  } finally {
    $("rule-submit").disabled = false;
  }
});

// ---------------------------------------------------------------- 알림
const NOTIFICATION_KINDS = {exception_hold: "예외 처리 보류", exception_occurrence: "예외 오류 재발생", approval_requested: "결재 요청", approval_decided: "결재 처리", incident_held: "보류"};
async function loadNotifications() {
  try {
    const data = await getJSON("/api/v1/notifications?limit=8");
    const items = data.notifications || [];
    $("notification-count").classList.toggle("hidden", !data.unread);
    $("notification-count").textContent = data.unread > 99 ? "99+" : String(data.unread || "");
    $("notification-bell").setAttribute("aria-label", data.unread ? "알림 (새 알림 " + data.unread + "건)" : "알림");
    $("notification-list").className = items.length ? "" : "muted";
    $("notification-list").innerHTML = items.length
      ? items.map(item => '<div class="notification' + (item.read ? '' : ' unread') + '"><strong>' + esc(item.title) + '</strong>'
        + '<span class="muted">' + esc(formatDateTime(item.created_at)) + ' · ' + esc(NOTIFICATION_KINDS[item.kind] || item.kind) + (item.delivery && item.delivery !== "ui" ? ' · ' + esc(item.delivery) : '') + '</span><div>' + esc(item.message) + '</div></div>').join("")
      : "새 알림이 없습니다.";
  } catch (error) {
    $("notification-list").textContent = "알림 조회 실패 — 자동으로 다시 확인합니다.";
    return false;
  }
}
function setNotificationsOpen(open) {
  $("notification-panel").classList.toggle("hidden", !open);
  $("notification-bell").setAttribute("aria-expanded", String(open));
  if (open) loadNotifications();
}
$("notification-bell").addEventListener("click", event => {
  event.stopPropagation();
  setNotificationsOpen($("notification-panel").classList.contains("hidden"));
});
document.addEventListener("click", event => {
  if (!$("notification-panel").classList.contains("hidden") && !event.target.closest(".bell-wrap")) setNotificationsOpen(false);
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !$("notification-panel").classList.contains("hidden")) {
    setNotificationsOpen(false);
    $("notification-bell").focus();
  }
});
$("notification-read").addEventListener("click", async () => {
  await postJSON("/api/v1/notifications/read", {});
  loadNotifications();
});
schedulePoll(loadNotifications, 3000);
if (!IS_CLIENT) {
  schedulePoll(loadApprovals, 2000);
  loadRules();
}


</script>
</body>
</html>
"""


def _render(mode: str, title_suffix: str) -> Response:
    page = (
        _PAGE.replace("__MODE__", mode)
        .replace("__TITLE_SUFFIX__", title_suffix)
        .replace("__CREATE_ERROR_BUTTON__", '<button id="create-error" type="button" class="secondary">신규 오류 생성</button>' if mode == "admin" else "")
    )
    return Response(page, mimetype="text/html")


@web_blueprint.get(ADMIN_PAGE_PATH)
def admin() -> Response:
    """장애 시나리오 실행·수집/분석 로그까지 보이는 운영자(어드민) 화면.

    경로는 config.ADMIN_PAGE_PATH(환경변수 ADMIN_PAGE_PATH)로 정한다.
    """
    return _render("admin", " (Admin)")


@web_blueprint.get("/")
@web_blueprint.get("/client")
def client() -> Response:
    """오류 내용(원인·Runbook/리소스 가이드)만 보이는 클라이언트 화면.

    어드민에서 시나리오를 실행하면 latest-run 폴링으로 같은 장애를 따라간다.
    """
    return _render("client", "")

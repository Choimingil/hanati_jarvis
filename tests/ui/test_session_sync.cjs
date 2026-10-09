// Run with jsdom installed and JARVIS_TEST_PYTHON pointing to the test Python.
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const path = require('node:path');
const {JSDOM, VirtualConsole} = require('jsdom');
const html = JSON.parse(execFileSync(process.env.JARVIS_TEST_PYTHON || 'python', ['-c', `
import json
from flask import Flask
from routes.web_routes import web_blueprint
app = Flask(__name__)
app.register_blueprint(web_blueprint)
print(json.dumps({mode: app.test_client().get('/' + mode).get_data(as_text=True) for mode in ('admin', 'client')}))
`], {cwd: path.resolve(__dirname, '../..'), encoding: 'utf8'}));
const settle = () => new Promise(resolve => setImmediate(resolve));
const element = (w, id) => w.document.getElementById(id);
const target = {host:'orders-01', environment:'prod', service:'orders', instance:'orders-one'};
function server() {
  const rec = {incident_id:'INC-SHARED', incident_version:2, recommendation_id:'REC-SHARED', cause:'memory',
    runbooks:[{script_id:'restart_application',confidence:90}], targets:[target],
    actions:[{script_id:'restart_application',action_id:'ACTION-SHARED',targets:[target]}]};
  return {incident:{incident_id:'INC-SHARED',version:2,status:'ACTION_REQUIRED',service:'orders',environment:'prod',
    error_code:'MEMORY_LEAK',affected_hosts:['orders-01'],occurrence_count:1,
    first_seen:'2026-10-09T15:15:00Z',last_seen:'2026-10-09T15:15:00Z',latest_recommendation:rec},
    listMissing:false, listStale:null, execution:null, posts:[], reads:[]};
}
function processing(s) {
  const i=s.incident, completed=i.status==='RESOLVED', done=i.status==='MONITORING';
  const manual=i.manual_actions?.at(-1);
  return {state:completed?'completed':done?'action_completed':'open',confirmation:i.recovery_confirmation,
    completed_at:i.recovered_at,operator:manual?.operator||s.execution?.approved_by,
    method:manual?.method||s.execution?.script_id};
}
async function mount(mode, s) {
  const timers=[], errors=[], controls={failList:false, holdDetail:null};
  const vc=new VirtualConsole(); vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(html[mode], {url:'http://jarvis.test/'+mode,runScripts:'dangerously',pretendToBeVisual:true,virtualConsole:vc,
    beforeParse(w) {
      w.HTMLElement.prototype.scrollIntoView=function(){};
      w.setTimeout=(fn,ms)=>{timers.push({fn,ms});return timers.length;};
      w.fetch=async (url,options={})=>{
        let body, ok=true;
        if (!options.body) assert.equal(options.cache,'no-store');
        if (options.body) s.posts.push({url,body:JSON.parse(options.body)});
        s.reads.push(url);
        if (url==='/api/v1/operations/status') body={status:'ready',components:{},hosts:[]};
        else if(url==='/api/v1/log-generator/scenarios') body=[];
        else if(url==='/api/v1/log-generator/latest-run') body={status:'none'};
        else if(url.startsWith('/api/v1/log-generator/activity?')) body={};
        else if(url.startsWith('/api/v1/log-generator/latest-recommendation?'))
          body={status:'ready',recommendation:s.incident.latest_recommendation,processing:processing(s),decisions:[]};
        else if(url==='/api/v1/log-generator/incidents?minutes=10') {
          ok=!controls.failList;
          body={incidents:s.listMissing?[]:[s.listStale||s.incident],server_time:'2026-10-09T15:15:10Z'};
        } else if(url==='/api/v1/log-generator/incidents/INC-SHARED') {
          body={incident:s.incident,processing:processing(s),logs:[],logs_status:'ready',execution:s.execution,
            decisions:s.execution?[{...s.execution,decision:'approve'}]:[],executions_status:'ready',
            manual_action_available:!s.incident.latest_recommendation.targets.length && s.incident.status==='ACTION_REQUIRED'};
          body=JSON.parse(JSON.stringify(body));
          if(controls.holdDetail) await controls.holdDetail;
        } else if(url==='/api/v1/remediations/approve') {
          const input=JSON.parse(options.body);
          body={execution_id:'EXEC-SHARED',status:'success',returncode:0,stdout:'restarted'};
          s.execution={...input,execution_id:body.execution_id,script_id:'restart_application',result:body};
          s.incident={...s.incident,status:'MONITORING',version:3,recovery_confirmation:'pending_execution',last_execution:s.execution};
        } else if(url==='/api/v1/remediations/verify') {
          s.incident={...s.incident,status:'RESOLVED',version:4,recovery_confirmation:'business_probe',recovered_at:'2026-10-09T15:15:13Z'};
          body={recovered:true,incident:s.incident,processing:processing(s)};
        } else if(url==='/api/v1/remediations/manual') {
          const input=JSON.parse(options.body);
          s.incident={...s.incident,status:'RESOLVED',version:s.incident.version+1,recovery_confirmation:'operator_report',
            recovered_at:'2026-10-09T15:15:13Z',manual_actions:[{...input,registered_at:'2026-10-09T15:15:13Z'}]};
          body={incident:s.incident,status:'registered'};
        } else throw new Error('Unexpected API '+url);
        const snapshot=JSON.parse(JSON.stringify(body));
        return {ok,status:ok?200:503,json:async()=>snapshot};
      };
    }});
  await settle();
  return {dom,w:dom.window,timers,controls,errors};
}
async function open(m) {
  m.w.document.querySelector('.incident-detail').click(); await settle();
}
async function tickDetails(m) {
  const due=m.timers.filter(t=>t.ms===2000);
  assert.ok(due.length);
  m.timers.splice(0,m.timers.length,...m.timers.filter(t=>t.ms!==2000));
  await Promise.all(due.map(t=>t.fn())); await settle();
}
function completed(m) {
  assert.equal(element(m.w,'incident-detail-panel').classList.contains('hidden'),false);
  assert.equal(element(m.w,'incident-processing-title').textContent,'처리 완료');
  assert.equal(element(m.w,'verify-execution').classList.contains('hidden'),true);
  assert.equal(m.w.document.querySelector('.runbook .approve').disabled,true);
}
(async()=>{
  for(const [actorMode,observerMode] of [['admin','client'],['client','admin'],['admin','admin'],['client','client']]) {
    const s=server(), actor=await mount(actorMode,s), observer=await mount(observerMode,s);
    await open(actor);
    if(observerMode==='admin') {
      // Scenario results must start tracking the incident without a list click.
      const waiting=observer.w.waitForRecommendation('MEMORY_LEAK','2026-10-09T15:15:00Z');
      observer.timers.find(t=>t.ms===1500).fn(); await waiting;
      assert.equal(element(observer.w,'incident-detail-panel').classList.contains('hidden'),false);
    } else await open(observer);
    const card=actor.w.document.querySelector('.runbook'), select=card.querySelector('.target-select');
    select.value='0';select.dispatchEvent(new actor.w.Event('change'));card.querySelector('.approve').click();await settle();
    await tickDetails(observer);
    assert.equal(element(observer.w,'incident-processing-title').textContent,'조치 완료 · 복구 확인 대기');
    assert.equal(element(observer.w,'verify-execution').classList.contains('hidden'),false);
    // Recent-window expiry and list outage must not stop shared completion reads.
    s.listMissing=true;observer.controls.failList=true;
    element(actor.w,'verify-execution').click();await settle();
    await tickDetails(observer);completed(observer);
    assert.match(element(observer.w,'incident-processing-meta').textContent,/restart_application.*서비스 복구 검사/);
    // A stale search result must never downgrade a real-time completed detail.
    observer.controls.failList=false;s.listMissing=false;s.listStale={...s.incident,status:'ACTION_REQUIRED',version:2};
    await observer.w.loadIncidents();completed(observer);
    element(observer.w,'incident-detail-close').click();await tickDetails(observer);
    assert.equal(element(observer.w,'incident-detail-panel').classList.contains('hidden'),true);
    assert.deepEqual(actor.errors,[]);assert.deepEqual(observer.errors,[]);
    actor.dom.window.close();observer.dom.window.close();
  }
  // Manual completion from another session also closes its form and restores history.
  const s=server();s.incident.latest_recommendation.targets=[];s.incident.latest_recommendation.actions=[];
  const actor=await mount('admin',s), observer=await mount('client',s);
  await open(actor);await open(observer);
  for(const [id,value] of [['manual-method','설정 변경 후 주문 정상 확인'],['manual-operator','other-session']]) {
    element(actor.w,id).value=value;element(actor.w,id).dispatchEvent(new actor.w.Event('input'));
  }
  for(const id of ['manual-performed','manual-recovered']) {
    element(actor.w,id).checked=true;element(actor.w,id).dispatchEvent(new actor.w.Event('input'));
  }
  element(actor.w,'manual-form').dispatchEvent(new actor.w.Event('submit',{cancelable:true}));await settle();
  await tickDetails(observer);completed(observer);
  assert.equal(element(observer.w,'manual-form').classList.contains('hidden'),true);
  assert.match(element(observer.w,'manual-history').textContent,/other-session.*설정 변경 후 주문 정상 확인/s);
  assert.deepEqual(actor.errors,[]);assert.deepEqual(observer.errors,[]);
  actor.dom.window.close();observer.dom.window.close();
  // A delayed snapshot cannot undo newer local completion; concurrent polls share a read.
  const race=server(), view=await mount('client',race);await open(view);
  let release;view.controls.holdDetail=new Promise(resolve=>{release=resolve;});
  const reads=race.reads.length;
  const first=view.w.refreshSelectedIncident(), second=view.w.refreshSelectedIncident();
  assert.equal(first,second);assert.equal(race.reads.length,reads+1);
  race.incident={...race.incident,status:'RESOLVED',version:4};
  view.w.renderIncidentDetails(race.incident,processing(race));release();await first;
  assert.equal(element(view.w,'incident-processing-title').textContent,'처리 완료');
  view.controls.holdDetail=null;
  // Returning from a hidden tab fetches shared state immediately.
  race.incident={...race.incident,status:'REOPENED',version:5};
  view.w.document.dispatchEvent(new view.w.Event('visibilitychange'));await settle();
  assert.equal(element(view.w,'incident-processing').classList.contains('hidden'),true);
  assert.deepEqual(view.errors,[]);view.dom.window.close();
  console.log('Passed: four session pairs, scenario result tracking, execution/recovery sync, expired/failed/stale list, manual history, close, delayed read, coalescing, tab return and no-store reads.');
})().catch(error=>{console.error(error);process.exitCode=1;});

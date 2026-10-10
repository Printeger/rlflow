import test from 'node:test';
import assert from 'node:assert/strict';
import {checkFiniteAccounting,FiniteAccountingPanel} from '../rlflow/static/finite-accounting.mjs';
const scope={project:'p',mode:'fixture',epoch:'e'};
const dimensions=['model_sessions','model_input_tokens','model_output_tokens','gpu_device_seconds','experiment_starts','experiment_retries','wall_seconds'];
const row={limit:'9223372036854775807',consumed:'9007199254740993',reserved:'1',unknown_exposure:'1',available:'9214364837600034813',overrun:'0'};
function value(){return {schema_version:'1.1',project_id:'p',data_mode:'fixture',store_epoch:'e',as_of_state_version:8,execution_enabled:false,
  task_id:'task',reservation_id:'reservation',goal_ref:'goal',profile:'ORIGINAL_FINITE_ACCOUNTING',cross_database_atomic:false,goal_completed:false,
  budget:{profile:'ORIGINAL_GOAL_LEDGER_INT64_DECIMAL',observed_at:'2026-10-10T12:00:00.123456Z',entry_id:'budget_entry_'+'a'.repeat(64),entry_sha256:'sha256:'+'a'.repeat(64),recorded_state_version:8,reservation_recorded_state_version:7,reservation_status:'UNKNOWN',balances:Object.fromEntries(dimensions.map(n=>[n,{...row}])),actual_cost_status:'UNKNOWN',source_coverage:'ORIGINAL_EVENT_VERIFIED'},
  pool:{profile:'ORIGINAL_DURABLE_SHARED_POOL',pool_id:'pool_a',as_of_pool_version:10,observed_at:'2026-10-10T12:00:00Z',capacity:3,project_occupied:1,occupied:2,coverage:'ALL_REGISTERED_PROJECTS',execution_enabled:false,release_enabled:false,process_status:'NOT_OBSERVED'}};}
test('all int64 decimal values conserve exactly beyond JS safe integer; no fake zero/cost/current authority',()=>{
  const v=value();assert.equal(checkFiniteAccounting(v,scope),v);
  for(const change of [{project_id:'other'},{store_epoch:'other'},{data_mode:'live'},{cross_database_atomic:true},{goal_completed:true},{execution_enabled:true},{secret:'/private'}])assert.throws(()=>checkFiniteAccounting({...v,...change},scope));
  for(const change of [{actual_cost_status:'KNOWN'},{source_coverage:'HEAD_ONLY'},{recorded_state_version:9},{entry_sha256:'wrong'},{observed_at:'bad'}])assert.throws(()=>checkFiniteAccounting({...v,budget:{...v.budget,...change}},scope));
  for(const change of [{capacity:4},{project_occupied:4},{occupied:0},{occupied:null},{coverage:'CURRENT'},{release_enabled:true},{process_status:'KNOWN'},{pid:123}])assert.throws(()=>checkFiniteAccounting({...v,pool:{...v.pool,...change}},scope));
  assert.equal(checkFiniteAccounting({...v,pool:{...v.pool,occupied:null,as_of_pool_version:null,coverage:'PROJECT_ONLY'}},scope).pool.occupied,null);
  assert.throws(()=>checkFiniteAccounting({...v,pool:{...v.pool,occupied:null,coverage:'PROJECT_ONLY'}},scope));
  assert.throws(()=>checkFiniteAccounting({...v,pool:{...v.pool,coverage:'PROJECT_ONLY'}},scope));
  for(const change of [{available:'9214364837600034814'},{reserved:1},{reserved:'01'},{limit:'9223372036854775808'},{unknown_exposure:'2'},{overrun:'1'},{extra:'0'}]){
    assert.throws(()=>checkFiniteAccounting({...v,budget:{...v.budget,balances:{...v.budget.balances,model_sessions:{...row,...change}}}},scope));
  }
});
class Element{constructor(){this.textContent='';this.disabled=false;}addEventListener(){}}
function setup(handler){const nodes=new Map();globalThis.document={getElementById:id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);}};
  let context={...scope,version:8,authGeneration:1,session:{principal_id:'human'}},calls=[],jobs=new Map(),next=0;
  const panel=new FiniteAccountingPanel({context:()=>context,request:(...a)=>{calls.push(a);return handler(...a);},schedule:f=>{jobs.set(++next,f);return next;},cancel:id=>jobs.delete(id)});
  return {panel,calls,jobs,setContext:v=>context=v,context:()=>context};}
test('only GET, exact rendering and project-domain coalescing; no heartbeat/clock budget growth',async()=>{
  let current=value();const s=setup(async()=>current);await s.panel.load();assert.equal(s.calls.length,1);assert.equal(s.calls[0].length,1);
  assert.match(s.panel.$('detail').textContent,/9007199254740993/);assert.match(s.panel.$('note').textContent,/实际费用 UNKNOWN/);
  s.panel.connection('LIVE');s.panel.changed(8);s.panel.changed(8);assert.equal(s.jobs.size,0);
  s.panel.changed(9);s.panel.changed(9);assert.equal(s.jobs.size,1);current={...value(),as_of_state_version:9};
  const job=[...s.jobs.values()][0];s.jobs.clear();job();await new Promise(r=>setImmediate(r));assert.equal(s.calls.length,2);assert.equal(s.jobs.size,0);s.panel.clear();
});
test('bad source clears current numeric display to UNKNOWN, no retry loop or synthesized refund',async()=>{
  let broken=false;const s=setup(async()=>{if(broken)throw new Error('503');return value();});await s.panel.load();broken=true;await s.panel.load();
  assert.equal(s.panel.$('detail').textContent,'');assert.match(s.panel.$('note').textContent,/UNKNOWN.*不显示零/);s.panel.changed(20);s.panel.connection('LIVE');assert.equal(s.jobs.size,0);s.panel.clear();
});
test('held read cannot refill DOM after project/Auth/epoch/logout; new independent scope may read',async()=>{
  for(const drift of ['project','auth','epoch','logout']){
    let resolve;const s=setup(()=>new Promise(r=>resolve=r)),pending=s.panel.load();
    s.setContext(drift==='logout'?null:{...s.context(),...(drift==='project'?{project:'other'}:drift==='epoch'?{epoch:'other'}:{authGeneration:2})});s.panel.clear();
    resolve(value());await pending;assert.equal(s.panel.$('detail').textContent,'');assert.equal(s.panel.reading,false);assert.equal(s.jobs.size,0);
  }
});
test('independent Pool version and fixed original identity cannot regress while project version increases',async()=>{
  let v=value();const s=setup(async()=>v);await s.panel.load();
  v={...value(),as_of_state_version:9,pool:{...value().pool,as_of_pool_version:9}};await s.panel.load();assert.equal(s.panel.$('detail').textContent,'');assert.match(s.panel.$('note').textContent,/UNKNOWN/);s.panel.clear();
});
test('global to project-only hides counters, preserves prior visible highwater without displaying zero',async()=>{
  let v=value();const s=setup(async()=>v);await s.panel.load();
  v={...value(),pool:{...value().pool,coverage:'PROJECT_ONLY',occupied:null,as_of_pool_version:null}};await s.panel.load();
  assert.match(s.panel.$('note').textContent,/全池 未授权读取.*独立版本 未授权/);
  assert.equal(s.panel.value.pool.as_of_pool_version,null);assert.equal(s.panel.poolFloor,10);
  v={...value(),pool:{...value().pool,as_of_pool_version:9}};await s.panel.load();assert.equal(s.panel.$('detail').textContent,'');s.panel.clear();
});

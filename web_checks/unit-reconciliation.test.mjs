import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash,webcrypto} from 'node:crypto';
import {CpuUnitPanel,checkCpuUnitReceipt} from '../rlflow/static/cpu-unit-panel.mjs';
import {checkEngineeringUnitReceipt} from '../rlflow/static/engineering-unit-panel.mjs';
import {bindOriginalRun,checkUnitReconciliation} from '../rlflow/static/unit-reconciliation.mjs';
globalThis.crypto=webcrypto;
const sha=s=>createHash('sha256').update(s).digest('hex');
const scope={project:'p',mode:'fixture',epoch:'e',identity:'human',authGeneration:1,sessionKind:'human',roles:'operator'};
const spec=cpu=>({path:cpu?'cpu-unit':'engineering-unit',start:cpu?'START_FIXED_CPU':'START_FIXED_ENGINEERING',receipt:cpu?checkCpuUnitReceipt:checkEngineeringUnitReceipt});
function receipt(body,key){return {schema_version:'1.1',command_id:'fixture_command_'+sha(JSON.stringify(['p','fixture','e','human',key])),action:body.action,status:'ACCEPTED',accepted_state_version:body.expected_state_version===undefined?8:body.expected_state_version+1,request_hash:'sha256:'+sha(JSON.stringify(Object.fromEntries(Object.keys(body).sort().map(k=>[k,body[k]])))),actor_id:'human',task_id:body.task_id,recorded_phase:body.expected_state_version===undefined?'STOP_INTENT_ACCEPTED':'HANDOFF_UNKNOWN',execution_status:'UNKNOWN',native_execution_enabled:false,arbitrary_tree_stop:false,duplicate:false};}
async function witness(cpu=true){const s=spec(cpu),body={action:s.start,task_id:'task_a',expected_state_version:4},intent={body:JSON.stringify(body),key:'original_run'};return bindOriginalRun(scope,intent,receipt(body,intent.key),s);}
function recovered(w,cpu=true){return {schema_version:'1.0',profile:'ORIGINAL_UNIT_RECONCILIATION',original_acceptance:{...w.receipt,duplicate:true},result:{status:cpu?'EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW':'MACHINE_ACCEPTED_PENDING_REVIEW',lease_id:'lease_a',cancel_requested:false,goal_completed:false,independent_review_status:'NOT_PERFORMED',dispatch_enabled:false,execution_scope:cpu?'FIXED_CPU_PI_TRIAL_V1':'FIXED_ADD_PATCH_ONLY',cleanup_error:null},result_fact:{id:cpu?w.facts.decision:w.facts.acceptance,source_id:cpu?w.facts.decision:w.facts.output,sha256:'sha256:'+'a'.repeat(64),recorded_state_version:7},new_dispatch_enabled:false,automatic_effect_retry_enabled:false};}

test('original fixed ASCII ID and body digest bind both profiles; mismatch cannot mint a witness',async()=>{
  for(const cpu of [true,false]){
    const w=await witness(cpu);assert(Object.isFrozen(w) && Object.isFrozen(w.receipt) && Object.isFrozen(w.scope));
    for(const change of [{command_id:'fixture_command_wrong'},{request_hash:'sha256:'+'b'.repeat(64)}]){
      await assert.rejects(bindOriginalRun(scope,{body:w.body,key:w.key},{...w.receipt,...change},spec(cpu)));
    }
    await assert.rejects(bindOriginalRun({...scope,identity:'other'},{body:w.body,key:w.key},w.receipt,spec(cpu)));
    await assert.rejects(bindOriginalRun(scope,{body:w.body,key:'changed'},w.receipt,spec(cpu)));
  }
});
test('closed typed recovery rejects false authority, facts, versions and completion while preserving canceled/UNKNOWN',async()=>{
  for(const cpu of [true,false]){
    const w=await witness(cpu),s=spec(cpu),v=recovered(w,cpu);assert.equal(checkUnitReconciliation(v,w,s),v);
    for(const change of [{schema_version:'1.1'},{profile:'RUNNING'},{new_dispatch_enabled:true},{automatic_effect_retry_enabled:true},{private_token:'secret'},{result_fact:null},
      {original_acceptance:{...v.original_acceptance,command_id:'fixture_command_wrong'}},
      {original_acceptance:{...v.original_acceptance,request_hash:'sha256:'+'b'.repeat(64)}}])assert.throws(()=>checkUnitReconciliation({...v,...change},w,s));
    for(const change of [{status:'RUNNING'},{goal_completed:true},{dispatch_enabled:true},{independent_review_status:'PASSED'},
      {execution_scope:'NATIVE'},{lease_id:''},{cancel_requested:0},{cleanup_error:{}},{cleanup_error:'汉'.repeat(1400)},{private:1}])assert.throws(()=>checkUnitReconciliation({...v,result:{...v.result,...change}},w,s));
    for(const change of [{id:'wrong'},{source_id:'wrong'},{sha256:'a'.repeat(64)},{recorded_state_version:5},{recorded_state_version:NaN},{private:1}])assert.throws(()=>checkUnitReconciliation({...v,result_fact:{...v.result_fact,...change}},w,s));
    const captured=cpu?w.facts.assessment:w.facts.output;
    const canceled={...v,result:{...v.result,status:cpu?'EXPERIMENT_ASSESSED_CANCELLED':'OUTPUT_CAPTURED_CANCELLED',cancel_requested:true,cleanup_error:'Original cleanup UNKNOWN'},result_fact:{...v.result_fact,id:captured,source_id:captured}};
    assert.equal(checkUnitReconciliation(canceled,w,s),canceled);
    assert.throws(()=>checkUnitReconciliation({...canceled,result:{...canceled.result,cancel_requested:false}},w,s));
    for(const status of ['UNKNOWN_RESULT_UNAVAILABLE','UNKNOWN_CLEANUP_REQUIRED',...(cpu?[]:['UNKNOWN_NO_AUTOMATIC_EFFECT_RETRY'])]){
      const unknown={...v,result:{...v.result,status,cleanup_error:'Unproved cleanup'},result_fact:null};assert.equal(checkUnitReconciliation(unknown,w,s),unknown);
      assert.throws(()=>checkUnitReconciliation({...unknown,result_fact:v.result_fact},w,s));
    }
    for(const cleanup_error of [null,''])assert.throws(()=>checkUnitReconciliation({...v,result:{...v.result,status:'UNKNOWN_CLEANUP_REQUIRED',cleanup_error},result_fact:null},w,s));
    assert.throws(()=>checkUnitReconciliation({...v,result:{...v.result,status:'CANCELLED_SCOPE_STOPPED',cancel_requested:true,cleanup_error:'Unknown'},result_fact:null},w,s));
    const foreign=cpu?'cpu_assessment_':'candidate_output_result_';
    assert.throws(()=>checkUnitReconciliation({...v,result_fact:{...v.result_fact,source_id:foreign+'b'.repeat(64)}},w,s));
    assert.throws(()=>checkUnitReconciliation({...v,result_fact:{...v.result_fact,id:(cpu?foreign:'candidate_output_acceptance_')+'b'.repeat(64)}},w,s));
  }
});

const profile={schema_version:'1.1',project_id:'p',data_mode:'fixture',store_epoch:'e',as_of_state_version:4,execution_enabled:false,
  task:{id:'task_a',attempt_id:'attempt_a',reservation_id:'reservation_a',kind:'LOCAL_CPU_NUMERICAL_TRIAL',authorization:'LOCAL_CPU_TRIAL_ONLY',recorded_phase:'REGISTER_NO_HANDOFF',recorded_at_state_version:4,current_execution_status:'UNKNOWN',controls_available:false,source_coverage:'ORIGINAL_EVENT_VERIFIED',model_enabled:false,native_execution_enabled:false,candidate_write_enabled:false,delegation_enabled:false,actual_cost_status:'UNKNOWN',synthetic_tokens_settled:false,arbitrary_tree_stop:false,resource_release_status:'NOT_OBSERVED',recorded_wall_seconds:null},
  control_api_installed:true,original_owner_available:true,profile:'FIXED_CPU_PI_TRIAL_UNIT',last_sdk_status:null,cancel_requested:false,goal_completed:false,independent_review_status:'NOT_PERFORMED'};
class Element{constructor(){this.textContent='';this.hidden=false;this.disabled=false;}addEventListener(){}}
function setup(handler){const nodes=new Map();globalThis.document={getElementById:id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);}};
  let context={project:'p',mode:'fixture',epoch:'e',version:4,authGeneration:1,session:{principal_id:'human',kind:'human',roles:['operator'],csrf_token:'csrf'}},read=profile;
  const calls=[],panel=new CpuUnitPanel({context:()=>context,schedule:()=>1,cancel:()=>{},request:async(url,options)=>{calls.push({url,options});if(!options)return read;if(handler)return handler(url,options,panel);return receipt(JSON.parse(options.body),options.headers['Idempotency-Key']);}});
  return {panel,calls,context:()=>context,setContext:v=>context=v,setRead:v=>read=v};}

test('explicit recovery keeps original body/key after lost response; no automatic retry and no stale successful result',async()=>{
  let lose=false;const s=setup((url,o,p)=>{if(!url.endsWith('/reconcile'))return receipt(JSON.parse(o.body),o.headers['Idempotency-Key']);if(lose)throw new TypeError('Lost reply');return recovered(p.originalRun);});
  await s.panel.load();await s.panel.command('run');assert.equal(s.panel.run,null);assert(s.panel.originalRun);
  assert.equal(s.calls.filter(c=>c.options).length,1);await s.panel.load();assert.equal(s.calls.filter(c=>c.options).length,1);
  await s.panel.recover();assert.match(s.panel.$('reconcile-detail').textContent,/EXPERIMENT_MACHINE_VERIFIED/);
  lose=true;await s.panel.recover();assert.equal(s.panel.$('reconcile-detail').textContent,'');assert.equal(s.panel.recovery.status,'UNKNOWN');
  lose=false;await s.panel.recover();const writes=s.calls.filter(c=>c.options),start=writes[0],recovery=writes.slice(1);
  assert.equal(start.options.expectedStatus,202);assert.equal(recovery.length,3);
  for(const call of recovery){assert.equal(call.options.expectedStatus,200);assert.equal(call.options.body,start.options.body);assert.equal(call.options.headers['Idempotency-Key'],start.options.headers['Idempotency-Key']);assert.match(call.url,/fixture_command_[0-9a-f]{64}\/reconcile$/);}
  assert.match(s.panel.$('reconcile-note').textContent,/预算未读取/);s.panel.clear();
});
test('held recovery never disables independent STOP; viewer/closed methods cannot send',async()=>{
  let resolve;const s=setup((url,o,p)=>url.endsWith('/reconcile')?new Promise(r=>resolve=()=>r(recovered(p.originalRun))):receipt(JSON.parse(o.body),o.headers['Idempotency-Key']));
  await s.panel.load();await s.panel.command('run');const recovering=s.panel.recover();assert.equal(s.panel.$('stop').disabled,false);
  await s.panel.command('stop');assert.equal(s.panel.stop.acceptedStop,true);resolve();await recovering;
  s.setRead({...profile,original_owner_available:false});await s.panel.load();const before=s.calls.filter(c=>c.options).length;await s.panel.recover();assert.equal(s.calls.filter(c=>c.options).length,before);
  s.setContext({...s.context(),session:{...s.context().session,roles:['viewer']}});await s.panel.recover();assert.equal(s.panel.originalRun,null);assert.equal(s.panel.$('reconcile-detail').textContent,'');assert.equal(s.calls.filter(c=>c.options).length,before);s.panel.clear();
});
test('late recovery cannot refill DOM after project/Auth or same-scope task changes',async()=>{
  for(const drift of ['project','auth','task']){
    let release;const s=setup((url,o,p)=>{if(!url.endsWith('/reconcile'))return receipt(JSON.parse(o.body),o.headers['Idempotency-Key']);const response=recovered(p.originalRun);return new Promise(r=>release=()=>r(response));});
    await s.panel.load();await s.panel.command('run');const pending=s.panel.recover();
    if(drift==='task'){s.setRead({...profile,as_of_state_version:7,task:{...profile.task,id:'task_other'}});await s.panel.load();}
    else{s.setContext({...s.context(),...(drift==='project'?{project:'other'}:{authGeneration:2})});s.panel.buttons();}
    release();await pending;assert.equal(s.panel.originalRun,null);assert.equal(s.panel.$('reconcile-detail').textContent,'');assert.equal(s.panel.$('run-receipt').textContent,'');s.panel.clear();
  }
});
test('late actual crypto cannot establish a Run witness after Auth or task changes',async()=>{
  for(const drift of ['auth','task']){
    const releases=[];globalThis.crypto={randomUUID:()=>webcrypto.randomUUID(),subtle:{digest:async(...a)=>{const value=await webcrypto.subtle.digest(...a);await new Promise(r=>releases.push(r));return value;}}};
    const s=setup();await s.panel.load();const pending=s.panel.command('run');
    while(releases.length<2)await new Promise(r=>setImmediate(r));
    if(drift==='task'){s.setRead({...profile,as_of_state_version:7,task:{...profile.task,id:'task_other'}});await s.panel.load();}
    else{s.setContext({...s.context(),authGeneration:2});s.panel.buttons();}
    // Hold the first real digests only; later fixed-ID derivations still run
    // native crypto and must reach the same final scope fence.
    globalThis.crypto=webcrypto;releases.forEach(r=>r());await pending;assert.equal(s.panel.originalRun,null);assert.equal(s.panel.$('run-receipt').textContent,'');s.panel.clear();
  }
});

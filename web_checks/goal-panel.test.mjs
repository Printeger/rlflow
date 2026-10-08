import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {GoalPanel} from '../rlflow/static/goal-panel.mjs';
globalThis.crypto=webcrypto;
const hash='sha256:'+'a'.repeat(64);
const item={goal_ref:'goal_a',contract_revision:1,contract_hash:hash,source_coverage:'HEAD_ONLY',execution_enabled:false,authority:null};
const proposal={schema_version:'1.1',project_id:'p',data_mode:'fixture',goal_id:'g',contract_version:1,registry_bindings:{tool_registry_hash:hash}};
const review=()=>({schema_version:'1.1',project_id:'p',data_mode:'fixture',store_epoch:'e',as_of_state_version:1,execution_enabled:false,goal_ref:'goal_a',contract:{id:'g',version:1,hash,proposal:structuredClone(proposal),state:'DRAFT',approval_id:null,outcome:null},changes:[],submitted_by:{id:'human',kind:'human'},submitted_at:'2026-10-09T00:00:00Z',previous_hash:null,source_coverage:'ORIGINAL_EVENT_VERIFIED',submitted_state_version:1,authority:null});
const view=()=>({proposal:structuredClone(proposal),changes:[],binding:{state:'NOT_EXECUTABLE',project_id:'p',data_mode:'fixture',proposal_hash:hash,config_hash:hash,scope_hash:hash,registry_bindings:structuredClone(proposal.registry_bindings)},confirmation:{id:'nonce',goal_id:'g',store_epoch:'e',expected_version:1,expected_revision:1,expected_authority_revision:0,proposal_hash:hash,scope_hash:hash,config_hash:hash,ttl_seconds:60,view_hash:hash},execution_status:'LEASE_VALIDATION_PENDING',execution_enabled:false,limitations:['ACTUAL_DATA_BYTES_NOT_VERIFIED','ACTUAL_OS_AND_RESOURCE_ENFORCEMENT_NOT_VERIFIED']});
class Element {
  constructor(){this.textContent='';this.value='';this.hidden=false;this.checked=false;this.dataset={};this.children=[];}
  addEventListener(){}
  replaceChildren(...nodes){this.children=nodes;}
  append(node){this.children.push(node);}
}
function setup(request) {
  const elements=new Map();globalThis.document={getElementById:id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},createElement:()=>new Element()};
  let context={project:'p',mode:'fixture',epoch:'e',version:1,authGeneration:1,session:{principal_id:'human',kind:'human',roles:['operator','approver'],csrf_token:'csrf'}},expired=0,now=0;
  const panel=new GoalPanel({context:()=>context,request,onExpired:()=>expired++,now:()=>now});panel.$('goal-ttl').value='60';
  return {panel,elements,context:()=>context,setContext:v=>context=v,expired:()=>expired,setNow:v=>now=v};
}
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
test('late private review cannot repopulate cleared identity/project/epoch',async()=>{
  for(const change of ['identity','project','epoch']){
    const d=deferred(),s=setup(()=>d.promise),waiting=s.panel.open(item);
    const c=s.context();s.setContext({...c,...(change==='identity'?{authGeneration:2,session:{...c.session,principal_id:'other'}}:{[change]: 'other'})});s.panel.clear();
    d.resolve(review());await waiting;assert.equal(s.panel.review,null);assert.equal(s.panel.$('goal-review').textContent,'');
  }
});
test('editing/refresh and elapsed request time invalidate delayed nonce',async()=>{
  for(const change of ['edit','refresh','deadline','new-version']){
    const d=deferred(),s=setup(()=>d.promise);s.panel.review=review();const waiting=s.panel.prepare();
    if(change==='edit')s.panel.clearConfirmation();if(change==='refresh')s.panel.clearPrivate();
    if(change==='deadline')s.setNow(110000);if(change==='new-version')s.setContext({...s.context(),version:2});
    d.resolve(view());await waiting;assert.equal(s.panel.confirmation,null);assert.equal(s.panel.$('goal-confirmation').textContent,'');
  }
});
test('401 during private read clears editor/review/nonce and calls authentication boundary',async()=>{
  const s=setup(async()=>{throw Object.assign(new Error('expired'),{status:401});});s.panel.$('goal-json').value='PRIVATE';s.panel.review=review();
  await s.panel.open(item);assert.equal(s.expired(),1);assert.equal(s.panel.review,null);assert.equal(s.panel.$('goal-json').value,'');
});
test('network uncertainty requires manual identical retry, 409 stops and never auto-replays',async()=>{
  const calls=[],s=setup(async(url,options)=>{calls.push({url,options});throw Object.assign(new Error('lost'),calls.length===2?{status:409}:{});});
  s.panel.enabled=true;s.panel.$('goal-json').value=JSON.stringify(proposal);s.panel.submit();
  await new Promise(r=>setImmediate(r));assert.equal(calls.length,1);assert.equal(s.panel.pending.status,'UNKNOWN');
  s.panel.$('goal-json').value='changed';await s.panel.send();assert.equal(calls.length,2);
  assert.equal(calls[0].options.body,calls[1].options.body);assert.equal(calls[0].options.headers['Idempotency-Key'],calls[1].options.headers['Idempotency-Key']);
  assert.equal(s.panel.pending,null);assert.match(s.panel.$('goal-note').textContent,/未自动重发/);
});
test('late POST success after scope switch cannot render receipt or launch another request',async()=>{
  const d=deferred(),calls=[],s=setup((url,options)=>{calls.push({url,options});return d.promise;});
  s.panel.enabled=true;s.panel.$('goal-json').value=JSON.stringify(proposal);s.panel.submit();
  s.panel.clear();s.setContext({...s.context(),project:'other'});
  d.resolve({schema_version:'1.1',command_id:'control_one',action:'submit_goal',status:'SUCCEEDED',accepted_state_version:2,duplicate:false,
    result:{goal_id:'g',state:'DRAFT',proposal_hash:hash,contract_version:1,execution_enabled:false,as_of_state_version:2}});
  await new Promise(r=>setImmediate(r));assert.equal(calls.length,1);assert.equal(s.panel.$('goal-receipt').textContent,'');assert.equal(s.panel.pending,null);
});
test('heartbeat does not renew nonce; newer version clears it',async()=>{
  const s=setup(async()=>view());s.panel.review=review();await s.panel.prepare();assert.ok(s.panel.confirmation);
  s.panel.changed(1);assert.ok(s.panel.confirmation);s.panel.changed(2);assert.equal(s.panel.confirmation,null);
  assert.equal(s.panel.$('goal-consent').checked,false);
});
test('ambiguous or rounded pasted budget/tool declarations never cause a POST',()=>{
  const calls=[],s=setup(async(...args)=>calls.push(args));s.panel.enabled=true;
  for(const suffix of ['"allowed_tools":[],"allowed_tools":["hidden"]','"budget":{"model_input_tokens":9007199254740993}',
    '"budget":{"wall_seconds":1e309}','"budget":{},"bu\\u0064get":{"wall_seconds":99}']){
    s.panel.$('goal-json').value=JSON.stringify(proposal).slice(0,-1)+','+suffix+'}';s.panel.submit();
    assert.equal(calls.length,0);assert.equal(s.panel.pending,null);assert.match(s.panel.$('goal-note').textContent,/未提交/);
  }
});

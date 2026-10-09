import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {FixturePanel} from '../rlflow/static/fixture-panel.mjs';
import {checkFixturePage,checkFixtureDetail,checkFixtureReceipt} from '../rlflow/static/fixture-view.mjs';
globalThis.crypto=webcrypto;
const meta={schema_version:'1.1',project_id:'p',data_mode:'fixture',store_epoch:'e',as_of_state_version:4,execution_enabled:false};
const task={id:'task_a',attempt_id:'attempt_a',reservation_id:'reservation_a',kind:'PROTOCOL_CONFORMANCE',authorization:'LOCAL_PROTOCOL_ONLY',recorded_phase:'REGISTER_NO_HANDOFF',recorded_at_state_version:4,current_execution_status:'UNKNOWN',controls_available:false,source_coverage:'ORIGINAL_EVENT_VERIFIED',model_enabled:false,native_execution_enabled:false,candidate_write_enabled:false,delegation_enabled:false,actual_cost_status:'UNKNOWN',synthetic_tokens_settled:false,arbitrary_tree_stop:false,resource_release_status:'NOT_OBSERVED',recorded_wall_seconds:null};
const profile={...meta,control_api_installed:true,original_owner_available:true,profile:'FIXED_CPU_SINGLE_PARTICIPANT',native_execution_enabled:false,arbitrary_tree_stop:false};
class Element{constructor(){this.textContent='';this.children=[];this.disabled=false;this.hidden=false;}addEventListener(){}replaceChildren(...nodes){this.children=nodes;}append(n){this.children.push(n);}}
function setup(request){const elements=new Map();globalThis.document={getElementById:id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},createElement:()=>new Element()};let context={project:'p',mode:'fixture',epoch:'e',version:4,authGeneration:1,session:{principal_id:'human',kind:'human',roles:['operator'],csrf_token:'csrf'}};const panel=new FixturePanel({context:()=>context,request});return {panel,context:()=>context,setContext:v=>context=v};}
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const receipt=(body)=>({schema_version:'1.1',command_id:'fixture_command_a',action:body.action,status:'ACCEPTED',accepted_state_version:body.expected_state_version+1,request_hash:'sha256:'+'a'.repeat(64),actor_id:'human',task_id:body.task_id,recorded_phase:body.action==='START_FIXED_CPU'?'HANDOFF_UNKNOWN':'STOP_REQUESTED',execution_status:'UNKNOWN',native_execution_enabled:false,arbitrary_tree_stop:false,duplicate:false});
test('sparse scanned page may advance; closed unsafe/wrong scope/execution claims rejected',()=>{
  const s={project:'p',mode:'fixture',epoch:'e'};
  assert.equal(checkFixturePage({...meta,items:[],next_after:'reservation_z'},s).items.length,0);
  for(const changed of [{store_epoch:'other'},{as_of_state_version:2**53},{items:[{...task,controls_available:true}]},{items:[{...task,resource_release_status:'FREE'}]},{extra:'secret'}])assert.throws(()=>checkFixturePage({...meta,items:[task],next_after:null,...changed},s));
  assert.throws(()=>checkFixtureDetail({...meta,task:{...task,attempt_id:'other'}},s,task));
  const body={action:'START_FIXED_CPU',task_id:task.id,expected_state_version:4};assert.throws(()=>checkFixtureReceipt({...receipt(body),execution_status:'RUNNING'},body,'human'));
});
test('readonly history survives absent control discovery; viewer/dead owner never enables writes',async()=>{
  for(const kind of ['readonly','viewer','dead']){
    const s=setup(async url=>{if(url.endsWith('/fixture-runtime-profile')){if(kind==='readonly')throw Object.assign(new Error('absent'),{status:404});return {...profile,original_owner_available:kind!=='dead'};}return url.includes('?')?{...meta,items:[task],next_after:null}:{...meta,task};});
    if(kind==='viewer')s.setContext({...s.context(),session:{...s.context().session,roles:['viewer']}});
    await s.panel.load();await s.panel.open(task);assert.ok(s.panel.detail);assert.equal(s.panel.$('fixture-start').disabled,true);assert.equal(s.panel.$('fixture-stop').disabled,true);
  }
});
test('late detail from prior task/scope cannot enable actions or repopulate cleared DOM',async()=>{
  for(const change of ['task','identity','project','epoch']){
    const d=deferred(),s=setup(()=>d.promise);s.panel.profile=profile;const wait=s.panel.open(task);
    if(change==='task'){s.panel.open({...task,id:'other'});}else{s.setContext({...s.context(),...(change==='identity'?{authGeneration:2,session:{...s.context().session,principal_id:'other'}}:{[change]:'other'})});s.panel.clear();}
    d.resolve({...meta,task});await wait;assert.equal(s.panel.detail,null);assert.equal(s.panel.$('fixture-detail').textContent,'');assert.equal(s.panel.$('fixture-start').disabled,true);
  }
});
test('uncertain command is manual original-body/key only; conflict never rebases or auto replays',async()=>{
  const calls=[],s=setup(async(url,options)=>{calls.push({url,options});throw Object.assign(new Error('lost'),calls.length===2?{status:409}:{});});
  s.panel.profile=profile;s.panel.detail={...meta,task};s.panel.command('START_FIXED_CPU');await new Promise(r=>setImmediate(r));
  assert.equal(calls.length,1);assert.equal(s.panel.pending.status,'UNKNOWN');assert.equal(s.panel.$('fixture-stop').disabled,true);
  await s.panel.send();assert.equal(calls.length,2);assert.equal(calls[0].options.body,calls[1].options.body);assert.equal(calls[0].options.headers['Idempotency-Key'],calls[1].options.headers['Idempotency-Key']);assert.equal(s.panel.pending,null);assert.match(s.panel.$('fixture-note').textContent,/未自动重发/);
});
test('late accepted command after logout never writes receipt or issues follow-up read',async()=>{
  const d=deferred(),calls=[],s=setup((...args)=>{calls.push(args);return d.promise;});s.panel.profile=profile;s.panel.detail={...meta,task};s.panel.command('STOP_FIXED_SCOPE');const body=JSON.parse(calls[0][1].body);s.panel.clear();s.setContext(null);d.resolve(receipt(body));await new Promise(r=>setImmediate(r));assert.equal(calls.length,1);assert.equal(s.panel.$('fixture-receipt').textContent,'');
});
test('held POST cannot be invalidated by refresh/task selection; UNKNOWN remains recoverable',async()=>{
  const d=deferred(),calls=[],s=setup((...args)=>{calls.push(args);return d.promise;});s.panel.profile=profile;s.panel.detail={...meta,task};s.panel.command('START_FIXED_CPU');
  const serial=s.panel.serial;await s.panel.load();await s.panel.open({...task,id:'other'});assert.equal(s.panel.serial,serial);assert.equal(calls.length,1);assert.equal(s.panel.$('fixture-refresh').disabled,true);
  d.resolve({bad:'receipt'});await new Promise(r=>setImmediate(r));assert.equal(s.panel.pending.status,'UNKNOWN');assert.equal(s.panel.$('fixture-retry').hidden,false);assert.equal(s.panel.$('fixture-refresh').disabled,false);
});
test('STOP ACCEPTED retains immutable manual cleanup through STOP_REQUESTED and terminal, never auto retries',async()=>{
  for(const phase of ['STOP_REQUESTED','FIXTURE_SCOPE_STOPPED']){
    const calls=[],s=setup(async(url,options)=>{calls.push({url,options});if(options)return receipt(JSON.parse(options.body));if(url.endsWith('/fixture-runtime-profile'))return profile;return {...meta,as_of_state_version:6,items:[{...task,recorded_phase:phase,recorded_at_state_version:6,recorded_wall_seconds:phase==='FIXTURE_SCOPE_STOPPED'?2:null}],next_after:null};});
    s.panel.profile=profile;s.panel.detail={...meta,task};s.panel.command('STOP_FIXED_SCOPE');await new Promise(r=>setImmediate(r));
    assert.equal(s.panel.pending.status,'UNKNOWN');assert.equal(s.panel.pending.acceptedStop,true);assert.equal(calls.filter(c=>c.options).length,1);assert.match(s.panel.$('fixture-retry').textContent,/继续原 STOP/);
    await s.panel.send();const writes=calls.filter(c=>c.options);assert.equal(writes.length,2);assert.equal(writes[0].options.body,writes[1].options.body);assert.equal(writes[0].options.headers['Idempotency-Key'],writes[1].options.headers['Idempotency-Key']);assert.equal(s.panel.pending.status,'UNKNOWN');
  }
});

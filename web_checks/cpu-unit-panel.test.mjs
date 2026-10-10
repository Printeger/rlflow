import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto,createHash} from 'node:crypto';
import {CpuUnitPanel,checkCpuUnit,checkCpuUnitReceipt} from '../rlflow/static/cpu-unit-panel.mjs';
globalThis.crypto=webcrypto;
const meta={schema_version:'1.1',project_id:'p',data_mode:'fixture',store_epoch:'e',as_of_state_version:4,execution_enabled:false};
const task={id:'task_a',attempt_id:'attempt_a',reservation_id:'reservation_a',kind:'LOCAL_CPU_NUMERICAL_TRIAL',authorization:'LOCAL_CPU_TRIAL_ONLY',recorded_phase:'REGISTER_NO_HANDOFF',recorded_at_state_version:4,current_execution_status:'UNKNOWN',controls_available:false,source_coverage:'ORIGINAL_EVENT_VERIFIED',model_enabled:false,native_execution_enabled:false,candidate_write_enabled:false,delegation_enabled:false,actual_cost_status:'UNKNOWN',synthetic_tokens_settled:false,arbitrary_tree_stop:false,resource_release_status:'NOT_OBSERVED',recorded_wall_seconds:null};
const profile={...meta,task,control_api_installed:true,original_owner_available:true,profile:'FIXED_CPU_PI_TRIAL_UNIT',last_sdk_status:null,cancel_requested:false,goal_completed:false,independent_review_status:'NOT_PERFORMED'};
class Element{constructor(){this.textContent='';this.disabled=false;this.hidden=false;}addEventListener(){}}
const tick=()=>new Promise(r=>setImmediate(r));
function setup(request){const nodes=new Map();globalThis.document={getElementById:id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);}};let context={project:'p',mode:'fixture',epoch:'e',version:4,authGeneration:1,session:{principal_id:'human',kind:'human',roles:['operator'],csrf_token:'csrf'}};const jobs=new Map();let next=0;const panel=new CpuUnitPanel({context:()=>context,request,schedule:f=>{jobs.set(++next,f);return next;},cancel:id=>jobs.delete(id)});return {panel,jobs,setContext:v=>context=v,context:()=>context};}
const sha=raw=>createHash('sha256').update(raw).digest('hex');
const receipt=(body,key='node')=>({schema_version:'1.1',command_id:'fixture_command_'+sha(JSON.stringify(['p','fixture','e','human',key])),action:body.action,status:'ACCEPTED',accepted_state_version:body.action==='START_FIXED_CPU'?body.expected_state_version+1:17,request_hash:'sha256:'+sha(JSON.stringify(Object.fromEntries(Object.keys(body).sort().map(k=>[k,body[k]])))),actor_id:'human',task_id:body.task_id,recorded_phase:body.action==='START_FIXED_CPU'?'HANDOFF_UNKNOWN':'STOP_INTENT_ACCEPTED',execution_status:'UNKNOWN',native_execution_enabled:false,arbitrary_tree_stop:false,duplicate:false});
test('closed CPU source refuses false current/FREE/Review and wrong identity',()=>{
  const s={project:'p',mode:'fixture',epoch:'e'};assert.equal(checkCpuUnit(profile,s),profile);
  for(const v of [{goal_completed:true},{store_epoch:'other'},{independent_review_status:'PASSED'},{last_sdk_status:'RUNNING'},{task:{...task,resource_release_status:'FREE'}},{private_token:'secret'}])assert.throws(()=>checkCpuUnit({...profile,...v},s));
  const body={action:'CANCEL_FIXED_CPU_TRIAL',task_id:task.id};assert.equal(checkCpuUnitReceipt(receipt(body),body,'human').accepted_state_version,17);
  assert.throws(()=>checkCpuUnitReceipt({...receipt(body),execution_status:'STOPPED'},body,'human'));
});
test('held RUN does not block emergency STOP; separate immutable intents and late logout replies',async()=>{
  const calls=[],resolves=[];const s=setup((url,options)=>{calls.push({url,options});if(!options)return Promise.resolve(profile);return new Promise(r=>resolves.push(r));});
  await s.panel.load();s.panel.command('run');assert.equal(s.panel.run.status,'IN_FLIGHT');assert.equal(s.panel.$('stop').disabled,false);
  s.setContext({...s.context(),version:9});s.panel.changed(9);s.panel.command('stop');assert.equal(calls.filter(c=>c.options).length,2);
  const writes=calls.filter(c=>c.options),stopBody=JSON.parse(writes[1].options.body);assert.equal('expected_state_version' in stopBody,false);assert.notEqual(writes[0].options.headers['Idempotency-Key'],writes[1].options.headers['Idempotency-Key']);
  s.panel.clear();s.setContext(null);resolves[0](receipt(JSON.parse(writes[0].options.body)));resolves[1](receipt(stopBody));await tick();
  assert.equal(s.panel.$('run-receipt').textContent,'');assert.equal(s.panel.$('stop-receipt').textContent,'');assert.equal(calls.length,3);
});
test('UNKNOWN Run and accepted STOP are manual original body/key only; refresh never dispatches',async()=>{
  const calls=[];let lose=true;const s=setup(async(url,options)=>{calls.push({url,options});if(!options)return profile;if(lose)throw new TypeError('Failed to fetch');return receipt(JSON.parse(options.body),options.headers['Idempotency-Key']);});
  await s.panel.load();s.panel.command('run');await tick();assert.equal(s.panel.run.status,'UNKNOWN');assert.equal(s.panel.$('stop').disabled,false);
  lose=false;await s.panel.send('run');s.panel.command('stop');await tick();assert.equal(s.panel.stop.status,'UNKNOWN');assert.equal(s.panel.stop.acceptedStop,true);await s.panel.send('stop');
  const writes=calls.filter(c=>c.options);assert.equal(writes.length,4);for(const [a,b] of [[writes[0],writes[1]],[writes[2],writes[3]]]){assert.equal(a.options.body,b.options.body);assert.equal(a.options.headers['Idempotency-Key'],b.options.headers['Idempotency-Key']);}
  s.panel.clear();
});
test('SSE floor coalesces readonly refresh including already updated context; failure no loop',async()=>{
  let fail=false,version=4;const calls=[];const s=setup(async url=>{calls.push(url);if(fail)throw new Error('source');return {...profile,as_of_state_version:version};});
  await s.panel.load();s.panel.connection('LIVE');s.setContext({...s.context(),version:7});s.panel.changed(7);s.panel.changed(7);assert.equal(s.jobs.size,1);assert.equal(s.panel.$('run').disabled,true);assert.equal(s.panel.$('stop').disabled,false);
  fail=true;const fn=[...s.jobs.values()][0];s.jobs.clear();fn();await tick();assert.equal(s.panel.blocked,true);assert.equal(s.jobs.size,0);s.panel.connection('LIVE');assert.equal(s.jobs.size,0);
  version=7;fail=false;await s.panel.load();assert.equal(s.panel.profile.as_of_state_version,7);s.panel.clear();assert.equal(s.jobs.size,0);
});
test('viewer or closed original never enables commands',async()=>{
  for(const mode of ['viewer','closed']){const s=setup(async()=>({...profile,original_owner_available:mode!=='closed'}));if(mode==='viewer')s.setContext({...s.context(),session:{...s.context().session,roles:['viewer']}});await s.panel.load();assert.equal(s.panel.$('run').disabled,true);assert.equal(s.panel.$('stop').disabled,true);s.panel.clear();}
});
test('accepted Run raises floor before older held GET settles while SSE offline',async()=>{
  let resolveRead;const s=setup((url,options)=>options?Promise.resolve(receipt(JSON.parse(options.body),options.headers['Idempotency-Key'])):new Promise(r=>resolveRead=r));
  s.panel.profile=profile;
  // Original acceptance now additionally proves the command ID/body digest.
  // Await that actual crypto operation, not an arbitrary one-loop delay.
  const {PendingCommand}=await import('../rlflow/static/goal-view.mjs');
  s.panel.run=new PendingCommand(s.panel.scope(),{action:'START_FIXED_CPU',task_id:task.id,expected_state_version:4},'node_run');
  const sending=s.panel.send('run'),wait=s.panel.load();await sending;
  assert.equal(s.panel.run,null);assert.equal(s.panel.floor,5);resolveRead(profile);await wait;
  assert.equal(s.panel.$('run').disabled,true);assert.equal(s.panel.$('stop').disabled,false);assert.equal(s.jobs.size,0);s.panel.clear();
});

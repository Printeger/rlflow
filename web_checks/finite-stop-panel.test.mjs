import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto,createHash} from 'node:crypto';
import {FiniteStopPanel,checkFiniteScope,checkFiniteResult} from '../rlflow/static/finite-stop-panel.mjs';
globalThis.crypto=webcrypto;
const profile={schema_version:'1.1',profile:'ORIGINAL_FIXED_BOUND_UNITS_ONLY',scope_sha256:'sha256:'+'a'.repeat(64),data_mode:'fixture',execution_enabled:false,original_owner_available:true,stop_enabled:true,items:[{project_id:'p',store_epoch:'e',task_id:'t',stop_action:'CANCEL_FIXED_CPU_TRIAL'},{project_id:'q',store_epoch:'f',task_id:'u',stop_action:'CANCEL_FIXED_ENGINEERING'}],goal_completed:false,independent_review_status:'NOT_PERFORMED'};
const commandId=key=>'finite_stop_'+createHash('sha256').update(JSON.stringify([profile.scope_sha256,'human',key])).digest('hex');
function result(key,partial=false){return {schema_version:'1.1',command_id:commandId(key),action:'CANCEL_ORIGINAL_FINITE_UNITS',duplicate:false,status:partial?'PARTIAL_OR_UNKNOWN':'ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN',scope:profile.profile,durable_aggregate_receipt:false,cleanup_resume:false,items:profile.items.map((p,i)=>({...p,stop_action:undefined,intent:{schema_version:'1.1',command_id:'fixture_command_a',action:p.stop_action,status:'ACCEPTED',accepted_state_version:17,request_hash:'sha256:'+'b'.repeat(64),actor_id:'human',task_id:p.task_id,recorded_phase:'STOP_INTENT_ACCEPTED',execution_status:'UNKNOWN',native_execution_enabled:false,arbitrary_tree_stop:false,duplicate:false},intent_status:'ACCEPTED',cleanup_status:partial&&i===1?'UNKNOWN':'ORIGINAL_SCOPE_STOPPED',post_cleanup_status:'RETURNED',error_type:null,goal_completed:false,independent_review_status:'NOT_PERFORMED'})).map(({stop_action,...r})=>r),goal_completed:false,independent_review_status:'NOT_PERFORMED'};}
class Element{constructor(){this.textContent='';this.hidden=false;this.disabled=false;}addEventListener(){}}
function setup(request){const nodes=new Map();globalThis.document={getElementById:id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);}};let context={project:'p',epoch:'e',mode:'fixture',authGeneration:1,session:{principal_id:'human',kind:'human',roles:['operator'],csrf_token:'csrf'}};const panel=new FiniteStopPanel({context:()=>context,request});return {panel,setContext:c=>context=c,context:()=>context};}
const tick=()=>new Promise(r=>setTimeout(r,15));
test('closed whole-scope contracts refuse wrong target, fake completion and durable global receipt',()=>{
  assert.equal(checkFiniteScope(profile),profile);const good=result('key');assert.equal(checkFiniteResult(good,profile,'human',commandId('key')),good);
  for(const patch of [{goal_completed:true},{durable_aggregate_receipt:true},{status:'PARTIAL_OR_UNKNOWN'},{items:[good.items[1],good.items[0]]},{items:[good.items[0]]}])assert.throws(()=>checkFiniteResult({...good,...patch},profile,'human',commandId('key')));
  for(const patch of [{execution_enabled:true},{items:[profile.items[1],profile.items[0]]},{original_owner_available:false}])assert.throws(()=>checkFiniteScope({...profile,...patch}));
});
test('no automatic POST; UNKNOWN manual same-key retry; explicit partial cleanup resume',async()=>{
  const calls=[];let lost=true;const s=setup(async(url,options)=>{if(!options)return profile;calls.push({url,options});if(lost)throw Error('lost reply');return result(options.headers['Idempotency-Key'],!url.includes('?'));});
  await s.panel.load();assert.equal(calls.length,0);s.panel.command();await tick();assert.equal(calls.length,1);assert.equal(s.panel.$('retry').hidden,false);
  lost=false;await s.panel.send(false);assert.equal(s.panel.result.status,'PARTIAL_OR_UNKNOWN');assert.equal(s.panel.$('resume').hidden,false);await s.panel.send(true);
  assert.equal(calls.length,3);assert.match(calls[2].url,/resume_cleanup=1$/);for(const c of calls){assert.equal(c.options.body,calls[0].options.body);assert.equal(c.options.headers['Idempotency-Key'],calls[0].options.headers['Idempotency-Key']);}
  assert.equal(s.panel.result.status,'ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN');assert.equal(s.panel.$('resume').hidden,true);
});
test('held reply cannot repopulate private DOM after project/auth clear; viewer cannot STOP',async()=>{
  let finish;const s=setup(async(url,options)=>options?new Promise(r=>finish=()=>r(result(options.headers['Idempotency-Key']))):profile);
  await s.panel.load();s.panel.command();await tick();assert.equal(s.panel.sending,true);s.panel.clear();s.setContext({...s.context(),project:'q',epoch:'f',authGeneration:2});finish();await tick();assert.equal(s.panel.$('receipt').textContent,'');assert.equal(s.panel.intent,null);
  s.setContext({...s.context(),session:{...s.context().session,roles:['viewer']}});await s.panel.load();assert.equal(s.panel.$('stop').disabled,true);s.panel.command();assert.equal(s.panel.intent,null);
});
test('lost explicit resume reply exposes only receipt retry until fresh PARTIAL result',async()=>{
  const calls=[];const s=setup(async(url,options)=>{if(!options)return profile;calls.push({url,options});if(url.includes('?'))throw Error('lost resume reply');return result(options.headers['Idempotency-Key'],true);});
  await s.panel.load();s.panel.command();await tick();await s.panel.send(true);assert.equal(s.panel.result,null);assert.equal(s.panel.$('retry').hidden,false);assert.equal(s.panel.$('resume').hidden,true);assert.equal(s.panel.$('receipt').textContent,'');
  await s.panel.send(false);assert.equal(calls[2].url,'/api/v1/finite-host/commands');assert.equal(calls[2].options.headers['Idempotency-Key'],calls[1].options.headers['Idempotency-Key']);assert.equal(calls[2].options.body,calls[1].options.body);assert.equal(s.panel.$('resume').hidden,false);
});

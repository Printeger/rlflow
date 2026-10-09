import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {EngineeringUnitPanel,checkEngineeringUnit,checkEngineeringUnitReceipt} from '../rlflow/static/engineering-unit-panel.mjs';
globalThis.crypto=webcrypto;
const meta={schema_version:'1.1',project_id:'p',data_mode:'fixture',store_epoch:'e',as_of_state_version:4,execution_enabled:false};
const task={id:'task_a',attempt_id:'attempt_a',reservation_id:'reservation_a',kind:'LOCAL_CPU_PATCH_PROPOSAL',authorization:'FIXED_PATCH_PROPOSAL_ONLY',recorded_phase:'REGISTER_NO_HANDOFF',recorded_at_state_version:4,current_execution_status:'UNKNOWN',controls_available:false,source_coverage:'ORIGINAL_EVENT_VERIFIED',model_enabled:false,native_execution_enabled:false,candidate_write_enabled:false,delegation_enabled:false,actual_cost_status:'UNKNOWN',synthetic_tokens_settled:false,arbitrary_tree_stop:false,resource_release_status:'NOT_OBSERVED',recorded_wall_seconds:null};
const profile={...meta,task,control_api_installed:true,original_owner_available:true,profile:'FIXED_ENGINEERING_PATCH_UNIT',last_sdk_status:null,cancel_requested:false,goal_completed:false,independent_review_status:'NOT_PERFORMED'};
class Element{constructor(){this.textContent='';this.disabled=false;this.hidden=false;}addEventListener(){}}
const tick=()=>new Promise(r=>setImmediate(r));
function setup(request){const nodes=new Map();globalThis.document={getElementById:id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);}};let context={project:'p',mode:'fixture',epoch:'e',version:4,authGeneration:1,session:{principal_id:'human',kind:'human',roles:['operator'],csrf_token:'csrf'}};const jobs=new Map();let next=0;const panel=new EngineeringUnitPanel({context:()=>context,request,schedule:f=>{jobs.set(++next,f);return next;},cancel:id=>jobs.delete(id)});return {panel,jobs,setContext:v=>context=v,context:()=>context};}
const receipt=body=>({schema_version:'1.1',command_id:'fixture_command_a',action:body.action,status:'ACCEPTED',accepted_state_version:body.action==='START_FIXED_ENGINEERING'?body.expected_state_version+1:17,request_hash:'sha256:'+'a'.repeat(64),actor_id:'human',task_id:body.task_id,recorded_phase:body.action==='START_FIXED_ENGINEERING'?'HANDOFF_UNKNOWN':'STOP_INTENT_ACCEPTED',execution_status:'UNKNOWN',native_execution_enabled:false,arbitrary_tree_stop:false,duplicate:false});

test('engineering exact profile and receipts reject CPU action and false Review',()=>{
  const s={project:'p',mode:'fixture',epoch:'e'};assert.equal(checkEngineeringUnit(profile,s),profile);
  for(const v of [{profile:'FIXED_CPU_PI_TRIAL_UNIT'},{goal_completed:true},{last_sdk_status:'EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW'},{task:{...task,authorization:'LOCAL_CPU_TRIAL_ONLY'}}])assert.throws(()=>checkEngineeringUnit({...profile,...v},s));
  const body={action:'START_FIXED_ENGINEERING',task_id:task.id,expected_state_version:4};assert.equal(checkEngineeringUnitReceipt(receipt(body),body,'human').recorded_phase,'HANDOFF_UNKNOWN');
  assert.throws(()=>checkEngineeringUnitReceipt({...receipt(body),action:'START_FIXED_CPU'},body,'human'));
});
test('engineering held Run permits independent noCAS STOP and immutable manual retry',async()=>{
  const calls=[];let resolveRun;const s=setup(async(url,options)=>{if(!options)return profile;calls.push(options);const body=JSON.parse(options.body);if(body.action==='START_FIXED_ENGINEERING')return new Promise(r=>resolveRun=r);return receipt(body);});
  await s.panel.load();s.panel.command('run');assert.equal(s.panel.$('stop').disabled,false);
  s.panel.changed(99);s.panel.command('stop');await tick();assert.equal(calls.length,2);
  assert.deepEqual(JSON.parse(calls[1].body),{action:'CANCEL_FIXED_ENGINEERING',task_id:task.id});assert.equal(s.panel.stop.acceptedStop,true);
  await s.panel.send('stop');assert.equal(calls[1].body,calls[2].body);assert.equal(calls[1].headers['Idempotency-Key'],calls[2].headers['Idempotency-Key']);
  s.panel.clear();s.setContext(null);resolveRun(receipt(JSON.parse(calls[0].body)));await tick();assert.equal(s.panel.$('run-receipt').textContent,'');
});

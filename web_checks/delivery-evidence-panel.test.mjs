import test from 'node:test';
import assert from 'node:assert/strict';
import {DeliveryEvidencePanel,checkDelivery} from '../rlflow/static/delivery-evidence-panel.mjs';
const hash='sha256:'+'a'.repeat(64),id='candidate_output_result_a';
const blockers=['MISSING_CONDITION_EVIDENCE','MISSING_INDEPENDENT_REVIEW'];
const value={schema_version:'1.1',project_id:'p',data_mode:'fixture',store_epoch:'e',as_of_state_version:5,execution_enabled:false,goal_ref:'goal_a',contract_revision:1,proposal_sha256:hash,source_coverage:'ORIGINAL_RESULT_AND_CURRENT_CONTRACT_VERIFIED',result_activation:'CURRENT_SOURCE_AS_OF',consent_status:'CURRENT_AS_OF',checked_at:'2026-10-10T00:00:00Z',machine_context:{profile:'FIXED_ENGINEERING_PATCH_UNIT',machine_status:'MACHINE_ACCEPTED_PENDING_REVIEW',candidate_binding_kind:'OUTPUT_TREE_SHA256',candidate_sha256:hash,raw_item_count:3,source_id:id,source_kind:'ENGINEERING',source_sha256:hash,result_sha256:hash,configuration_sha256:hash,original_proposal_sha256:hash,original_contract_revision:1,recorded_state_version:4,verifier_sha256:hash,machine_case_count:21,original_model_budget:{model_sessions:0,model_input_tokens:0,model_output_tokens:0},evidence_role:'UNBOUND_MACHINE_CONTEXT_NOT_CONDITION_EVIDENCE'},conditions:[{id:'condition_a',description:'Actual contract condition',required:true,verification:{method:'independent_review',rule:'Verify before interpretation',evidence_required:['Issued readonly Review']},verification_sha256:hash,status:'UNASSESSED',condition_evidence_refs:[],machine_context_refs:[id],missing:blockers}],required_count:1,required_satisfied_count:0,finalization_status:'BLOCKED_MISSING_EVIDENCE',blockers,independent_review_status:'NOT_PERFORMED',goal_completed:false,dispatch_enabled:false,model_call_enabled:false,condition_evidence_write_enabled:false};
class Element{constructor(){this.textContent='';}addEventListener(){}}
function setup(request){const elements=new Map();globalThis.document={getElementById:id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);}};let c={project:'p',mode:'fixture',epoch:'e',version:5,authGeneration:1,session:{principal_id:'viewer'}};let selected={id};const panel=new DeliveryEvidencePanel({context:()=>c,request,selection:()=>selected,kind:'ENGINEERING',prefix:'candidate-output'});return {panel,setContext:v=>c=v,context:()=>c,setSelected:v=>selected=v};}
test('negative delivery schema rejects fake PASS, wrong scope/source and denominator inflation',()=>{
  const scope={project:'p',mode:'fixture',epoch:'e'};assert.equal(checkDelivery(value,scope,{id},'ENGINEERING').required_count,1);
  for(const bad of [{...value,goal_completed:true},{...value,required_satisfied_count:1},{...value,required_count:2},{...value,independent_review_status:'PASS'},{...value,extra:'private_path'},{...value,project_id:'other'},{...value,machine_context:{...value.machine_context,source_id:'other'}},{...value,conditions:[{...value.conditions[0],status:'PASS'}]},{...value,blockers:[]}])assert.throws(()=>checkDelivery(bad,scope,{id},'ENGINEERING'));
});
test('manual GET only; changes invalidate without automatic acceptance or retry',async()=>{
  const calls=[];const s=setup(async url=>{calls.push(url);return value;});assert.equal(calls.length,0);
  await s.panel.load();assert.equal(calls.length,1);assert.match(calls[0],/delivery-evidence\/ENGINEERING\/candidate_output_result_a$/);assert.equal(s.panel.value.goal_completed,false);
  s.panel.changed(6);assert.equal(s.panel.value,null);assert.equal(s.panel.$('conditions').textContent,'');assert.equal(calls.length,1);
  s.setContext({...s.context(),version:6});await s.panel.load();assert.equal(s.panel.value,null);assert.match(s.panel.$('conditions').textContent,/STALE/);assert.equal(calls.length,2);
});
test('late evidence after identity, epoch, project, selection, durable change or logout never repopulates',async()=>{
  for(const kind of ['identity','epoch','project','selection','version','logout']){
    let resolve;const s=setup(()=>new Promise(r=>resolve=r));const pending=s.panel.load();
    if(kind==='selection')s.setSelected({id:'other'});
    else if(kind==='version')s.panel.changed(6);
    else s.setContext(kind==='logout'?null:{...s.context(),...(kind==='identity'?{authGeneration:2}:{[kind]:'other'})});
    s.panel.clear();resolve(value);await pending;assert.equal(s.panel.value,null);assert.equal(s.panel.$('conditions').textContent,'');assert.equal(s.panel.reading,false);
  }
});
test('original CPU UNAVAILABLE remains a readable negative terminal, never PASS or empty denominator',async()=>{
  const unavailable={...value,consent_status:'UNAVAILABLE_AS_OF',result_activation:'HISTORICAL_ONLY',
    machine_context:{...value.machine_context,profile:'FIXED_CPU_PI_TRIAL_V1',source_kind:'CPU_TRIAL',
      candidate_binding_kind:'FIXED_COMMAND_SHA256',machine_status:'UNAVAILABLE',raw_item_count:0,machine_case_count:0,result_sha256:null},
    blockers:[...blockers,'CURRENT_CONSENT_UNAVAILABLE','RESULT_HISTORICAL_ONLY']};
  unavailable.conditions=value.conditions.map(c=>({...c,missing:unavailable.blockers}));
  const scope={project:'p',mode:'fixture',epoch:'e'};
  assert.equal(checkDelivery(unavailable,scope,{id},'CPU_TRIAL').required_satisfied_count,0);
  assert.throws(()=>checkDelivery({...unavailable,conditions:[],required_count:0},scope,{id},'CPU_TRIAL'));
  const calls=[];const s=setup(async url=>{calls.push(url);return unavailable;});s.panel.kind='CPU_TRIAL';
  await s.panel.load();assert.equal(s.panel.value.machine_context.machine_status,'UNAVAILABLE');
  assert.equal(s.panel.value.goal_completed,false);assert.equal(calls.length,1);
});

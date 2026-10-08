import test from 'node:test';
import assert from 'node:assert/strict';
import {checkGoalPage,checkGoalReview,checkConfirmation,approvalPayload,PendingCommand,sameJSON,parseProposalJSON} from '../rlflow/static/goal-view.mjs';
const h='sha256:'+'a'.repeat(64),scope={project:'p',mode:'fixture',epoch:'e'};
const item={goal_ref:'goal_a',contract_revision:1,contract_hash:h,source_coverage:'HEAD_ONLY',execution_enabled:false,authority:null};
const meta={schema_version:'1.1',project_id:'p',data_mode:'fixture',store_epoch:'e',as_of_state_version:1,execution_enabled:false};
const proposal={goal_id:'g',project_id:'p',data_mode:'fixture',contract_version:1,registry_bindings:{tool_registry_hash:h},objective:'<img src=x>'};
const review=()=>({...meta,goal_ref:'goal_a',contract:{id:'g',version:1,hash:h,proposal:structuredClone(proposal),state:'DRAFT',approval_id:null,outcome:null},changes:[],submitted_by:{id:'human',kind:'human'},submitted_at:'2026-10-09T00:00:00Z',previous_hash:null,source_coverage:'ORIGINAL_EVENT_VERIFIED',submitted_state_version:1,authority:null});
const view=()=>({proposal:structuredClone(proposal),changes:[],binding:{state:'NOT_EXECUTABLE',project_id:'p',data_mode:'fixture',proposal_hash:h,config_hash:h,scope_hash:h,registry_bindings:{tool_registry_hash:h}},confirmation:{id:'nonce',goal_id:'g',store_epoch:'e',expected_version:1,expected_revision:1,expected_authority_revision:0,proposal_hash:h,scope_hash:h,config_hash:h,ttl_seconds:60,view_hash:h},execution_status:'LEASE_VALIDATION_PENDING',execution_enabled:false,limitations:['ACTUAL_DATA_BYTES_NOT_VERIFIED','ACTUAL_OS_AND_RESOURCE_ENFORCEMENT_NOT_VERIFIED']});
test('closed scoped head pages reject private extensions, duplicates and execution claims',()=>{
  const p={...meta,items:[item],next_after:null};assert.equal(checkGoalPage(p,scope),p);
  for(const delta of [{store_epoch:'old'},{items:[item,item]},{next_after:'other'},{execution_enabled:true},{proposal}])assert.throws(()=>checkGoalPage({...p,...delta},scope));
});
test('review bound to selected immutable revision and explicit coverage',()=>{
  const r=review();assert.equal(checkGoalReview(r,scope,item),r);
  for(const delta of [{goal_ref:'other'},{submitted_state_version:2},{source_command_key:'private'},{execution_enabled:true},{contract:{...r.contract,hash:'sha256:'+'b'.repeat(64)}}])assert.throws(()=>checkGoalReview({...r,...delta},scope,item));
  assert.equal(checkGoalReview({...r,source_coverage:'PARTIAL_NO_SOURCE_POINTER',submitted_state_version:null},scope,item).submitted_state_version,null);
});
test('confirmation exact displayed proposal/diff and server hashes must agree',()=>{
  assert.equal(checkConfirmation(view(),review(),scope).execution_enabled,false);
  for(const mutate of [v=>v.proposal.objective='changed',v=>v.changes.push({path:'objective'}),v=>v.confirmation.store_epoch='old',v=>v.confirmation.expected_authority_revision=1,v=>v.binding.scope_hash='sha256:'+'b'.repeat(64),v=>v.execution_enabled=true,v=>v.registry_witness={}]){
    const v=view();mutate(v);assert.throws(()=>checkConfirmation(v,review(),scope));
  }
});
test('approval sends a detached exact nonce object, never rewrites hashes',()=>{
  const v=view(),p=approvalPayload(v);assert.deepEqual(p.parameters.confirmation,v.confirmation);
  v.confirmation.id='changed';assert.equal(p.parameters.confirmation.id,'nonce');
});
test('uncertain delivery retries identical serialized payload/key only in same identity scope',()=>{
  const payload=approvalPayload(view()),s={...scope,identity:'human',authGeneration:1},p=new PendingCommand(s,payload,'key_one');
  const first=p.begin(s);payload.expected_version=99;p.unknown();assert.deepEqual(p.begin(s),first);
  assert.throws(()=>p.begin(s));p.unknown();assert.throws(()=>p.begin({...s,authGeneration:2}));
  assert.throws(()=>p.begin({...s,epoch:'new'}));p.invalidate();assert.throws(()=>p.begin(s));
});
test('completed intent cannot be silently sent again; semantic equality is not canonical hash',()=>{
  const p=new PendingCommand(scope,{},'key');p.begin(scope);p.finish();assert.throws(()=>p.begin(scope));
  assert.equal(sameJSON({b:[1,{a:2}],a:0},{a:0,b:[1,{a:2}]}),true);
  assert.equal(sameJSON({a:1},{a:'1'}),false);
});
test('strict pasted JSON rejects decoded duplicates and numeric loss instead of normalizing intent',()=>{
  for(const raw of ['{"budget":1,"budget":2}','{"allowed_tools":[],"allowed_\\u0074ools":["other"]}',
    '{"budget":{"wall_seconds":1e309}}','{"budget":{"model_input_tokens":9007199254740993}}',
    '{"budget":{"model_input_tokens":9007199254740992}}','{"nested":['.repeat(50)+'0'+']}'.repeat(50)])assert.throws(()=>parseProposalJSON(raw));
  const raw=' {"fraction": 0.2, "numeric_spelling":1.0,"negative":-0.0,"str":"a\\\"b"} ';
  const parsed=parseProposalJSON(raw),p=new PendingCommand(scope,parsed,'key',raw);
  assert.equal(p.begin(scope).body,raw);assert.throws(()=>{p.body='changed';});assert.throws(()=>{p.key='changed';});
});
test('rounded legal server int64 cannot become apparently exact human consent',()=>{
  const unsafe=JSON.parse('9007199254740993');assert.equal(Number.isSafeInteger(unsafe),false);
  const r=review();r.contract.proposal.budget={model_input_tokens:unsafe};assert.throws(()=>checkGoalReview(r,scope,item));
  const v=view();v.proposal.budget={model_input_tokens:unsafe};assert.throws(()=>checkConfirmation(v,r,scope));
  const changed=review();changed.changes=[{path:'budget',before:{wall_seconds:unsafe},after:1}];assert.throws(()=>checkGoalReview(changed,scope,item));
  for(const number of [Infinity,-Infinity,NaN]){const v=view();v.proposal.budget={wall_seconds:number};assert.throws(()=>checkConfirmation(v,review(),scope));}
});

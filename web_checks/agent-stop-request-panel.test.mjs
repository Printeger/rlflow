import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash,webcrypto} from 'node:crypto';
import {verifyRequest} from '../rlflow/static/agent-request-panel.mjs';
globalThis.crypto=webcrypto;
const sha=v=>createHash('sha256').update(JSON.stringify(v)).digest('hex');
function sample() {
  const target={project_id:'project_a',data_mode:'fixture',store_epoch:'store_'+'a'.repeat(32),task_id:'task_a',stop_action:'CANCEL_FIXED_CPU_TRIAL'};
  const scope_sha256='sha256:'+sha([[target.project_id,target.store_epoch,target.task_id,target.stop_action]]);
  const request_id='request_'+'b'.repeat(64),key='forward_'+request_id.slice(8),actor='human_a';
  const intent={schema_version:'1.1',command_id:'fixture_command_'+sha([target.project_id,target.data_mode,target.store_epoch,actor,key]),
    action:target.stop_action,status:'ACCEPTED',accepted_state_version:1,request_hash:'sha256:'+sha({action:target.stop_action,task_id:target.task_id}),
    actor_id:actor,task_id:target.task_id,recorded_phase:'STOP_INTENT_ACCEPTED',execution_status:'UNKNOWN',native_execution_enabled:false,arbitrary_tree_stop:false,duplicate:false};
  return {schema_version:'1.0',request_id,project_id:target.project_id,data_mode:'fixture',store_epoch:target.store_epoch,
    action:'request_finite_stop',request_hash:'sha256:'+'c'.repeat(64),submitted_by:{id:'agent_a',kind:'agent'},status:'STOPPED_AS_OF_RETURN',execution_enabled:false,
    stop_scope:{scope_sha256,items:[target]},forwarded_by:{id:actor,kind:'human'},original_owner_available:true,
    result:{schema_version:'1.1',command_id:'finite_stop_'+sha([scope_sha256,actor,key]),action:'CANCEL_ORIGINAL_FINITE_UNITS',duplicate:true,
      status:'ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN',scope:'ORIGINAL_FIXED_BOUND_UNITS_ONLY',durable_aggregate_receipt:false,cleanup_resume:false,
      items:[{project_id:target.project_id,store_epoch:target.store_epoch,task_id:target.task_id,intent,intent_status:'ACCEPTED',cleanup_status:'ORIGINAL_SCOPE_STOPPED',post_cleanup_status:'RETURNED',error_type:null,goal_completed:false,independent_review_status:'NOT_PERFORMED'}],goal_completed:false,independent_review_status:'NOT_PERFORMED'}};
}
const context=v=>({project:v.project_id,mode:v.data_mode,epoch:v.store_epoch});
test('closed original scope and derived finite/child/body identities verified before display',async()=>{
  const v=sample();assert.equal(await verifyRequest(v,context(v),{privateView:true}),v);
  for(const change of [x=>x.stop_scope.scope_sha256='sha256:'+'d'.repeat(64),
    x=>x.result.command_id='finite_stop_'+'d'.repeat(64),
    x=>x.result.items[0].intent.command_id='fixture_command_'+'d'.repeat(64),
    x=>x.result.items[0].intent.request_hash='sha256:'+'d'.repeat(64)]) {
    const bad=structuredClone(v);change(bad);
    await assert.rejects(verifyRequest(bad,context(v),{privateView:true}));
    delete bad.forwarded_by;delete bad.original_owner_available;
    await assert.rejects(verifyRequest(bad,context(v)));
  }
});

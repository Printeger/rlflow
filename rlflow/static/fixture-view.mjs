// Consistency checks only. Neither historical DTOs nor discovery grant execution.
const id=v=>typeof v==='string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(v);
const count=v=>Number.isSafeInteger(v) && v>=0;
const closed=(v,keys)=>v!==null && typeof v==='object' && !Array.isArray(v) && Object.keys(v).sort().join()===keys.slice().sort().join();
const fail=()=>{throw new Error('固定 CPU 来源合同被拒绝；未启用动作');};
const meta=['schema_version','project_id','data_mode','store_epoch','as_of_state_version','execution_enabled'];
export const phases=['REGISTER_NO_HANDOFF','HANDOFF_UNKNOWN','PROCESS_REGISTERED','RELEASE_INTENT','STARTED_AS_OBSERVED','STOP_REQUESTED','FIXTURE_SCOPE_STOPPED'];
function scope(v,s){if(!v || v.schema_version!=='1.1' || v.project_id!==s.project || v.data_mode!=='fixture' || s.mode!=='fixture' || v.store_epoch!==s.epoch || !count(v.as_of_state_version) || v.execution_enabled!==false)fail();}
const taskKeys=['id','attempt_id','reservation_id','kind','authorization','recorded_phase','recorded_at_state_version','current_execution_status','controls_available','source_coverage','model_enabled','native_execution_enabled','candidate_write_enabled','delegation_enabled','actual_cost_status','synthetic_tokens_settled','arbitrary_tree_stop','resource_release_status','recorded_wall_seconds'];
function task(v,version){
  if(!closed(v,taskKeys) || !['id','attempt_id','reservation_id'].every(k=>id(v[k])) || v.kind!=='PROTOCOL_CONFORMANCE' || v.authorization!=='LOCAL_PROTOCOL_ONLY' || !phases.includes(v.recorded_phase) || !count(v.recorded_at_state_version) || v.recorded_at_state_version>version || v.current_execution_status!=='UNKNOWN' || v.source_coverage!=='ORIGINAL_EVENT_VERIFIED' || v.actual_cost_status!=='UNKNOWN' || v.resource_release_status!=='NOT_OBSERVED' || !['controls_available','model_enabled','native_execution_enabled','candidate_write_enabled','delegation_enabled','synthetic_tokens_settled','arbitrary_tree_stop'].every(k=>v[k]===false) || (v.recorded_phase==='FIXTURE_SCOPE_STOPPED' ? !count(v.recorded_wall_seconds) : v.recorded_wall_seconds!==null))fail();
}
export function checkFixtureProfile(v,s){scope(v,s);if(!closed(v,[...meta,'control_api_installed','original_owner_available','profile','native_execution_enabled','arbitrary_tree_stop']) || v.control_api_installed!==true || typeof v.original_owner_available!=='boolean' || v.profile!=='FIXED_CPU_SINGLE_PARTICIPANT' || v.native_execution_enabled!==false || v.arbitrary_tree_stop!==false)fail();return v;}
export function checkFixturePage(v,s,after=''){
  scope(v,s);if(!closed(v,[...meta,'items','next_after']) || !Array.isArray(v.items) || v.items.length>20)fail();
  let previous=after;for(const row of v.items){task(row,v.as_of_state_version);if(row.reservation_id<=previous)fail();previous=row.reservation_id;}
  // Cursor tracks SCANNED reservations, so an empty sparse page may advance.
  if(v.next_after!==null && (!id(v.next_after) || v.next_after<=after || v.next_after<previous))fail();return v;
}
export function checkFixtureDetail(v,s,selected){scope(v,s);if(!closed(v,[...meta,'task']))fail();task(v.task,v.as_of_state_version);if(v.task.id!==selected.id || v.task.reservation_id!==selected.reservation_id || v.task.attempt_id!==selected.attempt_id)fail();return v;}
export function checkFixtureReceipt(v,body,actor){
  if(!closed(v,['schema_version','command_id','action','status','accepted_state_version','request_hash','actor_id','task_id','recorded_phase','execution_status','native_execution_enabled','arbitrary_tree_stop','duplicate']) || v.schema_version!=='1.1' || !id(v.command_id) || v.action!==body.action || v.status!=='ACCEPTED' || v.accepted_state_version!==body.expected_state_version+1 || !count(v.accepted_state_version) || !/^sha256:[0-9a-f]{64}$/.test(v.request_hash) || v.actor_id!==actor || v.task_id!==body.task_id || v.recorded_phase!==(body.action==='START_FIXED_CPU'?'HANDOFF_UNKNOWN':'STOP_REQUESTED') || v.execution_status!=='UNKNOWN' || v.native_execution_enabled!==false || v.arbitrary_tree_stop!==false || typeof v.duplicate!=='boolean')fail();return v;
}

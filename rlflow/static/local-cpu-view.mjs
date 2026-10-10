// Display consistency only: no current liveness, execution or Reviewer grant.
const closed=(v,keys)=>v!==null && typeof v==='object' && !Array.isArray(v) && Object.keys(v).sort().join()===keys.slice().sort().join();
const count=v=>Number.isSafeInteger(v) && v>=0;
const hash=v=>typeof v==='string' && /^sha256:[0-9a-f]{64}$/.test(v);
const fail=()=>{throw new Error('配置 CPU 原来源合同被拒绝；保持只读 UNKNOWN');};
const dimensions=['experiment_retries','experiment_starts','gpu_device_seconds','model_input_tokens','model_output_tokens','model_sessions','wall_seconds'];
const vector=v=>closed(v,dimensions) && dimensions.every(k=>count(v[k]));
const text=v=>typeof v==='string' && new TextEncoder().encode(v).length<=65536;
export const localTaskKeys=['configured_local_cpu_only','fixed_cpu_scope_only','profile','approved_spec_sha256','approved_code_sha256','approved_inputs_sha256','recorded_release_attempted','recorded_terminal_proof_sha256','local_result_status','machine_acceptance_status','independent_review_status','condition_evidence','recorded_budget_status','recorded_reserved_amount','recorded_unknown_exposure','cold_recovery_action'];
export function checkLocalTaskExtras(v){
  if(v.configured_local_cpu_only!==true || v.fixed_cpu_scope_only!==false || v.profile!=='CONFIGURED_LOCAL_CPU_V1' || !['approved_spec_sha256','approved_code_sha256','approved_inputs_sha256'].every(k=>hash(v[k])) || typeof v.recorded_release_attempted!=='boolean' || !(v.recorded_terminal_proof_sha256===null || hash(v.recorded_terminal_proof_sha256)) || !['NOT_DURABLY_ARCHIVED','ARCHIVED','RESULT_UNAVAILABLE'].includes(v.local_result_status) || !['UNKNOWN','PASS','FAIL','NOT_CONFIGURED'].includes(v.machine_acceptance_status) || v.independent_review_status!=='NOT_PROVEN' || v.condition_evidence!==false || !['HELD','UNKNOWN','SETTLED'].includes(v.recorded_budget_status) || !vector(v.recorded_reserved_amount) || !vector(v.recorded_unknown_exposure) || dimensions.some(k=>v.recorded_unknown_exposure[k]>v.recorded_reserved_amount[k]) || v.cold_recovery_action!=='READ_ONLY_HISTORY_NO_EXECUTION_REPLAY')fail();
  if(v.recorded_budget_status==='SETTLED' && (v.recorded_phase!=='FIXTURE_SCOPE_STOPPED' || dimensions.some(k=>v.recorded_reserved_amount[k] || v.recorded_unknown_exposure[k])))fail();
}
export function checkLocalDetail(v){
  const r=v.configured_result,t=v.task,u=v.recorded_settled_usage;
  if(t.recorded_phase==='FIXTURE_SCOPE_STOPPED' ? !vector(u) : u!==null)fail();
  if(r===null){if(t.local_result_status==='ARCHIVED' || t.machine_acceptance_status!=='UNKNOWN')fail();return;}
  const execution=Object.hasOwn(r,'execution');
  if(t.local_result_status!=='ARCHIVED' || t.recorded_phase!=='FIXTURE_SCOPE_STOPPED' || !closed(r,['outputs','approved_acceptance','machine_acceptance',...(execution?['execution']:[])]) || !closed(r.outputs,['stdout','stderr']))fail();
  if(execution && (!closed(r.execution,['status','wait_status','control_terminal_reason']) || !['SUCCEEDED','NONZERO_EXIT','SIGNAL_EXIT','DEADLINE'].includes(r.execution.status) || !count(r.execution.wait_status) || r.execution.wait_status>65535 || !['DEADLINE','PRODUCER_EXIT','CONTROL_EOF','CONTROL_STOP'].includes(r.execution.control_terminal_reason)))fail();
  if(execution){
    const low=r.execution.wait_status&127;
    if(low===127)fail();
    const expected=r.execution.control_terminal_reason==='DEADLINE'?'DEADLINE':low===0?(r.execution.wait_status>>>8===0?'SUCCEEDED':'NONZERO_EXIT'):'SIGNAL_EXIT';
    if(r.execution.status!==expected)fail();
  }
  const failed=execution && r.execution.status!=='SUCCEEDED';
  for(const output of Object.values(r.outputs))if(!closed(output,['text','sha256']) || !text(output.text) || !hash(output.sha256))fail();
  const m=r.machine_acceptance,a=r.approved_acceptance;
  if(!closed(m,['status','criteria_sha256']) || m.status!==t.machine_acceptance_status || !['PASS','FAIL','NOT_CONFIGURED'].includes(m.status))fail();
  if(failed && m.status!=='FAIL')fail();
  if(a===null){if(m.status!==(failed?'FAIL':'NOT_CONFIGURED') || m.criteria_sha256!==null)fail();return;}
  if(!hash(m.criteria_sha256) || m.status==='NOT_CONFIGURED' || typeof a.stderr_empty!=='boolean')fail();
  if(a.method==='EXACT_STDOUT_UTF8'){if(!closed(a,['method','stdout','stderr_empty']) || !text(a.stdout))fail();}
  else if(a.method==='JSON_METRICS_RANGE'){
    if(!closed(a,['method','metrics','stderr_empty']) || !a.metrics || Array.isArray(a.metrics) || typeof a.metrics!=='object' || Object.keys(a.metrics).length<1 || Object.keys(a.metrics).length>16)fail();
    for(const [key,b] of Object.entries(a.metrics))if(!/^[A-Za-z][A-Za-z0-9_]{0,79}$/.test(key) || !closed(b,['min','max']) || !Number.isFinite(b.min) || !Number.isFinite(b.max) || b.min>b.max)fail();
  }else fail();
}

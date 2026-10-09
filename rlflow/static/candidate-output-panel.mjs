// Immutable original engineering evidence; no execution buttons or authority.
import {CpuAssessmentPanel} from './cpu-assessment-panel.mjs';
const closed=(v,keys)=>v && typeof v==='object' && !Array.isArray(v) && Object.keys(v).sort().join()===keys.slice().sort().join();
const id=v=>typeof v==='string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(v);
const count=v=>Number.isSafeInteger(v) && v>=0;
const hash=v=>typeof v==='string' && /^sha256:[0-9a-f]{64}$/.test(v);
const time=v=>typeof v==='string' && v.endsWith('Z') && Number.isFinite(Date.parse(v));
const instant=v=>{
  const match=/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.([0-9]{1,6}))?Z$/.exec(v);
  if(!match)throw new Error('工程来源时间格式被拒绝');
  return BigInt(Date.parse(match[1]+'Z'))*1000n+BigInt((match[2]||'').padEnd(6,'0'));
};
const meta=['schema_version','project_id','data_mode','store_epoch','as_of_state_version','execution_enabled'];
const fields=['id','task_id','attempt_id','goal_ref','contract_revision','recorded_at','recorded_at_state_version','state','source_coverage','current_activation','current_execution_status','resource_release_status','actual_cost_status','model_enabled','gpu_enabled','controls_available','goal_completed','dispatch_enabled','independent_review_status','target','before_sha256','after_sha256','base_tree_sha256','output_tree_sha256','baseline_failed_cases','actual_passed_cases'];
const evidence=['actual_tests','candidate_write_performed','candidate_write_fd_closed','historical_runtime_phase','historical_pool_release','result_sha256','intent_sha256','source_sha256','program_sha256','resource_enforcement'];
const fail=()=>{throw new Error('工程产出来源合同被拒绝');};
const measurements=['cpu_ns','worker_wall_ns','cpu_measurement_scope'];
function evidenceKeys(e){
  const present=measurements.filter(k=>Object.hasOwn(e??{},k));
  if(!present.length)return evidence;
  if(present.length!==3 || !['cpu_ns','worker_wall_ns'].every(k=>count(e[k]) && e[k]<=3e9) || e.cpu_measurement_scope!=='ORIGINAL_FIXED_PROGRAM_KERNEL_REPORTED_AS_OF_EMIT')fail();
  return [...evidence,...measurements];
}
export function checkOutput(value,scope,selected=null,after=''){
  if(!closed(value,[...meta,...(selected?['candidate']:['items','next_after'])]) || value.schema_version!=='1.1' || value.project_id!==scope.project || value.store_epoch!==scope.epoch || value.data_mode!=='fixture' || scope.mode!=='fixture' || !count(value.as_of_state_version) || value.execution_enabled!==false)fail();
  const rows=selected?[value.candidate]:value.items;
  if(!Array.isArray(rows) || rows.length>5)fail();let previous=after;
  for(const r of rows){
    if(!closed(r,[...fields,...(selected?['evidence',...(Object.hasOwn(r??{},'machine_acceptance')?['machine_acceptance']:[])]:[])]) || !['id','task_id','attempt_id','goal_ref'].every(k=>id(r[k])) || !count(r.contract_revision) || !count(r.recorded_at_state_version) || r.recorded_at_state_version>value.as_of_state_version || !time(r.recorded_at) || r.state!=='OUTPUT_CAPTURED_AUDIT_ONLY' || r.source_coverage!=='ORIGINAL_DEPENDENCIES_VERIFIED' || r.current_activation!=='HISTORICAL_AUDIT_ONLY' || r.current_execution_status!=='UNKNOWN' || r.resource_release_status!=='NOT_OBSERVED' || r.actual_cost_status!=='UNKNOWN' || r.independent_review_status!=='NOT_PERFORMED' || !['model_enabled','gpu_enabled','controls_available','goal_completed','dispatch_enabled'].every(k=>r[k]===false) || r.target!=='module/source.py' || !['before_sha256','after_sha256','base_tree_sha256','output_tree_sha256'].every(k=>hash(r[k])) || r.before_sha256===r.after_sha256 || r.base_tree_sha256===r.output_tree_sha256 || r.baseline_failed_cases!==2 || r.actual_passed_cases!==3)fail();
    if(selected){
      if(['id','task_id','attempt_id'].some(k=>r[k]!==selected[k]))fail();const e=r.evidence,keys=evidenceKeys(e);
      if(!closed(e,keys) || e.candidate_write_performed!==true || e.candidate_write_fd_closed!==true || e.historical_runtime_phase!=='FIXTURE_SCOPE_STOPPED' || e.historical_pool_release!=='FIXTURE_FREE' || e.resource_enforcement!=='partial' || !['result_sha256','intent_sha256','source_sha256','program_sha256'].every(k=>hash(e[k])) || !Array.isArray(e.actual_tests) || e.actual_tests.length!==3)fail();
      for(const [i,t] of e.actual_tests.entries()){
        const [a,b]=[[2,3],[-4,2],[0,0]][i];
        if(!closed(t,['left','right','expected','actual']) || !Object.values(t).every(Number.isSafeInteger) || t.left!==a || t.right!==b || t.expected!==a+b || t.actual!==a+b)fail();
      }
      if(r.machine_acceptance!==undefined && r.machine_acceptance!==null){
        const m=r.machine_acceptance,d=m?.derived;
        if(!closed(m,['id','recorded_at','recorded_at_state_version','verifier_version','verifier_sha256','status','derived','interpretation_scope','candidate_read_only','condition_coverage','independent_review_status','goal_completed','dispatch_enabled']) || !id(m.id) || !time(m.recorded_at) || instant(m.recorded_at)<=instant(r.recorded_at) || !count(m.recorded_at_state_version) || m.recorded_at_state_version<=r.recorded_at_state_version || m.recorded_at_state_version>value.as_of_state_version || m.verifier_version!=='FIXED_ADD_RAW_AST_CHECK_V1' || !hash(m.verifier_sha256) || m.status!=='MACHINE_ACCEPTED_PENDING_REVIEW' || m.interpretation_scope!=='FIXED_ADD_FUNCTION_ONLY' || m.candidate_read_only!==true || !Array.isArray(m.condition_coverage) || m.condition_coverage.length || m.independent_review_status!=='NOT_PERFORMED' || m.goal_completed!==false || m.dispatch_enabled!==false || !closed(d,['source_sha256','spec_sha256','syntax_sha256','actual_tests','passed_cases']) || !['source_sha256','spec_sha256','syntax_sha256'].every(k=>hash(d[k])) || d.source_sha256!==r.after_sha256 || d.passed_cases!==21 || !Array.isArray(d.actual_tests) || d.actual_tests.length!==21)fail();
        for(const [i,t] of d.actual_tests.entries()){
          const a=Math.floor(i/3)-3,b=[-2,0,2][i%3];
          if(!closed(t,['left','right','expected','actual']) || !Object.values(t).every(Number.isSafeInteger) || t.left!==a || t.right!==b || t.expected!==a+b || t.actual!==a+b)fail();
        }
      }
    }else {if(r.id<=previous)fail();previous=r.id;}
  }
  if(!selected && value.next_after!==null && (!rows.length || value.next_after!==previous))fail();return value;
}
export class CandidateOutputPanel extends CpuAssessmentPanel{
  constructor(options){super({...options,prefix:'candidate-output',check:checkOutput,path:'candidate-outputs',
    describe:r=>`${r.id} · 原baseline失败 ${r.baseline_failed_cases} → 实际通过 ${r.actual_passed_cases} · ${r.current_activation}`,
    select:r=>({id:r.id,task_id:r.task_id,attempt_id:r.attempt_id}),
    note:'原固定工程产出 · CPU/wall 仅只读 worker 内核测量至 emit，不含启动、候选写入及父进程检查，不是账单；历史关闭不代表当前资源；独立评审 NOT_PERFORMED，Goal 未完成。'});}
}

// Explicit manual cold GET. Machine context is never ConditionEvidence.
const closed=(v,keys)=>v && typeof v==='object' && !Array.isArray(v) && Object.keys(v).sort().join()===keys.slice().sort().join();
const id=v=>typeof v==='string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(v);
const hash=v=>typeof v==='string' && /^sha256:[a-f0-9]{64}$/.test(v);
const count=v=>Number.isSafeInteger(v) && v>=0;
const time=v=>typeof v==='string' && v.endsWith('Z') && Number.isFinite(Date.parse(v));
const fail=()=>{throw Error('条件证据来源合同被拒绝');};
export function checkDelivery(v,s,selection,kind){
  const keys=['schema_version','project_id','data_mode','store_epoch','as_of_state_version','execution_enabled','goal_ref','contract_revision','proposal_sha256','source_coverage','result_activation','consent_status','checked_at','machine_context','conditions','required_count','required_satisfied_count','finalization_status','blockers','independent_review_status','goal_completed','dispatch_enabled','model_call_enabled','condition_evidence_write_enabled'];
  if(!closed(v,keys) || v.schema_version!=='1.1' || v.project_id!==s.project || v.store_epoch!==s.epoch || v.data_mode!=='fixture' || s.mode!=='fixture' || !count(v.as_of_state_version) || !id(v.goal_ref) || !count(v.contract_revision) || v.contract_revision<1 || !hash(v.proposal_sha256) || !time(v.checked_at) || v.source_coverage!=='ORIGINAL_RESULT_AND_CURRENT_CONTRACT_VERIFIED' || !['CURRENT_SOURCE_AS_OF','HISTORICAL_ONLY'].includes(v.result_activation) || !['CURRENT_AS_OF','UNAVAILABLE_AS_OF'].includes(v.consent_status) || !['execution_enabled','goal_completed','dispatch_enabled','model_call_enabled','condition_evidence_write_enabled'].every(k=>v[k]===false) || v.finalization_status!=='BLOCKED_MISSING_EVIDENCE' || v.independent_review_status!=='NOT_PERFORMED' || v.required_satisfied_count!==0)fail();
  const m=v.machine_context;
if(!closed(m,['profile','machine_status','candidate_binding_kind','candidate_sha256','raw_item_count','source_id','source_kind','source_sha256','result_sha256','configuration_sha256','original_proposal_sha256','original_contract_revision','recorded_state_version','verifier_sha256','machine_case_count','original_model_budget','evidence_role']) || m.source_id!==selection.id || m.source_kind!==kind || !['CPU_TRIAL','ENGINEERING'].includes(kind) || m.profile!==(kind==='CPU_TRIAL'?'FIXED_CPU_PI_TRIAL_V1':'FIXED_ENGINEERING_PATCH_UNIT') || m.candidate_binding_kind!==(kind==='CPU_TRIAL'?'FIXED_COMMAND_SHA256':'OUTPUT_TREE_SHA256') || !(kind==='CPU_TRIAL'?['NOT_RECORDED','MACHINE_VERIFIED','UNAVAILABLE']:['NOT_RECORDED','MACHINE_ACCEPTED_PENDING_REVIEW']).includes(m.machine_status) || !['candidate_sha256','source_sha256','configuration_sha256','original_proposal_sha256'].every(k=>hash(m[k])) || ![m.result_sha256,m.verifier_sha256].every(h=>h===null || hash(h)) || !['raw_item_count','original_contract_revision','recorded_state_version','machine_case_count'].every(k=>count(m[k])) || m.recorded_state_version>v.as_of_state_version || m.evidence_role!=='UNBOUND_MACHINE_CONTEXT_NOT_CONDITION_EVIDENCE' || !closed(m.original_model_budget,['model_sessions','model_input_tokens','model_output_tokens']) || !Object.values(m.original_model_budget).every(n=>n===0))fail();
  const blockers=['MISSING_CONDITION_EVIDENCE','MISSING_INDEPENDENT_REVIEW'];
  const same=m.original_proposal_sha256===v.proposal_sha256;
  if(!same)blockers.push('CURRENT_CONTRACT_DIFFERS');
  if(v.consent_status==='UNAVAILABLE_AS_OF')blockers.push('CURRENT_CONSENT_UNAVAILABLE');
  if(v.result_activation==='HISTORICAL_ONLY')blockers.push('RESULT_HISTORICAL_ONLY');
  if(JSON.stringify(v.blockers)!==JSON.stringify(blockers) || v.result_activation==='CURRENT_SOURCE_AS_OF' && (!same || v.consent_status!=='CURRENT_AS_OF') || !Array.isArray(v.conditions) || !v.conditions.length || v.conditions.length>200 || !count(v.required_count) || !v.required_count)fail();
  const seen=new Set();
  for(const c of v.conditions){
    if(!closed(c,['id','description','required','verification','verification_sha256','status','condition_evidence_refs','machine_context_refs','missing']) || !id(c.id) || seen.has(c.id) || typeof c.description!=='string' || typeof c.required!=='boolean' || !closed(c.verification,['method','rule','evidence_required']) || !['deterministic','independent_review','experiment'].includes(c.verification.method) || typeof c.verification.rule!=='string' || !Array.isArray(c.verification.evidence_required) || !c.verification.evidence_required.every(e=>typeof e==='string') || !hash(c.verification_sha256) || c.status!=='UNASSESSED' || !Array.isArray(c.condition_evidence_refs) || c.condition_evidence_refs.length || JSON.stringify(c.machine_context_refs)!==JSON.stringify(same?[selection.id]:[]) || JSON.stringify(c.missing)!==JSON.stringify(blockers))fail();
    seen.add(c.id);
  }
  if(v.required_count!==v.conditions.filter(c=>c.required).length)fail();return v;
}
export class DeliveryEvidencePanel{
  constructor({context,request,selection,kind,prefix}){
    Object.assign(this,{context,request,selection,kind});this.$=id=>document.getElementById(prefix+'-'+id);
    this.serial=0;this.$('delivery').addEventListener('click',()=>this.load());this.clear();
  }
  scope(){const c=this.context();return c?{project:c.project,mode:c.mode,epoch:c.epoch,identity:c.session.principal_id,authGeneration:c.authGeneration}:null;}
  clear(){++this.serial;this.value=null;this.reading=false;this.$('conditions').textContent='';this.render();}
  render(){this.$('delivery').disabled=this.reading || this.scope()?.mode!=='fixture' || !this.selection();}
  changed(version){if(this.reading || this.value && version>this.value.as_of_state_version)this.clear();}
  async load(){
    if(this.reading || !this.selection() || this.scope()?.mode!=='fixture')return;
    const serial=++this.serial,scope=this.scope(),selection={...this.selection()};
    const current=()=>serial===this.serial && JSON.stringify(scope)===JSON.stringify(this.scope()) && JSON.stringify(selection)===JSON.stringify(this.selection());
    this.reading=true;this.value=null;this.$('conditions').textContent='正在读取原合同条件；不评定 PASS。';this.render();
    try{
      const value=checkDelivery(await this.request(`/api/v1/projects/${encodeURIComponent(scope.project)}/delivery-evidence/${this.kind}/${encodeURIComponent(selection.id)}`),scope,selection,this.kind);
      if(!current())return;if(value.as_of_state_version<(this.context()?.version??0))throw Error('STALE 持久版本，须手动重新读取');
      this.value=value;this.$('conditions').textContent=JSON.stringify(value,null,2);
    }catch(e){if(current())this.$('conditions').textContent=`条件来源不可用：${e.message}；未完成、未评定。手动读取恢复。`;}
    finally{if(current()){this.reading=false;this.render();}}
  }
}

// Readonly original-evidence display. No execution or decision authority.
const closed=(v,keys)=>v && typeof v==='object' && !Array.isArray(v) && Object.keys(v).sort().join()===keys.slice().sort().join();
const id=v=>typeof v==='string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(v);
const count=v=>Number.isSafeInteger(v) && v>=0;
const time=v=>typeof v==='string' && v.endsWith('Z') && Number.isFinite(Date.parse(v));
const meta=['schema_version','project_id','data_mode','store_epoch','as_of_state_version','execution_enabled'];
const fields=['id','experiment_id','attempt_id','goal_ref','contract_revision','recorded_at','recorded_at_state_version','assessment','source_coverage','model_enabled','gpu_enabled','controls_available','current_execution_status','resource_release_status','actual_cost_status','goal_completed','dispatch_enabled','current_activation','checked_at'];
const axes=['profile','execution_status','scientific_validity','hypothesis_outcome','interpretation_scope','next_action','condition_coverage','independent_review_status','goal_completed','dispatch_enabled'];
const fail=()=>{throw new Error('CPU 评估来源合同被拒绝');};
export function checkAssessment(value,scope,selected=null,after=''){
  if(!closed(value,[...meta,...(selected?['experiment']:['items','next_after'])]) || value.schema_version!=='1.1' || value.project_id!==scope.project || value.store_epoch!==scope.epoch || value.data_mode!=='fixture' || scope.mode!=='fixture' || !count(value.as_of_state_version) || value.execution_enabled!==false)fail();
  const rows=selected?[value.experiment]:value.items;
  if(!Array.isArray(rows) || rows.length>5)fail();let previous=after;
  for(const row of rows){
    const a=row?.assessment;
    if(!closed(row,[...fields,...(selected?['evidence']:[])]) || !['id','experiment_id','attempt_id','goal_ref'].every(k=>id(row[k])) || !count(row.contract_revision) || !count(row.recorded_at_state_version) || row.recorded_at_state_version>value.as_of_state_version || !time(row.recorded_at) || !time(row.checked_at) || !['EXPERIMENT_CURRENT_AS_OF','HISTORICAL_ONLY'].includes(row.current_activation) || row.source_coverage!=='ORIGINAL_DEPENDENCIES_VERIFIED' || row.current_execution_status!=='UNKNOWN' || row.resource_release_status!=='NOT_OBSERVED' || row.actual_cost_status!=='UNKNOWN' || !['model_enabled','gpu_enabled','controls_available','goal_completed','dispatch_enabled'].every(k=>row[k]===false) || !closed(a,axes) || a.profile!=='FIXED_CPU_PI_TRIAL_V1' || !['SUCCEEDED','NOT_EXECUTED','RESULT_UNAVAILABLE'].includes(a.execution_status) || !['VALID','UNASSESSED'].includes(a.scientific_validity) || !['SUPPORTED','REFUTED','INCONCLUSIVE'].includes(a.hypothesis_outcome) || a.interpretation_scope!=='PINNED_THREE_SEEDS_ONLY' || a.independent_review_status!=='NOT_PERFORMED' || !Array.isArray(a.condition_coverage) || a.condition_coverage.length || a.goal_completed!==false || a.dispatch_enabled!==false || a.next_action!==(a.execution_status==='SUCCEEDED'?'REQUEST_INDEPENDENT_REVIEW':'NO_AUTOMATIC_RETRY') || a.scientific_validity!==(a.execution_status==='SUCCEEDED'?'VALID':'UNASSESSED'))fail();
    if(a.execution_status==='SUCCEEDED' ? !['SUPPORTED','REFUTED'].includes(a.hypothesis_outcome) : a.hypothesis_outcome!=='INCONCLUSIVE')fail();
    if(selected){if(row.id!==selected.id || row.experiment_id!==selected.experiment_id || row.attempt_id!==selected.attempt_id)fail();checkEvidence(row.evidence,a);}
    else {if(row.id<=previous)fail();previous=row.id;}
  }
  if(!selected && value.next_after!==null && (!rows.length || value.next_after!==previous))fail();return value;
}
function checkEvidence(e,a){
  if(e===null){if(a.execution_status==='SUCCEEDED')fail();return;}
  const keys=['raw_samples','inside_counts','estimates','mean_absolute_error','baseline','baseline_absolute_error','hypothesis_supported','source_sha256','input_sha256','program_sha256','evaluator_sha256','cpu_ns','worker_wall_ns','cpu_measurement_scope','resource_enforcement','verification'];
  if(a.execution_status!=='SUCCEEDED' || !closed(e,keys) || e.verification!=='RAW_VALUES_VERIFIED' || e.resource_enforcement!=='partial' || e.cpu_measurement_scope!=='ORIGINAL_FIXED_PROGRAM_KERNEL_REPORTED_AS_OF_EMIT' || !['source_sha256','input_sha256','program_sha256','evaluator_sha256'].every(k=>/^sha256:[0-9a-f]{64}$/.test(e[k])) || !count(e.cpu_ns) || !count(e.worker_wall_ns) || !['mean_absolute_error','baseline','baseline_absolute_error'].every(k=>Number.isFinite(e[k])) || typeof e.hypothesis_supported!=='boolean' || !Array.isArray(e.raw_samples) || e.raw_samples.length!==3 || !Array.isArray(e.inside_counts) || e.inside_counts.length!==3 || !e.inside_counts.every(n=>count(n) && n<=128) || !Array.isArray(e.estimates) || e.estimates.length!==3 || !e.estimates.every(Number.isFinite))fail();
  for(const [i,r] of e.raw_samples.entries())if(!closed(r,['seed','points']) || r.seed!==[7,11,19][i] || !Array.isArray(r.points) || r.points.length!==128 || !r.points.every(p=>Array.isArray(p) && p.length===2 && p.every(n=>count(n) && n<65536)))fail();
  if(a.hypothesis_outcome!==(e.hypothesis_supported?'SUPPORTED':'REFUTED'))fail();
}
export class CpuAssessmentPanel{
  constructor({context,request,now=()=>performance.now(),schedule=(fn,ms)=>setTimeout(fn,ms),cancel=id=>clearTimeout(id)}){
    Object.assign(this,{context,request,now,schedule,cancel});this.serial=0;this.connectionState='UNKNOWN';this.$=id=>document.getElementById('cpu-assessment-'+id);
    this.$('refresh').addEventListener('click',()=>this.load());this.$('next').addEventListener('click',()=>this.load(this.page?.next_after));this.clear();
  }
  scope(){const c=this.context();return c?{project:c.project,mode:c.mode,epoch:c.epoch,identity:c.session.principal_id,authGeneration:c.authGeneration}:null;}
  ticket(){return {serial:this.serial,scope:this.scope()};}
  current(t){return t.serial===this.serial && JSON.stringify(t.scope)===JSON.stringify(this.scope());}
  clear(){++this.serial;this.cancel(this.timer);this.timer=null;this.page=null;this.detail=null;this.selected=null;this.after='';this.reading=false;this.blocked=false;this.wanted=0;this.boundScope=null;this.lastRead=-Infinity;this.$('list').replaceChildren();this.$('detail').textContent='';this.$('note').textContent='尚未读取；没有自动执行。';this.render(false);}
  floor(){const s=JSON.stringify(this.scope());if(s!==this.boundScope){this.boundScope=s;this.wanted=0;}const c=this.context();if(c?.mode==='fixture' && count(c.version))this.wanted=Math.max(this.wanted,c.version);}
  dirty(){return Boolean(this.page && (this.page.as_of_state_version<this.wanted || this.selected && (!this.detail || this.detail.as_of_state_version<this.wanted)));}
  render(sync=true){if(sync)this.floor();this.$('refresh').disabled=this.reading;this.$('next').disabled=this.reading || !this.page?.next_after;for(const b of this.$('list').children)b.disabled=this.reading;this.$('live').textContent=`${this.connectionState} · as-of ${this.page?.as_of_state_version??'UNKNOWN'} · 持久版本 ${this.wanted} · ${this.blocked || this.dirty()?'STALE':'AS-OF'} · checked_at 不是当前授权，心跳不刷新评估有效性`;}
  changed(version){this.floor();if(count(version))this.wanted=Math.max(this.wanted,version);this.render();this.queue();}
  connection(status){this.connectionState=status;if(!['LIVE','CATCHING UP'].includes(status)){this.cancel(this.timer);this.timer=null;}this.render();this.queue();}
  queue(){if(!this.dirty() || this.reading || this.blocked || this.timer!==null || !['LIVE','CATCHING UP'].includes(this.connectionState))return;const t=this.ticket();this.timer=this.schedule(()=>{this.timer=null;if(this.current(t) && !this.blocked && ['LIVE','CATCHING UP'].includes(this.connectionState))this.load(this.after,true);},Math.max(0,1000-(this.now()-this.lastRead)));}
  base(){return `/api/v1/projects/${encodeURIComponent(this.scope().project)}/cpu-trial-assessments`;}
  async load(after='',automatic=false){
    if(this.reading)return;if(this.scope()?.mode!=='fixture'){this.clear();return;}this.cancel(this.timer);this.timer=null;if(!automatic)this.blocked=false;
    ++this.serial;const t=this.ticket();this.reading=true;this.lastRead=this.now();this.after=after||'';this.detail=null;this.$('detail').textContent='';this.render();
    try{const page=checkAssessment(await this.request(`${this.base()}?limit=2&after=${encodeURIComponent(this.after)}`),t.scope,null,this.after);if(!this.current(t))return;this.page=page;this.wanted=Math.max(this.wanted,page.as_of_state_version);this.$('list').replaceChildren();for(const row of page.items){const b=document.createElement('button');b.className='object-row';b.textContent=`${row.id} · ${row.assessment.execution_status} / ${row.assessment.scientific_validity} / ${row.assessment.hypothesis_outcome} · ${row.current_activation} @ ${row.checked_at}`;b.addEventListener('click',()=>this.open(row));this.$('list').append(b);}this.$('note').textContent=`原始依赖验证 · 本页 ${page.items.length}；独立评审 NOT_PERFORMED，Goal 未完成。`;if(this.selected)await this.readSelected(t);}
    catch(e){if(this.current(t)){this.blocked=true;this.$('note').textContent=e.status===404?'此项目未安装评估只读接口；不是没有实验。':`来源不可用：${e.message}；保留原 as-of，手动读取恢复。`;}}
    finally{if(this.current(t)){this.reading=false;this.render();this.queue();}}
  }
  async open(row){if(this.reading)return;this.cancel(this.timer);this.timer=null;++this.serial;const t=this.ticket();this.selected={id:row.id,experiment_id:row.experiment_id,attempt_id:row.attempt_id};this.reading=true;this.detail=null;this.$('detail').textContent='';this.render();try{await this.readSelected(t);}catch(e){if(this.current(t)){this.blocked=true;this.$('note').textContent=`证据未读取：${e.message}；不推断实验结论。`;}}finally{if(this.current(t)){this.reading=false;this.render();this.queue();}}}
  async readSelected(t){const v=await this.request(`${this.base()}/${encodeURIComponent(this.selected.id)}`);if(!this.current(t))return;this.detail=checkAssessment(v,t.scope,this.selected);this.$('detail').textContent=JSON.stringify(this.detail,null,2);}
}

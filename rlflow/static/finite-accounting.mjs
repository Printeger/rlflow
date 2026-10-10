const closed=(v,keys)=>v!==null && typeof v==='object' && !Array.isArray(v) && Object.keys(v).sort().join()===keys.slice().sort().join();
const id=v=>typeof v==='string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(v);
const count=v=>Number.isSafeInteger(v) && v>=0;
const time=v=>typeof v==='string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$/.test(v) && Number.isFinite(Date.parse(v));
const hash=v=>typeof v==='string' && /^sha256:[0-9a-f]{64}$/.test(v);
const fail=()=>{throw new Error('原预算或共享池来源不一致');};
const dimensions=['model_sessions','model_input_tokens','model_output_tokens','gpu_device_seconds','experiment_starts','experiment_retries','wall_seconds'];
const fields=['limit','consumed','reserved','unknown_exposure','available','overrun'];
const decimal=v=>typeof v==='string' && /^(0|[1-9][0-9]{0,18})$/.test(v) && BigInt(v)<=9223372036854775807n;
export function checkFiniteAccounting(v,s){
  if(!closed(v,['schema_version','project_id','data_mode','store_epoch','as_of_state_version','execution_enabled',
      'task_id','reservation_id','goal_ref','budget','profile','pool','cross_database_atomic','goal_completed']) ||
      v.schema_version!=='1.1' || v.profile!=='ORIGINAL_FINITE_ACCOUNTING' || v.project_id!==s.project ||
      v.data_mode!=='fixture' || s.mode!=='fixture' || v.store_epoch!==s.epoch || !count(v.as_of_state_version) ||
      v.execution_enabled!==false || v.cross_database_atomic!==false || v.goal_completed!==false ||
      ![v.task_id,v.reservation_id,v.goal_ref].every(id))fail();
  const b=v.budget,p=v.pool;
  if(!closed(b,['profile','observed_at','entry_id','entry_sha256','recorded_state_version','reservation_status',
      'reservation_recorded_state_version','balances','actual_cost_status','source_coverage']) ||
      b.profile!=='ORIGINAL_GOAL_LEDGER_INT64_DECIMAL' || !time(b.observed_at) ||
      !/^budget_entry_[0-9a-f]{64}$/.test(b.entry_id) || !hash(b.entry_sha256) ||
      !count(b.recorded_state_version) || b.recorded_state_version<1 || b.recorded_state_version>v.as_of_state_version ||
      !count(b.reservation_recorded_state_version) || b.reservation_recorded_state_version<1 || b.reservation_recorded_state_version>b.recorded_state_version ||
      !['HELD','UNKNOWN','SETTLED'].includes(b.reservation_status) || b.actual_cost_status!=='UNKNOWN' ||
      b.source_coverage!=='ORIGINAL_EVENT_VERIFIED' || !closed(b.balances,dimensions))fail();
  for(const row of Object.values(b.balances)){
    if(!closed(row,fields) || !Object.values(row).every(decimal))fail();
    const {limit,consumed,reserved,unknown_exposure,available,overrun}=Object.fromEntries(Object.entries(row).map(([k,v])=>[k,BigInt(v)]));
    const exposure=consumed+reserved;
    if(exposure>9223372036854775807n || unknown_exposure>reserved ||
        available!==(limit>exposure?limit-exposure:0n) || overrun!==(exposure>limit?exposure-limit:0n))fail();
  }
  if(!closed(p,['profile','pool_id','as_of_pool_version','observed_at','capacity','project_occupied','occupied',
      'coverage','execution_enabled','release_enabled','process_status']) || p.profile!=='ORIGINAL_DURABLE_SHARED_POOL' ||
      !id(p.pool_id) || !time(p.observed_at) || p.capacity!==3 ||
      !count(p.project_occupied) || p.project_occupied>3 || p.execution_enabled!==false || p.release_enabled!==false ||
      p.process_status!=='NOT_OBSERVED' ||
      !(p.coverage==='PROJECT_ONLY' && p.occupied===null && p.as_of_pool_version===null || p.coverage==='ALL_REGISTERED_PROJECTS' &&
        count(p.as_of_pool_version) && count(p.occupied) && p.occupied>=p.project_occupied && p.occupied<=3))fail();
  return v;
}

export class FiniteAccountingPanel{
  constructor({context,request,schedule=(f,n)=>setTimeout(f,n),cancel=id=>clearTimeout(id)}){
    Object.assign(this,{context,request,schedule,cancel,serial:0});this.$=id=>document.getElementById('finite-accounting-'+id);
    this.$('refresh').addEventListener('click',()=>this.load());this.clear();
  }
  scope(){const c=this.context();return c?{project:c.project,mode:c.mode,epoch:c.epoch,identity:c.session.principal_id,authGeneration:c.authGeneration}:null;}
  current(t){return t.serial===this.serial && JSON.stringify(t.scope)===JSON.stringify(this.scope());}
  clear(){++this.serial;this.cancel(this.timer);this.timer=null;this.reading=false;this.blocked=false;this.floor=0;this.poolFloor=null;this.value=null;this.last=null;this.bound=null;this.connectionState='UNKNOWN';this.$('detail').textContent='';this.$('note').textContent='UNKNOWN / 尚未读取原账本或原池；无源不表示零。';this.$('refresh').disabled=false;}
  bind(){const s=JSON.stringify(this.scope());if(this.bound!==null && this.bound!==s)this.clear();this.bound=s;const c=this.context();if(count(c?.version))this.floor=Math.max(this.floor,c.version);}
  changed(version){if(!count(version))return;this.bind();this.floor=Math.max(this.floor,version);this.queue();}
  connection(value){const reconnect=!['LIVE','CATCHING UP'].includes(this.connectionState) && ['LIVE','CATCHING UP'].includes(value);this.connectionState=value;if(reconnect)this.blocked=false;this.bind();this.queue();}
  queue(){if(this.timer!==null || this.reading || this.blocked || !this.value || this.value.as_of_state_version>=this.floor || !['LIVE','CATCHING UP'].includes(this.connectionState))return;const t={serial:this.serial,scope:this.scope()};this.timer=this.schedule(()=>{this.timer=null;if(this.current(t))this.load(true);},1000);}
  async load(automatic=false){
    this.bind();if(this.reading)return;if(this.scope()?.mode!=='fixture'){this.clear();return;}
    if(!automatic)this.blocked=false;this.cancel(this.timer);this.timer=null;
    const t={serial:this.serial,scope:this.scope()};this.reading=true;this.$('refresh').disabled=true;
    try{
      const v=await this.request(`/api/v1/projects/${encodeURIComponent(t.scope.project)}/finite-accounting`);
      if(!this.current(t))return;checkFiniteAccounting(v,t.scope);
      if(this.last && (v.as_of_state_version<this.last.as_of_state_version ||
          v.pool.pool_id!==this.last.pool.pool_id ||
          v.task_id!==this.last.task_id || v.reservation_id!==this.last.reservation_id || v.goal_ref!==this.last.goal_ref))fail();
      if(count(v.pool.as_of_pool_version) && this.poolFloor!==null && v.pool.as_of_pool_version<this.poolFloor)fail();
      if(count(v.pool.as_of_pool_version))this.poolFloor=v.pool.as_of_pool_version;
      this.value=this.last=v;this.floor=Math.max(this.floor,v.as_of_state_version);this.$('detail').textContent=JSON.stringify(v,null,2);
      this.$('note').textContent=`原Goal预算 as-of ${v.as_of_state_version} · 本项目持久占槽 ${v.pool.project_occupied}/3 · 全池 ${v.pool.occupied ?? '未授权读取'} (独立版本 ${v.pool.as_of_pool_version ?? '未授权'})；不是跨库原子快照/当前进程或GPU观测，实际费用 UNKNOWN。其他项目池变化需重新读取。`;
    }catch(e){if(this.current(t)){this.blocked=true;this.value=null;this.$('detail').textContent='';this.$('note').textContent=`UNKNOWN (${e.status===404?'未安装原有限账本读取':e.message})；不显示零/满额/已退款，不自动重试。`;}}
    finally{if(this.current(t)){this.reading=false;this.$('refresh').disabled=false;this.queue();}}
  }
}

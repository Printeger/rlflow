import {PendingCommand} from './goal-view.mjs';
import {checkFixtureDetail,checkFixtureReceipt} from './fixture-view.mjs';
const closed=(v,keys)=>v && typeof v==='object' && !Array.isArray(v) && Object.keys(v).sort().join()===keys.slice().sort().join();
const meta=['schema_version','project_id','data_mode','store_epoch','as_of_state_version','execution_enabled'];
const fail=()=>{throw new Error('CPU Unit 来源不一致；未启用动作');};
export function checkCpuUnit(v,s){
  if(!closed(v,[...meta,'task','control_api_installed','original_owner_available','profile','last_sdk_status','cancel_requested','goal_completed','independent_review_status']) ||
    v.profile!=='FIXED_CPU_PI_TRIAL_UNIT' || v.control_api_installed!==true || typeof v.original_owner_available!=='boolean' || typeof v.cancel_requested!=='boolean' ||
    v.goal_completed!==false || v.independent_review_status!=='NOT_PERFORMED' ||
    ![null,'EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW','EXPERIMENT_MACHINE_UNAVAILABLE','EXPERIMENT_ASSESSED_CANCELLED','CANCELLED_SCOPE_STOPPED','UNKNOWN_CLEANUP_REQUIRED'].includes(v.last_sdk_status) ||
    v.task?.kind!=='LOCAL_CPU_NUMERICAL_TRIAL' || v.task?.authorization!=='LOCAL_CPU_TRIAL_ONLY')fail();
  const detail=Object.fromEntries([...meta,'task'].map(k=>[k,v[k]]));
  detail.task={...v.task,kind:'PROTOCOL_CONFORMANCE',authorization:'LOCAL_PROTOCOL_ONLY'};
  checkFixtureDetail(detail,s,v.task);return v;
}
export function checkCpuUnitReceipt(v,body,actor){
  if(body.action==='START_FIXED_CPU')return checkFixtureReceipt(v,body,actor);
  if(!closed(v,['schema_version','command_id','action','status','accepted_state_version','request_hash','actor_id','task_id','recorded_phase','execution_status','native_execution_enabled','arbitrary_tree_stop','duplicate']) ||
    v.schema_version!=='1.1' || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(v.command_id) || v.action!==body.action || v.status!=='ACCEPTED' ||
    !Number.isSafeInteger(v.accepted_state_version) || v.accepted_state_version<1 || !/^sha256:[0-9a-f]{64}$/.test(v.request_hash) ||
    v.actor_id!==actor || v.task_id!==body.task_id || v.recorded_phase!=='STOP_INTENT_ACCEPTED' || v.execution_status!=='UNKNOWN' ||
    v.native_execution_enabled!==false || v.arbitrary_tree_stop!==false || typeof v.duplicate!=='boolean')fail();return v;
}
export class OriginalUnitPanel{
  constructor({context,request,schedule=(f,n)=>setTimeout(f,n),cancel=id=>clearTimeout(id)},profile){
    Object.assign(this,{context,request,schedule,cancel,serial:0,unitProfile:profile});this.$=id=>document.getElementById(profile.path+'-'+id);
    this.$('refresh').addEventListener('click',()=>this.load());
    for(const kind of ['run','stop']){
      this.$(kind).addEventListener('click',()=>this.command(kind));
      this.$(kind+'-retry').addEventListener('click',()=>this.send(kind));
      this.$(kind+'-abandon').addEventListener('click',()=>{this[kind]?.invalidate();this[kind]=null;this.buttons();this.note('只清除本地意图；没有取消服务器执行。');});
    }
    this.clear();
  }
  scope(){const c=this.context();return c?{project:c.project,mode:c.mode,epoch:c.epoch,identity:c.session.principal_id,authGeneration:c.authGeneration}:null;}
  ticket(){return {serial:this.serial,scope:this.scope()};}
  current(t){return t.serial===this.serial && JSON.stringify(t.scope)===JSON.stringify(this.scope());}
  base(){return `/api/v1/projects/${encodeURIComponent(this.scope().project)}/${this.unitProfile.path}`;}
  note(v){this.$('note').textContent=v;}
  clear(){
    ++this.serial;this.cancel(this.timer);this.timer=null;this.reading=false;this.profile=null;this.floor=0;this.boundScope=null;this.blocked=false;this.connectionState='UNKNOWN';
    for(const kind of ['run','stop']){this[kind]?.invalidate();this[kind]=null;this.$(kind+'-receipt').textContent='';}
    this.$('detail').textContent='';this.note('尚未读取；不会自动执行。');this.buttons();
  }
  bind(){const s=JSON.stringify(this.scope());if(s!==this.boundScope){this.boundScope=s;this.floor=0;}const c=this.context();if(Number.isSafeInteger(c?.version))this.floor=Math.max(this.floor,c.version);}
  buttons(){
    this.bind();const c=this.context(),operator=c?.session.kind==='human' && c.session.roles.includes('operator');
    const live=operator && c?.mode==='fixture' && this.profile?.original_owner_available;
    this.$('run').disabled=!(live && !this.blocked && !this.run && !this.stop && !this.reading && !this.profile.cancel_requested && this.profile.task.recorded_phase==='REGISTER_NO_HANDOFF' && this.profile.as_of_state_version>=this.floor);
    // Emergency STOP intentionally does not wait for a RUN/read or fresh CAS.
    this.$('stop').disabled=!(live && !this.stop);
    this.$('refresh').disabled=this.reading;
    for(const kind of ['run','stop']){
      const p=this[kind];this.$(kind+'-retry').hidden=p?.status!=='UNKNOWN';this.$(kind+'-abandon').hidden=p?.status!=='UNKNOWN';
      this.$(kind+'-retry').disabled=p?.status==='IN_FLIGHT';
    }
    this.$('live').textContent=`${this.connectionState} · Task as-of ${this.profile?.as_of_state_version ?? 'UNKNOWN'} · 持久版本 ${this.floor} · 当前运行 UNKNOWN / 资源 NOT_OBSERVED；机器结论不等于独立 Review。`;
  }
  changed(v){if(!Number.isSafeInteger(v) || v<0)return;this.bind();this.floor=Math.max(this.floor,v);this.buttons();this.queue();}
  connection(v){const recovered=!['LIVE','CATCHING UP'].includes(this.connectionState) && ['LIVE','CATCHING UP'].includes(v);this.connectionState=v;if(recovered)this.blocked=false;this.buttons();this.queue();}
  queue(){if(this.timer!==null || this.reading || this.blocked || !this.profile || this.profile.as_of_state_version>=this.floor || !['LIVE','CATCHING UP'].includes(this.connectionState))return;const t=this.ticket();this.timer=this.schedule(()=>{this.timer=null;if(this.current(t))this.load(true);},1000);}
  async load(automatic=false){
    if(this.reading)return;if(!this.scope() || this.scope().mode!=='fixture'){this.clear();return;}
    this.cancel(this.timer);this.timer=null;if(!automatic)this.blocked=false;
    const t=this.ticket();this.reading=true;this.buttons();
    try{const v=await this.request(this.base());if(!this.current(t))return;this.unitProfile.check(v,t.scope);if(this.profile && v.as_of_state_version<this.profile.as_of_state_version)fail();this.profile=v;this.floor=Math.max(this.floor,v.as_of_state_version);this.$('detail').textContent=JSON.stringify(v,null,2);this.note(`原事件验证 · ${v.last_sdk_status || '尚无机器验收'} · 独立 Review NOT_PERFORMED · Goal 未完成。`);}
    catch(e){if(this.current(t)){this.blocked=true;this.note(e.status===404?this.unitProfile.notInstalled:`来源不可用 (${e.message})；保留 as-of，不推断当前运行。`);}}
    finally{if(this.current(t)){this.reading=false;this.buttons();this.queue();}}
  }
  command(kind){
    this.buttons();if(this.$(kind).disabled)return;
    const body={action:kind==='run'?this.unitProfile.start:this.unitProfile.stop,task_id:this.profile.task.id};
    if(kind==='run')body.expected_state_version=this.profile.as_of_state_version;
    this[kind]=new PendingCommand(this.scope(),body,this.unitProfile.path+'_web_'+crypto.randomUUID());this.send(kind);
  }
  async send(kind){
    const p=this[kind],t=this.ticket();if(!p || !p.matches(t.scope))return;let intent;try{intent=p.begin(t.scope);}catch{return;}
    this.buttons();this.note(kind==='stop'?'提交本范围紧急 STOP；接收不等于 FREE。':this.unitProfile.runNote);
    try{
      const v=await this.request(this.base()+'/commands',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':this.context().session.csrf_token,'Idempotency-Key':intent.key},body:intent.body});
      if(!this.current(t) || this[kind]!==p)return;this.unitProfile.receipt(v,JSON.parse(intent.body),t.scope.identity);
      this.floor=Math.max(this.floor,v.accepted_state_version);
      this.$(kind+'-receipt').textContent=JSON.stringify(v,null,2);
      if(kind==='stop'){p.unknown();p.acceptedStop=true;}else{p.finish();this[kind]=null;}
      this.note('原意图 ACCEPTED；不是当前执行或资源 FREE 证明。');this.buttons();await this.load();
    }catch(e){if(!this.current(t) || this[kind]!==p)return;p.unknown();this.note('结果 UNKNOWN；仅手动重试原 body/key。Run 不重新派发，STOP 继续原 scope 清理。');this.buttons();}
  }
}

export class CpuUnitPanel extends OriginalUnitPanel{
  constructor(options){super(options,{path:'cpu-unit',start:'START_FIXED_CPU',stop:'CANCEL_FIXED_CPU_TRIAL',
    check:checkCpuUnit,receipt:checkCpuUnitReceipt,notInstalled:'此项目未安装原 CPU Unit 控制。',
    runNote:'提交已批准 CPU 实验一次执行；不会调用模型/GPU。'});}
}

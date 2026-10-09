import {checkCpuUnitReceipt} from './cpu-unit-panel.mjs';
const closed=(v,keys)=>v && typeof v==='object' && !Array.isArray(v) && Object.keys(v).sort().join()===keys.slice().sort().join();
const id=v=>typeof v==='string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(v);
const hash=v=>typeof v==='string' && /^sha256:[0-9a-f]{64}$/.test(v);
const fail=()=>{throw Error('原全集 STOP 来源合同被拒绝');};
export function checkFiniteScope(v){
  if(!closed(v,['schema_version','profile','scope_sha256','data_mode','execution_enabled','original_owner_available','stop_enabled','items','goal_completed','independent_review_status']) ||
    v.schema_version!=='1.1' || v.profile!=='ORIGINAL_FIXED_BOUND_UNITS_ONLY' || !hash(v.scope_sha256) || v.data_mode!=='fixture' ||
    v.execution_enabled!==false || typeof v.original_owner_available!=='boolean' || typeof v.stop_enabled!=='boolean' ||
    (v.stop_enabled && !v.original_owner_available) || v.goal_completed!==false || v.independent_review_status!=='NOT_PERFORMED' ||
    !Array.isArray(v.items) || !v.items.length || v.items.length>3)fail();
  let previous='';
  for(const r of v.items){
    if(!closed(r,['project_id','store_epoch','task_id','stop_action']) || !['project_id','store_epoch','task_id'].every(k=>id(r[k])) ||
      r.project_id<=previous || !['CANCEL_FIXED_CPU_TRIAL','CANCEL_FIXED_ENGINEERING'].includes(r.stop_action))fail();
    previous=r.project_id;
  }
  return v;
}
export function checkFiniteResult(v,profile,actor,expectedId){
  if(!closed(v,['schema_version','command_id','action','duplicate','status','scope','durable_aggregate_receipt','cleanup_resume','items','goal_completed','independent_review_status']) ||
    v.schema_version!=='1.1' || v.command_id!==expectedId || v.action!=='CANCEL_ORIGINAL_FINITE_UNITS' || typeof v.duplicate!=='boolean' || typeof v.cleanup_resume!=='boolean' ||
    !['ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN','PARTIAL_OR_UNKNOWN'].includes(v.status) || v.scope!=='ORIGINAL_FIXED_BOUND_UNITS_ONLY' ||
    v.durable_aggregate_receipt!==false || v.goal_completed!==false || v.independent_review_status!=='NOT_PERFORMED' ||
    !Array.isArray(v.items) || v.items.length!==profile.items.length)fail();
  for(const [i,r] of v.items.entries()){
    const target=profile.items[i];
    if(!closed(r,['project_id','store_epoch','task_id','intent','intent_status','cleanup_status','post_cleanup_status','error_type','goal_completed','independent_review_status']) ||
      ['project_id','store_epoch','task_id'].some(k=>r[k]!==target[k]) || !['ACCEPTED','UNKNOWN'].includes(r.intent_status) ||
      !['ORIGINAL_SCOPE_STOPPED','UNKNOWN'].includes(r.cleanup_status) || !['RETURNED','UNKNOWN'].includes(r.post_cleanup_status) ||
      (r.error_type!==null && !id(r.error_type)) || r.goal_completed!==false || r.independent_review_status!=='NOT_PERFORMED')fail();
    if(r.intent_status==='ACCEPTED')checkCpuUnitReceipt(r.intent,{action:target.stop_action,task_id:target.task_id},actor);
    else if(r.intent!==null)fail();
  }
  const complete=v.items.every(r=>r.intent_status==='ACCEPTED' && r.cleanup_status==='ORIGINAL_SCOPE_STOPPED' && r.post_cleanup_status==='RETURNED');
  if((v.status==='ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN')!==complete)fail();
  return v;
}
async function commandId(scope,actor,key){
  const bytes=new TextEncoder().encode(JSON.stringify([scope,actor,key]));
  const digest=await crypto.subtle.digest('SHA-256',bytes);
  return 'finite_stop_'+[...new Uint8Array(digest)].map(n=>n.toString(16).padStart(2,'0')).join('');
}
export class FiniteStopPanel{
  constructor({context,request}){
    Object.assign(this,{context,request,serial:0});this.$=id=>document.getElementById('finite-stop-'+id);
    this.$('refresh').addEventListener('click',()=>this.load());
    this.$('stop').addEventListener('click',()=>this.command());
    this.$('retry').addEventListener('click',()=>this.send(false));
    this.$('resume').addEventListener('click',()=>this.send(true));
    this.clear();
  }
  scope(){const c=this.context();return c?{project:c.project,epoch:c.epoch,actor:c.session.principal_id,auth:c.authGeneration}:null;}
  ticket(){return {serial:this.serial,scope:JSON.stringify(this.scope())};}
  current(t){return t.serial===this.serial && t.scope===JSON.stringify(this.scope());}
  clear(){++this.serial;this.profile=null;this.intent=null;this.result=null;this.reading=false;this.sending=false;this.$('scope').textContent='';this.$('receipt').textContent='';this.$('note').textContent='尚未读取；不会自动 POST。';this.buttons();}
  buttons(){
    const c=this.context();
    this.$('stop').disabled=!(c?.session.kind==='human' && c.session.roles.includes('operator') && this.profile?.stop_enabled && !this.intent);
    this.$('refresh').disabled=this.reading;
    this.$('retry').hidden=!this.intent || !!this.result;this.$('retry').disabled=this.sending;
    this.$('resume').hidden=this.result?.status!=='PARTIAL_OR_UNKNOWN';this.$('resume').disabled=this.sending;
  }
  async load(){
    if(!this.scope() || this.context().mode!=='fixture'){this.clear();return;}
    if(this.reading)return;const t=this.ticket();this.reading=true;this.buttons();
    try{
      const v=checkFiniteScope(await this.request('/api/v1/finite-host'));if(!this.current(t))return;
      if(this.profile && this.profile.scope_sha256!==v.scope_sha256){this.clear();return;}
      this.profile=v;this.$('scope').textContent=JSON.stringify(v,null,2);
      this.$('note').textContent='仅原绑定全集；先全部锁存取消，再逐原 scope 收尾。不是整个 Goal / 任意树 STOP。';
    }catch(e){if(this.current(t)){this.profile=null;this.$('note').textContent=e.status===404?'此应用未安装或未授权原全集 STOP。':`来源不可用 (${e.message})；不启用新动作。`;}}
    finally{if(this.current(t)){this.reading=false;this.buttons();}}
  }
  command(){this.buttons();if(this.$('stop').disabled)return;this.intent={key:'finite_web_'+crypto.randomUUID(),body:{action:'CANCEL_ORIGINAL_FINITE_UNITS'},profile:JSON.parse(JSON.stringify(this.profile)),actor:this.scope().actor};this.send(false);}
  async send(resume){
    if(this.sending || !this.intent || !this.scope())return;
    const t=this.ticket(),p=this.intent;this.sending=true;this.buttons();
    this.$('note').textContent=resume?'显式继续原未知 scope 收尾；不新建执行或重复 STOP 事实。':'提交原全集紧急 STOP；不等待单项目 Run。';
    try{
      const expected=await commandId(p.profile.scope_sha256,p.actor,p.key);if(!this.current(t))return;
      const value=await this.request('/api/v1/finite-host/commands'+(resume?'?resume_cleanup=1':''),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':this.context().session.csrf_token,'Idempotency-Key':p.key},body:JSON.stringify(p.body)});
      if(!this.current(t))return;
      this.result=checkFiniteResult(value,p.profile,p.actor,expected);this.$('receipt').textContent=JSON.stringify(this.result,null,2);
      this.$('note').textContent=this.result.status==='PARTIAL_OR_UNKNOWN'?'部分/UNKNOWN：不证明全部释放；核对原因后才显式续原未知收尾。':'原 scope 已停止（as-of）；不是持久全集回执、整个 Goal 或独立 Review 完成。';
    }catch(e){if(this.current(t)){this.result=null;this.$('receipt').textContent='';this.$('note').textContent=`全集结果 UNKNOWN (${e.message})；只手动重试原 body/key，不自动重新提交。`;}}
    finally{if(this.current(t)){this.sending=false;this.buttons();}}
  }
}

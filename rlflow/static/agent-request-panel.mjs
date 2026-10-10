import {parseProposalJSON} from './goal-view.mjs';
import {checkFiniteResult} from './finite-stop-panel.mjs';
const id=/^request_[0-9a-f]{64}$/,hash=/^sha256:[0-9a-f]{64}$/;
const statuses=new Set(['AWAITING_HUMAN','UNKNOWN','STALE','ADOPTED']);
function scopeMatches(value,scope) {
  return value && value.project_id===scope.project && value.data_mode===scope.mode && value.store_epoch===scope.epoch;
}
const closed=(v,keys)=>v && typeof v==='object' && !Array.isArray(v) && Object.keys(v).sort().join()===keys.slice().sort().join();
const identifier=v=>typeof v==='string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(v);
function checkStopRequest(v,scope,privateView) {
  const keys=['schema_version','request_id','project_id','data_mode','store_epoch','action','request_hash','submitted_by','status','execution_enabled','stop_scope','result'];
  if(privateView)keys.push('forwarded_by','original_owner_available');
  if(!closed(v,keys) || !scopeMatches(v,scope) || v.data_mode!=='fixture' || v.schema_version!=='1.0' ||
    !id.test(v.request_id) || !hash.test(v.request_hash) || v.execution_enabled!==false ||
    !closed(v.submitted_by,['id','kind']) || !identifier(v.submitted_by.id) || v.submitted_by.kind!=='agent' ||
    !['AWAITING_HUMAN','UNKNOWN','STOPPED_AS_OF_RETURN','PARTIAL_OR_UNKNOWN'].includes(v.status) ||
    !closed(v.stop_scope,['scope_sha256','items']) || !hash.test(v.stop_scope.scope_sha256) ||
    !Array.isArray(v.stop_scope.items) || !v.stop_scope.items.length || v.stop_scope.items.length>3)
    throw Error('原有限全集 STOP 建议无效');
  let previous='';
  for(const r of v.stop_scope.items) {
    if(!closed(r,['project_id','data_mode','store_epoch','task_id','stop_action']) || r.data_mode!=='fixture' ||
      !['project_id','store_epoch','task_id'].every(k=>identifier(r[k])) || r.project_id<=previous ||
      !['CANCEL_FIXED_CPU_TRIAL','CANCEL_FIXED_ENGINEERING'].includes(r.stop_action))throw Error('明确原全集范围无效');
    previous=r.project_id;
  }
  if(!v.stop_scope.items.some(r=>r.project_id===scope.project && r.store_epoch===scope.epoch))throw Error('建议锚点不在原全集');
  if(privateView && (typeof v.original_owner_available!=='boolean' ||
    !(v.forwarded_by===null || closed(v.forwarded_by,['id','kind']) && identifier(v.forwarded_by.id) && v.forwarded_by.kind==='human')))
    throw Error('原转交主体不可用');
  if(v.result===null) {
    if(!['AWAITING_HUMAN','UNKNOWN'].includes(v.status))throw Error('未证明清理不得显示成功');
  } else {
    if(!['STOPPED_AS_OF_RETURN','PARTIAL_OR_UNKNOWN'].includes(v.status) ||
      !/^finite_stop_[0-9a-f]{64}$/.test(v.result.command_id))throw Error('原 STOP 回执身份无效');
    const actors=new Set((v.result.items || []).filter(r=>r.intent).map(r=>r.intent.actor_id));
    if(actors.size>1 || privateView && (!v.forwarded_by || actors.size && !actors.has(v.forwarded_by.id)))throw Error('原 STOP 主体不匹配');
    checkFiniteResult(v.result,v.stop_scope,v.forwarded_by?.id || [...actors][0],v.result.command_id);
    if((v.status==='STOPPED_AS_OF_RETURN')!==(v.result.status==='ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN'))throw Error('清理状态不匹配');
  }
  if(privateView && (v.status==='AWAITING_HUMAN')!==(v.forwarded_by===null))throw Error('冻结转交状态不匹配');
  return v;
}
export function checkRequest(value,scope,{privateView=false}={}) {
  if(value?.action==='request_finite_stop')return checkStopRequest(value,scope,privateView);
  if(!scopeMatches(value,scope) || value.schema_version!=='1.0' || !id.test(value.request_id) ||
      !hash.test(value.request_hash) || value.action!=='submit_goal' || !statuses.has(value.status) || value.execution_enabled!==false)
    throw new Error('请求范围或状态无效');
  if(value.status==='ADOPTED') {
    const r=value.result;
    if(!r || r.schema_version!=='1.1' || r.action!=='submit_goal' || r.status!=='SUCCEEDED' ||
        r.result?.state!=='DRAFT' || r.result.execution_enabled!==false || !Number.isSafeInteger(r.accepted_state_version))
      throw new Error('缺少原 DRAFT 回执');
  } else if(value.result!==null) throw new Error('未接受请求不得附成功回执');
  if(privateView && (!value.proposal || value.proposal.project_id!==scope.project || value.proposal.data_mode!==scope.mode ||
      value.proposal.schema_version!=='1.1' || !Number.isSafeInteger(value.expected_revision) ||
      value.proposal.contract_version!==value.expected_revision+1 ||
      !(value.forward_expected_version===null || Number.isSafeInteger(value.forward_expected_version))))
    throw new Error('私有精确提案不可用');
  if(privateView) parseProposalJSON(JSON.stringify(value.proposal));
  return value;
}
async function sha(value) {
  const raw=new TextEncoder().encode(JSON.stringify(value));
  const result=await crypto.subtle.digest('SHA-256',raw);
  return [...new Uint8Array(result)].map(v=>v.toString(16).padStart(2,'0')).join('');
}
export async function verifyRequest(value,scope,options={}) {
  const v=checkRequest(value,scope,options);
  if(v.action!=='request_finite_stop')return v;
  const items=v.stop_scope.items,key='forward_'+v.request_id.slice(8);
  const expectedScope='sha256:'+await sha(items.map(r=>[r.project_id,r.store_epoch,r.task_id,r.stop_action]));
  if(v.stop_scope.scope_sha256!==expectedScope)throw Error('原全集 scope hash 不匹配');
  if(v.result) {
    const actors=new Set(v.result.items.filter(r=>r.intent).map(r=>r.intent.actor_id));
    const actor=v.forwarded_by?.id || [...actors][0];
    if(actor && v.result.command_id!=='finite_stop_'+await sha([expectedScope,actor,key]))throw Error('派生原 STOP 命令不匹配');
    for(const [i,row] of v.result.items.entries())if(row.intent) {
      const target=items[i];
      if(row.intent.command_id!=='fixture_command_'+await sha([target.project_id,target.data_mode,target.store_epoch,actor,key]) ||
        row.intent.request_hash!=='sha256:'+await sha({action:target.stop_action,task_id:target.task_id}))throw Error('原 scope 命令/hash 不匹配');
    }
  }
  return v;
}

// No auto-forwarding or automatic retries. All human writes require consent.
export class AgentRequestPanel {
  constructor({context,request}) {
    this.context=context;this.request=request;this.serial=0;this.selected=null;this.busy=false;
    this.$=id=>document.getElementById(id);
    this.$('agent-request-refresh').addEventListener('click',()=>this.load());
    this.$('agent-request-consent').addEventListener('change',()=>this.buttons());
    this.$('agent-request-forward').addEventListener('click',()=>this.forward());
    this.$('agent-request-resume').addEventListener('click',()=>this.forward(true));
    this.$('agent-request-close').addEventListener('click',()=>this.clear());
    this.clear();
  }
  scope() {
    const c=this.context();
    return c && c.session.kind==='human' && c.session.roles.includes('operator') ?
      {project:c.project,mode:c.mode,epoch:c.epoch,identity:c.session.principal_id,authGeneration:c.authGeneration} : null;
  }
  ticket() {return {serial:this.serial,scope:this.scope()};}
  current(t) {return t.serial===this.serial && JSON.stringify(t.scope)===JSON.stringify(this.scope());}
  url() {return `/api/v1/projects/${encodeURIComponent(this.scope().project)}/agent-requests`;}
  note(text) {this.$('agent-request-note').textContent=text;}
  clear() {
    ++this.serial;this.selected=null;this.busy=false;
    this.$('agent-request-list').replaceChildren();this.$('agent-request-view').textContent='';
    this.$('agent-request-consent').checked=false;this.$('agent-request-private').hidden=true;
    this.note('建议不是核心事实；仅 human operator 可读取并明确转交。');this.buttons();
  }
  buttons() {
    const c=this.context(),v=this.selected,s=this.scope();
    const canForward=v && ['AWAITING_HUMAN','UNKNOWN'].includes(v.status) &&
      (!v.forwarded_by || v.forwarded_by.id===s?.identity) &&
      (v.action!=='request_finite_stop' || v.original_owner_available);
    this.$('agent-request-forward').disabled=!s || this.busy || !canForward ||
      !this.$('agent-request-consent').checked || c?.connection!=='LIVE';
    const resume=this.$('agent-request-resume');
    resume.hidden=v?.action!=='request_finite_stop' || !['UNKNOWN','PARTIAL_OR_UNKNOWN'].includes(v.status);
    resume.disabled=resume.hidden || !s || this.busy || !v?.original_owner_available ||
      v?.forwarded_by?.id!==s?.identity || !this.$('agent-request-consent').checked || c?.connection!=='LIVE';
    this.$('agent-request-forward').textContent=v?.action==='request_finite_stop'?'明确转交原有限全集 STOP':'明确转交原草案服务';
    this.$('agent-request-consent-text').textContent=v?.action==='request_finite_stop'?
      '我已核对原全集每个 project/epoch/task/action 与 hash，明确转交停止全部列出的原绑定执行；不是仅停止当前项目或整个 Goal。':
      '我已核对完整 proposal 与请求 hash，只将建议转交为不可执行 DRAFT；这不是批准。';
    this.$('agent-request-refresh').disabled=!s || this.busy;
    this.$('agent-request-close').disabled=this.busy;
  }
  connection() {this.buttons();}
  async load() {
    if(!this.scope() || this.busy) {this.buttons();return;}
    this.clear();const t=this.ticket();
    try {
      const page=await this.request(this.url());
      if(!this.current(t)) return;
      if(!scopeMatches(page,t.scope) || !Array.isArray(page.items) || page.items.length>32) throw new Error('有界请求列表无效');
      const values=await Promise.all(page.items.map(v=>verifyRequest(v,t.scope)));
      if(!this.current(t))return;
      if(new Set(values.map(v=>v.request_id)).size!==values.length) throw new Error('重复请求');
      for(const v of values) {
        const button=document.createElement('button');button.type='button';button.className='goal-row';
        button.dataset.requestId=v.request_id;button.textContent=`${v.request_id} · ${v.status} · 建议 / 不可执行`;
        button.addEventListener('click',()=>this.open(v.request_id));this.$('agent-request-list').append(button);
      }
      this.note(`${values.length} 个真实建议；保存不代表已被核心接受。`);this.buttons();
    } catch(error) {if(this.current(t)){this.clear();this.note(error.status===404 ? '本项目未显式启用请求入口。' : `请求不可用：${error.message}`);}}
  }
  async open(rid) {
    if(!this.scope() || this.busy) return;
    ++this.serial;this.selected=null;this.$('agent-request-consent').checked=false;this.buttons();const t=this.ticket();
    this.$('agent-request-private').hidden=true;this.$('agent-request-view').textContent='';
    try {
      const v=await verifyRequest(await this.request(`${this.url()}/${rid}`),t.scope,{privateView:true});
      if(!this.current(t)) return;
      if(v.request_id!==rid) throw new Error('请求身份不匹配');
      this.selected=v;this.$('agent-request-private').hidden=false;
      this.$('agent-request-view').textContent=JSON.stringify(v,null,2);
      this.note(v.action==='request_finite_stop' ?
        (v.status==='STOPPED_AS_OF_RETURN' ? '原列出 scope 已停止（as-of）；不是持久全集证明、整个 Goal 或独立 Review 完成。' :
          v.status==='PARTIAL_OR_UNKNOWN' ? '部分/UNKNOWN，不证明全部释放；普通重试只读，核对后才显式继续原未知收尾。' :
          !v.original_owner_available ? '原执行 owner 不可用；不从耐久意图重建物理清理证明，直接紧急 STOP 入口保持独立。' :
          '核对完整原绑定全集；耐久冻结转交后调用原 STOP。建议入口需要 inbox I/O；直接紧急 STOP 保持独立。') :
        v.status==='ADOPTED' ? '原核心已接受 DRAFT；仍未批准、未执行。' :
        v.status==='STALE' ? '冻结命令未被接受且版本陈旧；需新显式请求，不自动改版本。' :
        v.status==='UNKNOWN' ? '已冻结转交意图，接受结果未知；读取/手动恢复同一命令，不能换主体或键。' : '请核对完整 proposal 与 request_hash，再明确转交；不是批准。');
      this.buttons();
    } catch(error) {if(this.current(t)){this.clear();this.note(`原请求未验证：${error.message}`);}}
  }
  async forward(resumeCleanup=false) {
    this.buttons();if(this.$(resumeCleanup?'agent-request-resume':'agent-request-forward').disabled) return;
    const v=this.selected,t=this.ticket(),c=this.context();this.busy=true;this.buttons();
    const expected=v.forward_expected_version===null ? c.version : v.forward_expected_version;
    const stop=v.action==='request_finite_stop';
    try {
      const result=await verifyRequest(await this.request(`${this.url()}/${v.request_id}/${stop?'forward-stop':'forward'}`,{method:'POST',
        headers:{'Content-Type':'application/json','X-CSRF-Token':c.session.csrf_token},
        body:JSON.stringify(stop?{request_hash:v.request_hash,resume_cleanup:resumeCleanup}:{request_hash:v.request_hash,expected_version:expected})}),t.scope,{privateView:true});
      if(!this.current(t)) return;
      if(result.request_id!==v.request_id || result.request_hash!==v.request_hash) throw new Error('原请求回执不匹配');
      this.busy=false;await this.open(v.request_id);
    } catch(error) {
      if(this.current(t)) {
        this.busy=false;this.$('agent-request-consent').checked=false;this.buttons();
        // Reconcile is read-only. Do not submit a replacement or rebase.
        await this.open(v.request_id);
        if(JSON.stringify(this.scope())===JSON.stringify(t.scope) && this.selected?.request_id===v.request_id && !['ADOPTED','STOPPED_AS_OF_RETURN'].includes(this.selected.status))
          this.note(`转交未确认 (${error.status || '响应未知'})；已读取原请求，不自动重试。`);
      }
    }
  }
}

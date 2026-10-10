import {parseProposalJSON} from './goal-view.mjs';
const id=/^request_[0-9a-f]{64}$/,hash=/^sha256:[0-9a-f]{64}$/;
const statuses=new Set(['AWAITING_HUMAN','UNKNOWN','STALE','ADOPTED']);
function scopeMatches(value,scope) {
  return value && value.project_id===scope.project && value.data_mode===scope.mode && value.store_epoch===scope.epoch;
}
export function checkRequest(value,scope,{privateView=false}={}) {
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

// No auto-forwarding or automatic retries. All human writes require consent.
export class AgentRequestPanel {
  constructor({context,request}) {
    this.context=context;this.request=request;this.serial=0;this.selected=null;this.busy=false;
    this.$=id=>document.getElementById(id);
    this.$('agent-request-refresh').addEventListener('click',()=>this.load());
    this.$('agent-request-consent').addEventListener('change',()=>this.buttons());
    this.$('agent-request-forward').addEventListener('click',()=>this.forward());
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
      (!v.forwarded_by || v.forwarded_by.id===s?.identity);
    this.$('agent-request-forward').disabled=!s || this.busy || !canForward ||
      !this.$('agent-request-consent').checked || c?.connection!=='LIVE';
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
      const values=page.items.map(v=>checkRequest(v,t.scope));
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
      const v=checkRequest(await this.request(`${this.url()}/${rid}`),t.scope,{privateView:true});
      if(!this.current(t)) return;
      if(v.request_id!==rid) throw new Error('请求身份不匹配');
      this.selected=v;this.$('agent-request-private').hidden=false;
      this.$('agent-request-view').textContent=JSON.stringify(v,null,2);
      this.note(v.status==='ADOPTED' ? '原核心已接受 DRAFT；仍未批准、未执行。' :
        v.status==='STALE' ? '冻结命令未被接受且版本陈旧；需新显式请求，不自动改版本。' :
        v.status==='UNKNOWN' ? '已冻结转交意图，接受结果未知；读取/手动恢复同一命令，不能换主体或键。' : '请核对完整 proposal 与 request_hash，再明确转交；不是批准。');
      this.buttons();
    } catch(error) {if(this.current(t)){this.clear();this.note(`原请求未验证：${error.message}`);}}
  }
  async forward() {
    this.buttons();if(this.$('agent-request-forward').disabled) return;
    const v=this.selected,t=this.ticket(),c=this.context();this.busy=true;this.buttons();
    const expected=v.forward_expected_version===null ? c.version : v.forward_expected_version;
    try {
      const result=checkRequest(await this.request(`${this.url()}/${v.request_id}/forward`,{method:'POST',
        headers:{'Content-Type':'application/json','X-CSRF-Token':c.session.csrf_token},
        body:JSON.stringify({request_hash:v.request_hash,expected_version:expected})}),t.scope,{privateView:true});
      if(!this.current(t)) return;
      if(result.request_id!==v.request_id || result.request_hash!==v.request_hash) throw new Error('原请求回执不匹配');
      this.busy=false;await this.open(v.request_id);
    } catch(error) {
      if(this.current(t)) {
        this.busy=false;this.$('agent-request-consent').checked=false;this.buttons();
        // Reconcile is read-only. Do not submit a replacement or rebase.
        await this.open(v.request_id);
        if(JSON.stringify(this.scope())===JSON.stringify(t.scope) && this.selected?.request_id===v.request_id && this.selected.status!=='ADOPTED')
          this.note(`转交未确认 (${error.status || '响应未知'})；已读取原请求，不自动重试。`);
      }
    }
  }
}

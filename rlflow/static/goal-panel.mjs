import {checkGoalPage,checkGoalReview,checkConfirmation,approvalPayload,PendingCommand,checkCommand,parseProposalJSON} from './goal-view.mjs';

// All writes require an explicit click. No polling, automatic retry or launch.
export class GoalPanel {
  constructor({context,request,onExpired,now=()=>performance.now()}) {
    this.context=context;this.request=request;this.onExpired=onExpired;this.now=now;
    this.serial=0;this.nonceSerial=0;this.page=null;this.review=null;this.confirmation=null;this.pending=null;this.enabled=false;
    this.$=id=>document.getElementById(id);
    this.$('goal-refresh').addEventListener('click',()=>this.load());
    this.$('goal-next').addEventListener('click',()=>this.load(this.page?.next_after));
    this.$('goal-prepare').addEventListener('click',()=>this.prepare());
    this.$('goal-consent').addEventListener('change',()=>this.buttons());
    this.$('goal-approve').addEventListener('click',()=>this.approve());
    this.$('goal-submit').addEventListener('click',()=>this.submit());
    this.$('goal-revoke').addEventListener('click',()=>this.revoke());
    this.$('goal-retry').addEventListener('click',()=>this.send());
    this.$('goal-abandon').addEventListener('click',()=>this.abandon());
    this.$('goal-ttl').addEventListener('input',()=>this.clearConfirmation());
    this.$('goal-json').addEventListener('input',()=>this.clearConfirmation());
    this.$('goal-close').addEventListener('click',()=>this.clearPrivate());
  }
  scope() {
    const c=this.context();
    return c && {project:c.project,mode:c.mode,epoch:c.epoch,identity:c.session.principal_id,authGeneration:c.authGeneration};
  }
  ticket() {return {serial:this.serial,scope:this.scope()};}
  current(t) {return t.serial===this.serial && JSON.stringify(t.scope)===JSON.stringify(this.scope());}
  url() {return `/api/v1/projects/${encodeURIComponent(this.scope().project)}`;}
  role(name) {const c=this.context();return c?.session.kind==='human' && c.session.roles.includes(name);}
  note(value) {this.$('goal-note').textContent=value;}
  clearConfirmation() {
    ++this.nonceSerial;this.confirmation=null;this.$('goal-confirmation').textContent='';this.$('goal-consent').checked=false;this.buttons();
  }
  clearPrivate() {
    ++this.serial;this.review=null;this.clearConfirmation();
    this.$('goal-review').textContent='';this.$('goal-json').value='';this.$('goal-reason').value='';
    this.$('goal-private').hidden=true;this.buttons();
  }
  clear() {
    this.clearPrivate();this.pending?.invalidate();this.pending=null;this.page=null;this.enabled=false;
    this.$('goal-list').replaceChildren();this.$('goal-receipt').textContent='';this.note('尚未读取 Hybrid 合同。');this.buttons();
  }
  changed(version) {
    if (this.confirmation && version>this.confirmation.view.confirmation.expected_version) {
      this.clearConfirmation();this.note('核心版本已更新；请重新读取合同并准备确认。');
    }
  }
  buttons() {
    const blocked=!!this.pending,approver=this.role('approver'),operator=this.role('operator');
    this.$('observer-tag').textContent=this.enabled && (approver || operator) ? 'NON-EXECUTING FACT CONTROL' : 'READ-ONLY OBSERVER';
    this.$('goal-editor').hidden=!operator;
    this.$('goal-submit').disabled=!this.enabled || !operator || blocked;
    this.$('goal-next').disabled=!this.page?.next_after || blocked;
    this.$('goal-prepare').disabled=!this.review || !approver || blocked;
    this.$('goal-approve').disabled=!this.confirmation || !approver || blocked || !this.$('goal-consent').checked;
    this.$('goal-revoke').disabled=!this.review || !approver || blocked || this.review.authority?.recorded_state!=='LEASE_VALIDATION_PENDING';
    this.$('goal-retry').hidden=this.pending?.status!=='UNKNOWN';
    this.$('goal-abandon').hidden=!this.pending || this.pending.status==='IN_FLIGHT';
    this.$('goal-refresh').disabled=blocked;
    this.$('goal-close').disabled=blocked;this.$('goal-json').disabled=blocked;
  }
  async failure(error,t) {
    if (!this.current(t)) return;
    if ([401,403].includes(error.status)) {this.clear();this.onExpired(error);return;}
    this.note(`Hybrid 不可用：${error.message}；未推断执行状态。`);
  }
  async load(after='') {
    if (!this.scope() || this.pending) return;
    this.clearPrivate();const t=this.ticket();this.note('读取真实 Hybrid heads…');
    try {
      const page=checkGoalPage(await this.request(`${this.url()}/goals?${new URLSearchParams({limit:'30',after:after || ''})}`),t.scope,after || '');
      if (!this.current(t)) return;
      this.enabled=true;this.page=page;this.$('goal-list').replaceChildren();
      for (const item of page.items) {
        const button=document.createElement('button');button.type='button';button.className='goal-row';button.dataset.goalRef=item.goal_ref;
        button.textContent=`${item.goal_ref} · revision ${item.contract_revision} · ${item.authority?.recorded_state || 'DRAFT / 无批准'} · HEAD_ONLY / 不可执行`;
        button.disabled=!(this.role('operator') || this.role('approver'));
        button.addEventListener('click',()=>this.open(item));this.$('goal-list').append(button);
      }
      this.note(`本页 ${page.items.length} · as-of core version ${page.as_of_state_version} · HEAD_ONLY；列表不证明授权链或执行。`);
      this.buttons();
    } catch(error) {if(this.current(t) && error.status===404){this.enabled=false;this.note('本项目未启用 Hybrid 控制读取；不提供隐式写入。');this.buttons();}else await this.failure(error,t);}
  }
  async open(item) {
    if(this.pending) return;
    this.clearPrivate();const t=this.ticket();
    try {
      const review=checkGoalReview(await this.request(`${this.url()}/goals/${encodeURIComponent(item.goal_ref)}/review`),t.scope,item);
      if(!this.current(t)) return;
      this.review=review;this.$('goal-private').hidden=false;
      this.$('goal-review').textContent=JSON.stringify(review,null,2);
      this.note(`授权 human 私有合同 · ${review.source_coverage} · as-of ${review.as_of_state_version}；关闭/切换身份会清除。`);this.buttons();
    } catch(error) {await this.failure(error,t);}
  }
  async prepare() {
    if(!this.review || !this.role('approver') || this.pending) return;
    this.clearConfirmation();const nonceTicket=this.nonceSerial,t=this.ticket(),review=this.review,ttl=Number(this.$('goal-ttl').value),started=this.now();
    if(!Number.isSafeInteger(ttl) || ttl<1 || ttl>86400){this.note('批准事实 TTL 必须为1–86400秒。');return;}
    this.$('goal-prepare').disabled=true;
    try {
      const view=checkConfirmation(await this.request(`${this.url()}/goals/${encodeURIComponent(review.contract.id)}/approval-confirmations`,
        {method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':this.context().session.csrf_token},body:JSON.stringify({ttl_seconds:ttl})}),review,t.scope);
      if(!this.current(t) || review!==this.review || nonceTicket!==this.nonceSerial) return;
      if(this.context().version>view.confirmation.expected_version || this.now()-started>=110000){this.note('核心版本/临时确认已陈旧，请重新审阅。');this.buttons();return;}
      this.confirmation={view:structuredClone(view),at:started};
      this.$('goal-confirmation').textContent=JSON.stringify(view,null,2);
      this.note('请审阅服务器精确 proposal、changes、binding 与限制，再明确勾选批准；此确认不启动工作。');this.buttons();
    } catch(error) {await this.failure(error,t);if(this.current(t))this.buttons();}
  }
  async approve() {
    if(!this.confirmation || !this.$('goal-consent').checked || !this.role('approver') || this.pending) return;
    // Server nonce is at most120s and may expire earlier with session. This is
    // only a conservative UI deadline; server session/nonce checks are final.
    if(this.now()-this.confirmation.at>=110000){this.clearConfirmation();this.note('临时确认已陈旧；重新准备，不自动续期。');return;}
    this.start(approvalPayload(this.confirmation.view));
  }
  submit() {
    if(!this.enabled || !this.role('operator') || this.pending || !this.scope()) return;
    try {
      const raw=this.$('goal-json').value;
      const goal=parseProposalJSON(raw),c=this.context();
      if(goal.project_id!==c.project || goal.data_mode!==c.mode || goal.schema_version!=='1.1' || !Number.isSafeInteger(goal.contract_version) || goal.contract_version<1)throw new Error('需要匹配本项目/模式的显式1.1 proposal');
      const envelope={schema_version:'1.1',action:'submit_goal',target:{kind:'project',id:c.project},expected_version:c.version};
      // Preserve the strict original proposal bytes, including numeric spelling.
      // Never normalize ambiguous or rounded operator intent before server gates.
      const body=JSON.stringify(envelope).slice(0,-1)+',"parameters":{"goal":'+raw+',"expected_revision":'+(goal.contract_version-1)+'}}';
      if(new TextEncoder().encode(body).length>256*1024)throw new Error('command包络超出256KiB');
      this.start({...envelope,parameters:{goal,expected_revision:goal.contract_version-1}},body);
    } catch(error) {this.note(`未提交：${error.message}。服务器仍负责完整 schema 校验。`);}
  }
  revoke() {
    if(!this.review || !this.role('approver') || this.pending || this.review.authority?.recorded_state!=='LEASE_VALIDATION_PENDING') return;
    const reason=this.$('goal-reason').value.trim();if(!reason){this.note('撤销需要明确原因。');return;}
    this.start({schema_version:'1.1',action:'revoke',target:{kind:'approval',id:this.review.authority.fact_key},
      expected_version:this.review.as_of_state_version,parameters:{goal_id:this.review.contract.id,
        expected_authority_revision:this.review.authority.authority_revision,reason}});
  }
  start(payload,rawBody=null) {
    this.pending=new PendingCommand(this.scope(),payload,'web_'+crypto.randomUUID(),rawBody);this.buttons();this.send();
  }
  async send() {
    const pending=this.pending;if(!pending || !pending.matches(this.scope())) return;
    const t=this.ticket(),attempt=pending.begin(t.scope);this.buttons();
    try {
      const dto=checkCommand(await this.request(`${this.url()}/commands`,{method:'POST',headers:{'Content-Type':'application/json',
        'X-CSRF-Token':this.context().session.csrf_token,'Idempotency-Key':attempt.key},body:attempt.body}),JSON.parse(attempt.body));
      if(!this.current(t) || pending!==this.pending) return;
      pending.finish();this.pending=null;this.clearPrivate();this.$('goal-receipt').textContent=JSON.stringify(dto,null,2);
      this.note(`原命令事实已持久 · ${dto.result.state} · accepted ${dto.accepted_state_version}；不是执行启动。`);this.buttons();
      await this.load();
    } catch(error) {
      if(!this.current(t) || pending!==this.pending) return;
      pending.unknown();this.buttons();
      if([401,403].includes(error.status)){this.clear();this.onExpired(error);return;}
      this.clearConfirmation();
      if([400,409,422].includes(error.status)){pending.invalidate();this.pending=null;this.clearPrivate();this.buttons();this.note('命令被拒绝/版本冲突；未自动重发。请显式读取最新合同重新审阅。');return;}
      this.note(`提交结果未确认 (${error.status || '网络/响应校验'})；仅手动重试同payload/同key。版本冲突请放弃本地意图后重新审阅，不自动改写或重发。`);
    }
  }
  abandon() {
    if(!this.pending || this.pending.status==='IN_FLIGHT') return;
    this.pending.invalidate();this.pending=null;this.clearPrivate();this.buttons();
    this.note('已清除本地待确认意图，不表示服务器未提交或已取消；请读取最新合同核对。');
  }
}

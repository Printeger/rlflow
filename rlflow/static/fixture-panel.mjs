import {PendingCommand} from './goal-view.mjs';
import {checkFixtureProfile,checkFixturePage,checkFixtureTimeline,checkFixtureReceipt} from './fixture-view.mjs';
export class FixturePanel {
  constructor({context,request,now=()=>performance.now(),schedule=(fn,delay)=>setTimeout(fn,delay),cancel=id=>clearTimeout(id)}){
    this.context=context;this.request=request;this.serial=0;
    this.now=now;this.schedule=schedule;this.cancel=cancel;this.connectionState='UNKNOWN';
    this.$=id=>document.getElementById(id);
    this.$('fixture-refresh').addEventListener('click',()=>this.load());
    this.$('fixture-next').addEventListener('click',()=>this.load(this.page?.next_after));
    this.$('fixture-start').addEventListener('click',()=>this.command('START_FIXED_CPU'));
    this.$('fixture-stop').addEventListener('click',()=>this.command('STOP_FIXED_SCOPE'));
    this.$('fixture-retry').addEventListener('click',()=>this.send());
    this.$('fixture-abandon').addEventListener('click',()=>{this.pending?.invalidate();this.pending=null;this.buttons();this.note('只清除本地意图；不取消服务器执行。请重新读取。');});
    this.clear();
  }
  scope(){const c=this.context();return c ? {project:c.project,mode:c.mode,epoch:c.epoch,identity:c.session.principal_id,authGeneration:c.authGeneration}:null;}
  ticket(){return {serial:this.serial,scope:this.scope(),reconnectGeneration:this.reconnectGeneration};}
  current(t){return t.serial===this.serial && JSON.stringify(t.scope)===JSON.stringify(this.scope());}
  base(){return `/api/v1/projects/${encodeURIComponent(this.scope().project)}`;}
  note(s){this.$('fixture-note').textContent=s;}
  clear(){
    ++this.serial;this.cancel(this.refreshTimer);this.refreshTimer=null;
    this.wantedVersion=0;this.versionScope=null;this.lastRead=-Infinity;
    this.reading=false;this.autoBlocked=false;this.transportBlocked=false;
    this.reconnectGeneration=0;
    this.selected=null;this.after='';this.pending?.invalidate();this.pending=null;
    this.page=null;this.profile=null;this.detail=null;
    this.$('fixture-list').replaceChildren();this.$('fixture-timeline').replaceChildren();
    this.$('fixture-detail').textContent='';this.$('fixture-receipt').textContent='';
    this.note('尚未读取；没有自动执行。');this.buttons(false);
  }
  dirty(){return Boolean(this.page!==null && (this.page.as_of_state_version<this.wantedVersion || this.selected && (!this.detail || this.detail.as_of_state_version<this.wantedVersion)));}
  bindVersionScope(){const scope=JSON.stringify(this.scope());if(scope!==this.versionScope){this.versionScope=scope;this.wantedVersion=0;this.cancel(this.refreshTimer);this.refreshTimer=null;}}
  changed(version){
    this.bindVersionScope();
    if(!Number.isSafeInteger(version) || version<=this.wantedVersion || !this.scope() || this.scope().mode!=='fixture')return;
    this.wantedVersion=version;this.buttons();this.queueRefresh();
  }
  connection(status){
    const restored=!['LIVE','CATCHING UP'].includes(this.connectionState) && ['LIVE','CATCHING UP'].includes(status);
    this.connectionState=status;
    if(restored)++this.reconnectGeneration;
    if(restored && this.transportBlocked){this.autoBlocked=false;this.transportBlocked=false;}
    if(!['LIVE','CATCHING UP'].includes(status)){this.cancel(this.refreshTimer);this.refreshTimer=null;}
    this.buttons();this.queueRefresh();
  }
  readFailure(error,ticket){
    const transport=error instanceof TypeError && /fetch|network/i.test(error.message);
    const recovered=transport && this.reconnectGeneration>ticket.reconnectGeneration && ['LIVE','CATCHING UP'].includes(this.connectionState);
    this.autoBlocked=!recovered;this.transportBlocked=transport && !recovered;
  }
  queueRefresh(){
    if(!this.page || !this.dirty() || this.autoBlocked || this.reading || this.pending?.status==='IN_FLIGHT' || this.refreshTimer!==null || !['LIVE','CATCHING UP'].includes(this.connectionState))return;
    const ticket=this.ticket();this.refreshTimer=this.schedule(()=>{this.refreshTimer=null;if(this.current(ticket) && this.dirty() && !this.autoBlocked && ['LIVE','CATCHING UP'].includes(this.connectionState))this.load(this.after,true);},Math.max(0,1000-(this.now()-this.lastRead)));
  }
  buttons(syncFloor=true){
    const c=this.context(),operator=c?.session.kind==='human' && c.session.roles.includes('operator');
    if(syncFloor){this.bindVersionScope();if(c?.mode==='fixture' && Number.isSafeInteger(c.version) && c.version>=0)this.wantedVersion=Math.max(this.wantedVersion,c.version);}
    const enabled=operator && this.profile?.original_owner_available && this.detail && !this.pending && !this.reading && this.detail.as_of_state_version>=this.wantedVersion;
    const phase=this.detail?.task.recorded_phase;
    this.$('fixture-start').disabled=!(enabled && phase==='REGISTER_NO_HANDOFF');
    this.$('fixture-stop').disabled=!(enabled && !['STOP_REQUESTED','FIXTURE_SCOPE_STOPPED'].includes(phase));
    this.$('fixture-next').disabled=!this.page?.next_after;
    const inFlight=this.pending?.status==='IN_FLIGHT';
    this.$('fixture-refresh').disabled=inFlight || this.reading;
    this.$('fixture-next').disabled ||= inFlight || this.reading;
    for(const node of this.$('fixture-list').children)node.disabled=inFlight || this.reading;
    this.$('fixture-retry').hidden=this.pending?.status!=='UNKNOWN';
    this.$('fixture-retry').disabled=inFlight || this.reading;
    this.$('fixture-abandon').hidden=this.pending?.status!=='UNKNOWN';
    this.$('fixture-retry').textContent=this.pending?.acceptedStop?'手动继续原 STOP 清理（终态不代表 FREE）':'手动重试原 body / 原 key';
    this.$('fixture-live').textContent=`${this.connectionState} · Task as-of ${this.page?.as_of_state_version ?? 'UNKNOWN'} · 已接收持久版本 ${this.wantedVersion || 'UNKNOWN'} · ${this.autoBlocked?'STALE / 来源读取失败':this.dirty()?'STALE / 等待原来源读取':'AS-OF / 不推断当前运行'}`;
  }
  async load(after='',automatic=false){
    if(this.pending?.status==='IN_FLIGHT' || this.reading)return;
    if(!this.scope() || this.scope().mode!=='fixture'){this.clear();this.note('该项目没有固定 CPU fixture 视图。');return;}
    this.cancel(this.refreshTimer);this.refreshTimer=null;
    if(!automatic){this.autoBlocked=false;this.transportBlocked=false;}
    ++this.serial;const ticket=this.ticket();this.reading=true;this.lastRead=this.now();this.after=after || '';this.detail=null;this.profile=null;this.buttons();
    try{
      const results=await Promise.allSettled([this.request(`${this.base()}/fixture-tasks?limit=10&after=${encodeURIComponent(after || '')}`),this.request(`${this.base()}/fixture-runtime-profile`).catch(e=>{if(e.status===404)return null;throw e;})]);
      for(const result of results)if(result.status==='rejected')throw result.reason;
      const [page,profile]=results.map(result=>result.value);
      if(!this.current(ticket))return;
      this.page=checkFixturePage(page,ticket.scope,after || '');this.profile=profile===null?null:checkFixtureProfile(profile,ticket.scope);
      this.wantedVersion=Math.max(this.wantedVersion,page.as_of_state_version);
      this.$('fixture-list').replaceChildren();this.$('fixture-detail').textContent='';
      for(const row of this.page.items){const b=document.createElement('button');b.className='object-row';b.textContent=`${row.id} · ${row.recorded_phase} · as-of ${row.recorded_at_state_version}`;b.addEventListener('click',()=>this.open(row));this.$('fixture-list').append(b);}
      this.note(`原事件验证 · 本页 ${page.items.length} · 当前运行 UNKNOWN · owner ${profile?.original_owner_available?'此刻可用（不是授权）':'不可用；只读历史'}${this.pending?.acceptedStop?'。原 STOP 已接受；Task 终态不证明 FREE。可手动继续原 body / 原 key 清理，或明确清除本地意图。':''}`);
      if(this.selected)await this.readSelected(this.selected,ticket);
    }catch(e){if(this.current(ticket)){this.readFailure(e,ticket);this.profile=null;this.detail=null;this.note(e.status===404?'接口未安装或选择已不可读；不启用固定 CPU 执行。':`来源不可用：${e.message}；保留 as-of，不推断状态。`);}}
    finally{if(this.current(ticket)){this.reading=false;this.buttons();this.queueRefresh();}}
  }
  async open(row){
    if(this.pending?.status==='IN_FLIGHT' || this.reading)return;
    this.cancel(this.refreshTimer);this.refreshTimer=null;
    ++this.serial;const ticket=this.ticket();this.selected=Object.freeze({id:row.id,attempt_id:row.attempt_id,reservation_id:row.reservation_id});this.reading=true;this.detail=null;this.$('fixture-detail').textContent='';this.$('fixture-timeline').replaceChildren();this.buttons();
    try{await this.readSelected(row,ticket);}
    catch(e){if(this.current(ticket)){this.readFailure(e,ticket);this.note(`Task 未读取：${e.message}；保留 as-of。`);}}
    finally{if(this.current(ticket)){this.reading=false;this.buttons();this.queueRefresh();}}
  }
  async readSelected(row,ticket){
    const value=await this.request(`${this.base()}/fixture-tasks/${encodeURIComponent(row.reservation_id)}/timeline`);
    if(!this.current(ticket))return;
    this.detail=checkFixtureTimeline(value,ticket.scope,row);this.$('fixture-detail').textContent=JSON.stringify(this.detail,null,2);
    this.$('fixture-timeline').replaceChildren();for(const event of value.events){const node=document.createElement('li');node.textContent=`${event.recorded_phase} · 原版本 ${event.state_version} · ${event.recorded_at}`;this.$('fixture-timeline').append(node);}
  }
  command(action){
    this.buttons();if(this.$(action==='START_FIXED_CPU'?'fixture-start':'fixture-stop').disabled)return;
    const body={action,task_id:this.detail.task.id,expected_state_version:this.detail.as_of_state_version};
    this.pending=new PendingCommand(this.scope(),body,'fixture_web_'+crypto.randomUUID());
    this.pending.selector=this.detail.task.reservation_id;this.send();
  }
  async send(){
    if(this.reading)return;
    const pending=this.pending,ticket=this.ticket();if(!pending || !pending.matches(ticket.scope))return;
    let intent;try{intent=pending.begin(ticket.scope);}catch{return;}
    this.buttons();this.note('提交原意图；等待接收回执，不代表已运行/停止。');
    try{
      const value=await this.request(`${this.base()}/fixture-tasks/${encodeURIComponent(pending.selector)}/commands`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':this.context().session.csrf_token,'Idempotency-Key':intent.key},body:intent.body});
      if(!this.current(ticket) || this.pending!==pending)return;
      const body=JSON.parse(intent.body);checkFixtureReceipt(value,body,ticket.scope.identity);
      if(body.action==='STOP_FIXED_SCOPE'){pending.unknown();pending.acceptedStop=true;}
      else {pending.finish();this.pending=null;}
      this.$('fixture-receipt').textContent=JSON.stringify(value,null,2);this.note('ACCEPTED 只是原接收事实；请读取最新 Task 阶段。');this.detail=null;this.buttons();
      await this.load();
    }catch(e){
      if(!this.current(ticket) || this.pending!==pending)return;
      pending.unknown();this.detail=null;
      if([400,401,403,404,409,422].includes(e.status)){pending.invalidate();this.pending=null;this.profile=null;this.note(`命令被拒绝 (${e.status})；未自动重发，请明确重新读取。`);}
      else this.note('结果 UNKNOWN；只允许手动重试原 body / 原 key。Start 不重新派发；STOP 可继续原范围清理。');
      this.buttons();this.queueRefresh();
    }
  }
}

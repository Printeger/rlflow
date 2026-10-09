import {installSnapshot, applyEvent, mergePage, total, cursor, objectKey, SyncError} from './reducer.mjs';
import {VirtualList} from './virtual-list.mjs';
import {checkLogPage,checkLogBody} from './log-view.mjs';
import {TelemetryView} from './telemetry-view.mjs';
import {GoalPanel} from './goal-panel.mjs';
import {FixturePanel} from './fixture-panel.mjs';
import {CpuAssessmentPanel} from './cpu-assessment-panel.mjs';
import {CandidateOutputPanel} from './candidate-output-panel.mjs';
import {CpuUnitPanel} from './cpu-unit-panel.mjs';
import {EngineeringUnitPanel} from './engineering-unit-panel.mjs';
import {FiniteStopPanel} from './finite-stop-panel.mjs';

const $ = id => document.getElementById(id);
const motionPreference = matchMedia('(prefers-reduced-motion: reduce)');
let session = null, projects = [], project = null, state = null, source = null, generation = 0;
let lastHeard = 0, connection = 'NOT CONNECTED', caughtUp = false, pageIds = [], nextPage = null;
let renderTimer = null, pendingHighlights = new Map(), pageSerial = 0, unread = 0;
let raf = null, pulseTimer = null;
let authGeneration = 0, authController = null;
let telemetry = null, telemetryError = '';
const goals=new GoalPanel({context:()=>session && state && project && state.project===project.id ?
  {session,authGeneration,project:state.project,mode:state.mode,epoch:state.epoch,version:state.sourceVersion} : null,
  request,onExpired:error=>{if(error.status===401){session=null;$('login-panel').hidden=false;}problem('私有 Hybrid 控制已清除；请核对权限或重新登录。');}});
const pulses = new Map();
const fixtures=new FixturePanel({context:()=>session && state && project && state.project===project.id ?
  {session,authGeneration,project:state.project,mode:state.mode,epoch:state.epoch,version:state.sourceVersion}:null,request});
const cpuAssessments=new CpuAssessmentPanel({context:()=>session && state && project && state.project===project.id ?
  {session,authGeneration,project:state.project,mode:state.mode,epoch:state.epoch,version:state.sourceVersion}:null,request});
const candidateOutputs=new CandidateOutputPanel({context:()=>session && state && project && state.project===project.id ?
  {session,authGeneration,project:state.project,mode:state.mode,epoch:state.epoch,version:state.sourceVersion}:null,request});
const eventList = new VirtualList($('events'), eventNode, event => event.event_id);
const cpuUnits=new CpuUnitPanel({context:()=>session && state && project && state.project===project.id ?
  {session,authGeneration,project:state.project,mode:state.mode,epoch:state.epoch,version:state.sourceVersion}:null,request});
const engineeringUnits=new EngineeringUnitPanel({context:()=>session && state && project && state.project===project.id ?
  {session,authGeneration,project:state.project,mode:state.mode,epoch:state.epoch,version:state.sourceVersion}:null,request});
const finiteStops=new FiniteStopPanel({context:()=>session && state && project && state.project===project.id ?
  {session,authGeneration,project:state.project,mode:state.mode,epoch:state.epoch}:null,request});
let logSerial = 0, logDetailSerial = 0, logPage = null, logNext = null, logPending = 0;
const logList = new VirtualList($('logs'),logNode,row => row.id);
function clearLogs() {
  ++logSerial; ++logDetailSerial; logPage = null; logNext = null; logPending = 0; logList.setItems([]);
  $('log-note').textContent = '尚未读取。'; $('log-next').disabled = true; $('log-new').hidden = true; $('log-empty').hidden = true;
  $('log-new').textContent = ''; $('details').close(); $('detail-title').textContent = ''; $('detail-content').textContent = '';
}
function logScope() { return {project:state.project,mode:state.mode,epoch:state.epoch}; }
function logNode(row) {
  const button = text('button','', 'event-row'); button.dataset.logId = row.id;
  const summary = text('span',`${row.severity} · ${row.source}`);
  summary.append(text('span',`${row.object_count} objects · ${short(row.id)}`,'muted'));
  button.append(text('span',row.occurred_at.slice(11,19),'muted'),summary);
  button.title = `${row.severity} · ${row.id} · ${row.occurred_at} · Enter / 点击懒加载正文`;
  button.addEventListener('click',async () => {
    const selected = generation, ticket = logSerial, chosen = ++logDetailSerial, scope = logScope();
    try { const value = await request(`${base()}/logs/${encodeURIComponent(row.id)}`);
      if (selected === generation && ticket === logSerial && chosen === logDetailSerial) details(`${row.source} · ${row.id}`,checkLogBody(value,row,scope));
    } catch (error) { if (selected === generation && ticket === logSerial && chosen === logDetailSerial) $('log-note').textContent = `正文未加载：${error.message}`; }
  }); return button;
}
async function loadLogs(after='') {
  if (!state || !project || state.project !== project.id) return;
  const ticket = ++logSerial, selected = generation, scope = logScope(), previousHigh = after ? logPage?.high_water : null;
  const severity = $('log-severity').value, kind = $('log-kind').value, objectId = $('log-object').value.trim();
  if (!!kind !== !!objectId) { $('log-note').textContent = '关联类型和公开 ID 必须一起填写；下方保留上次读取结果。'; return; }
  const query = new URLSearchParams({limit:'50',after});
  if (severity) query.set('severity',severity);
  if (kind) {query.set('kind',kind);query.set('object_id',objectId);}
  $('log-note').textContent = '读取日志…下方保留上次读取结果。';
  try {
    const value = await request(`${base()}/logs?${query}`);
    if (selected !== generation || ticket !== logSerial) return;
    logPage = checkLogPage(value,scope,previousHigh); logNext = value.next_cursor;
    logPending = Math.max(0,state.seq-cursor(value.high_water).seq);
    $('logs').scrollTop = 0; logList.setItems(value.items); $('log-next').disabled = !logNext;
    $('log-empty').hidden = value.items.length>0;
    $('log-note').textContent = `${severity || 'ALL'} · ${kind ? kind+' '+objectId : '全部关联'} · 本页 ${value.items.length} · 日志 high-water ${value.high_water} · 覆盖 seq > ${value.coverage_after_seq}（不含更早历史）`;
    updateLogPending();
  } catch (error) { if (selected === generation && ticket === logSerial) $('log-note').textContent = `日志不可用：${error.message}；保留上次日志，不把缺覆盖解释成没有事件。`; }
}
function updateLogPending() {
  $('log-new').hidden = !logPending;
  $('log-new').textContent = `${logPending} 次新提交（可能不匹配筛选）；读取最新日志`;
}
function beginAuth() {
  finiteStops.clear();
  cpuUnits.clear();engineeringUnits.clear();
  cpuAssessments.clear();candidateOutputs.clear();
  goals.clear();
  fixtures.clear();
  authController?.abort(); authController = new AbortController();
  return {ticket:++authGeneration, signal:authController.signal};
}
function clearObservation() {
  finiteStops.clear();
  cpuUnits.clear();engineeringUnits.clear();
  cpuAssessments.clear();candidateOutputs.clear();
  goals.clear();
  fixtures.clear();
  ++generation; ++pageSerial; closeStream(); clearTimeout(renderTimer); renderTimer = null;
  state = null; project = null; pageIds = []; nextPage = null; unread = 0; lastHeard = 0;
  telemetry = null;telemetryError='';renderResources();
  for (const id of ['executions','budgets','objects','events']) $(id).replaceChildren();
  eventList.setItems([]);
  clearLogs(); $('log-severity').value = ''; $('log-kind').value = ''; $('log-object').value = '';
  for (const id of ['task-total','execution-total','approval-total']) $(id).textContent = 'UNKNOWN';
  $('tool-note').textContent = '工具返回覆盖：UNKNOWN / 尚未读取。';
  for (const id of ['project-title','mode-note','cursor','sync-time','core-flags','execution-caption','object-page-note','detail-content']) $(id).textContent = '';
  $('details').close(); $('next-page').disabled = true; $('new-events').hidden = true;
  for (const id of ['execution-empty','objects-empty','events-empty']) $(id).hidden = false;
  setConnection('NOT CONNECTED');
}
function text(tag, value, className) {
  const node = document.createElement(tag); node.textContent = value ?? '未提供';
  if (className) node.className = className; return node;
}
function number(value) { return value === null || value === undefined ? 'UNKNOWN' : String(value); }
function bytes(value) {return value===null || value===undefined ? 'UNKNOWN' : `${(value/1024**3).toFixed(2)} GiB`;}
function renderResources() {
  const value=telemetry?.current(performance.now());
  $('resource-status').textContent=value ? `${value.freshness} · sample age ${value.sample_age_seconds.toFixed(1)}s` : `UNKNOWN${telemetryError ? ' / '+telemetryError : ' / 尚无已验证样本'}`;
  $('resource-status').dataset.freshness=value?.freshness || 'UNKNOWN';
  const cpu=value?.host.cpu,memory=value?.host.memory,disk=value?.host.disk;
  $('resource-cpu').textContent=cpu?.status==='KNOWN' ? `${cpu.utilization_percent.toFixed(1)}%` : 'UNKNOWN';
  $('resource-memory').textContent=memory?.status==='KNOWN' ? `${bytes(memory.available_bytes)} / ${bytes(memory.total_bytes)}` : 'UNKNOWN';
  $('resource-disk').textContent=disk?.status==='KNOWN' ? `${bytes(disk.available_bytes)} / ${bytes(disk.total_bytes)}` : 'UNKNOWN';
  $('resource-note').textContent=value ? `CORE_OS_SAMPLE · PARTIAL · 本批 ${value.workers.length} worker${value.workers_truncated ? '（轮转未覆盖全部）' : ''} · ${value.observed_at} · ${value.sample_id}；仅最新样本，无历史曲线。` : '资源来源未启用/不可用不表示零；服务端心跳不刷新资源样本。';
  $('resource-workers').replaceChildren(...(value?.workers || []).filter(w=>w.process.scope==='FIXED_WORKER_PROCESS').map(w=>
    text('p',`${w.execution_id.slice(0,18)} · FIXED_WORKER_PROCESS · ${w.process.status==='KNOWN' ? 'CPU '+w.process.cpu_seconds.toFixed(2)+'s / RSS '+bytes(w.process.rss_bytes) : 'UNKNOWN'}（原固定进程采样；非计费/模型活动/整树资源）`)));
  for (const node of document.querySelectorAll('.worker-health')) {
    const worker=value?.workers.find(w=>w.execution_id===node.dataset.executionId),h=worker?.heartbeat,p=worker?.process;
    node.textContent=`worker loop ${h?.status || 'UNKNOWN'}${h?.age_seconds!==null && h?.age_seconds!==undefined ? ' · age '+h.age_seconds.toFixed(1)+'s' : ''} · supervisor ${p?.status==='KNOWN' ? 'CPU '+p.cpu_seconds.toFixed(2)+'s / RSS '+bytes(p.rss_bytes) : 'UNKNOWN'}（非模型活动/进程树）`;
  }
}
function short(value) { return value ? value.slice(0,14) + (value.length > 14 ? '…' : '') : '未提供'; }
function base() { return `/api/v1/projects/${encodeURIComponent(project.id)}`; }
function setConnection(value) {
  cpuUnits.connection(value);engineeringUnits.connection(value);
  connection = value; $('connection').textContent = value;
  fixtures.connection(value);
  cpuAssessments.connection(value);candidateOutputs.connection(value);
  $('connection').className = 'status-pill ' + value.toLowerCase().replaceAll(' ','-');
  if (!['LIVE','CATCHING UP'].includes(value)) stopPulses();
}
function problem(message) { $('error-banner').textContent = message; $('error-banner').hidden = !message; }
async function request(url, options = {}) {
  const requestAuth=authGeneration,requestGeneration=generation;
  const response = await fetch(url, {credentials:'same-origin', cache:'no-store', ...options});
  if (!response.ok) {
    if(response.status===401 && requestAuth===authGeneration && requestGeneration===generation) {finiteStops.clear();cpuUnits.clear();engineeringUnits.clear();goals.clear();fixtures.clear();cpuAssessments.clear();candidateOutputs.clear();session=null;$('login-panel').hidden=false;closeStream();}
    const error = new Error(response.status === 401 ? '登录已到期，请重新登录；最后快照保留。' : `读取失败 (${response.status})；最后快照保留。`);
    error.status = response.status; throw error;
  }
  return response.json();
}
function closeStream() { if (source) source.close(); source = null; caughtUp = false; stopPulses(); }
function stopPulses() {
  if (raf !== null) cancelAnimationFrame(raf); raf = null;
  clearTimeout(pulseTimer); pulseTimer = null;
  for (const pulse of pulses.values()) pulse.node.classList.remove('event-highlight');
  pulses.clear(); pendingHighlights.clear();
}
function motionAllowed() { return !document.hidden && !motionPreference.matches && !$('reduce-motion').checked && connection === 'LIVE' && caughtUp; }
function pulseStep() {
  raf = null; const now = performance.now();
  if (!motionAllowed()) { stopPulses(); return; }
  for (const [key,pulse] of pulses) {
    if (now - pulse.start > 500 || !pulse.node.isConnected) { pulse.node.classList.remove('event-highlight'); pulses.delete(key); }
  }
  // Schedule at most 30 callbacks/s, only while a real event highlight exists.
  if (pulses.size) pulseTimer = setTimeout(() => { pulseTimer = null; raf = requestAnimationFrame(pulseStep); },34);
}
function highlight(node, key, eventId) {
  if (!motionAllowed()) return;
  const previous = pulses.get(key), count = (previous?.count || 0) + 1;
  node.classList.add('event-highlight'); node.title = `真实事件 ${eventId}；合并 ${count} 次变化，不代表模型活动。`;
  pulses.set(key,{node,start:performance.now(),count});
  if (raf === null && pulseTimer === null) raf = requestAnimationFrame(pulseStep);
}
function details(title, value) {
  ++logDetailSerial;
  $('detail-title').textContent = title; $('detail-content').textContent = JSON.stringify(value,null,2);
  if (!$('details').open) $('details').showModal();
}
function nodeButton(row) {
  const button = document.createElement('button'); button.className = 'execution-node';
  button.dataset.objectId = row.id; button.dataset.state = row.state || 'UNKNOWN';
  const heading = text('div','', 'node-heading'); heading.append(text('strong',row.role || row.kind),text('span',row.state || 'UNKNOWN','state ' + (row.state || 'UNKNOWN')));
  button.append(heading,text('div',`session ${short(row.id)}`,'node-line'),text('div',`model ${row.model_id || 'UNKNOWN'}`,'node-line'),
    text('div',`usage ${row.usage_status || 'UNKNOWN'} · scope 未提供`,'node-line'),
    text('div',row.startup_observation ? `CLI_RELEASE_ACK · ${row.startup_released_at}` : '尚未观测启动释放 ACK','node-line'));
  if (row.task_id) button.append(text('div',`关联 task ${short(row.task_id)}`,'node-line'));
  const health = text('div','worker loop UNKNOWN · supervisor resources UNKNOWN','node-line worker-health');
  health.dataset.executionId=row.id;button.append(health);
  button.append(text('div',row.reason || row.description || '没有已公开的触发原因。','node-description'));
  button.addEventListener('click',() => details(`${row.kind} · ${row.id}`,row));
  return button;
}
function eventNode(event) {
  const button = text('button','', 'event-row'); button.dataset.eventId = event.event_id;
  const summary = text('span',event.source_event_type);
  summary.append(text('span',`${event.changed_count} changes · ${short(event.event_id)}`,'muted'));
  button.append(text('span',event.occurred_at.slice(11,19),'muted'),summary);
  button.title = `${event.source_event_type} · ${event.event_id} · ${event.occurred_at} · 点击读取完整公共事件`;
  button.addEventListener('click',async () => {
    const selected = generation;
    try { const full = await request(`${base()}/domain-events/${encodeURIComponent(event.event_id)}`);
      if (selected === generation) details(event.event_id,full);
    } catch (error) { if (selected === generation) problem(error.message); }
  });
  return button;
}
function scheduleRender() {
  if (renderTimer !== null) return;
  renderTimer = setTimeout(() => { renderTimer = null; render(); },34);
}
function render() {
  if (!state) return;
  $('task-total').textContent = total(state,'task'); $('execution-total').textContent = total(state,'execution');
  $('approval-total').textContent = total(state,'approval');
  $('core-flags').textContent = `source paused=${state.paused} · enabled=${state.enabled} · PARTIAL`;
  $('tool-note').textContent = state.toolCoverage ? `已公开的绑定工具返回 ${total(state,'tool_return')} · PARTIAL / LIVE_ONLY · 覆盖 seq > ${state.toolCoverage.coverage_after_seq}、source version > ${state.toolCoverage.coverage_after_source_version}；缺失/未验证调用与更早历史 UNKNOWN，不是全部调用数。` : '工具返回覆盖 UNKNOWN / 未启用；没有公开记录不等于零调用。';
  $('cursor').textContent = state.cursor; $('sync-time').textContent = `服务端同步 ${state.serverTime}`;
  const executions = [...state.objects.values()].filter(row => row.kind === 'execution').slice(0,30);
  $('executions').replaceChildren();
  for (const row of executions) {
    const button = nodeButton(row), key = objectKey(row); $('executions').append(button);
    if (pendingHighlights.has(key)) highlight(button,key,pendingHighlights.get(key));
  }
  pendingHighlights.clear(); $('execution-empty').hidden = executions.length > 0;
  renderResources();
  $('execution-caption').textContent = `缓存显示 ${executions.length} / 后端 ${total(state,'execution')} · 最多 30`;
  const stages = [...state.objects.values()].filter(row => row.kind === 'stage'); $('budgets').replaceChildren();
  for (const row of stages.slice(0,10)) {
    const section = text('div','', 'budget-row'); section.append(text('div',`Stage ${short(row.id)}`));
    const values = text('div','', 'budget-values');
    for (const [label,value] of [['consumed calls',row.used_calls],['reserved calls',row.reserved_calls],['limit calls',row.limit_calls]]) {
      const field = text('div',''); field.append(text('span',label),text('strong',number(value))); values.append(field);
    }
    section.append(values,text('div',`seconds consumed ${number(row.used_seconds)} / reserved ${number(row.reserved_seconds)} / limit ${number(row.limit_seconds)}`,'muted'));
    $('budgets').append(section);
  }
  if (!stages.length) $('budgets').append(text('p','当前缓存没有 Stage 预算；未提供。','empty'));
  const kind = $('kind-select').value;
  const rows = pageIds.map(key => state.objects.get(key)).filter(row => row?.kind === kind);
  $('objects').replaceChildren();
  for (const row of rows) {
    const label = row.kind==='tool_return' ? `cpu_exec · bound return · exit ${row.exit_code} · reported ${row.wall_seconds}s` : row.description || row.reason || short(row.id);
    const button = text('button','', 'object-row'), title = text('span',label,'object-title');
    title.append(text('span',`${row.kind} ${short(row.id)} · v${row.version}`,'muted'));
    button.append(title,text('span',row.state || 'UNKNOWN','state')); button.addEventListener('click',() => details(`${row.kind} · ${row.id}`,row));
    $('objects').append(button);
  }
  $('objects-empty').hidden = rows.length > 0; $('next-page').disabled = !nextPage;
  const filter = $('event-filter').value.toLowerCase();
  eventList.setItems(state.events.filter(event => JSON.stringify(event).toLowerCase().includes(filter)));
  $('events-empty').hidden = state.events.length > 0;
  $('new-events').hidden = !unread; $('new-events').textContent = `查看新增 ${unread} 条事件`;
}
async function loadPage(after = '') {
  if (!state) return;
  const ticket = ++pageSerial, selected = generation, requestCursor = state.cursor, kind = $('kind-select').value;
  $('object-page-note').textContent = '加载公共对象页…';
  try {
    const page = await request(`${base()}/objects?kind=${encodeURIComponent(kind)}&limit=50&after=${encodeURIComponent(after)}`);
    if (ticket !== pageSerial || selected !== generation) return;
    state = mergePage(state,page,requestCursor); pageIds = page.items.map(objectKey); nextPage = page.next_cursor;
    $('object-page-note').textContent = `本页 ${page.items.length} / 后端 ${page.total}；keyset 分页`;
    scheduleRender();
  } catch (error) { if (selected === generation && ticket === pageSerial) { $('object-page-note').textContent = error.message === 'STALE_PAGE' ? '读页期间状态已变化，请切换类型或重建快照重试。' : error.message; } }
}
function openStream(selected) {
  source = new EventSource(`${base()}/events?after=${encodeURIComponent(state.cursor)}`);
  const current = source;
  current.onopen = () => { if (selected === generation) { lastHeard = performance.now(); setConnection('CATCHING UP'); } };
  current.addEventListener('domain',message => {
    if (selected !== generation || current !== source) return;
    try {
      const value = JSON.parse(message.data), result = applyEvent(state,value,message.lastEventId);
      state = result.state; goals.changed(state.sourceVersion); lastHeard = performance.now();
      if (!result.duplicate) {
        telemetry?.invalidateFixedWorkers(state.sourceVersion);
        fixtures.changed(state.sourceVersion);
        cpuUnits.changed(state.sourceVersion);engineeringUnits.changed(state.sourceVersion);
        cpuAssessments.changed(state.sourceVersion);candidateOutputs.changed(state.sourceVersion);
        telemetry?.invalidateWorkers([...value.payload.upsert.filter(r=>r.kind==='execution').map(r=>r.id),
          ...value.payload.removed.filter(r=>r.kind==='execution').map(r=>r.id)],value.payload.source_state_version);
        if (logPage && value.seq>cursor(logPage.high_water).seq) {logPending++;updateLogPending();}
        const kind = $('kind-select').value;
        for (const row of value.payload.upsert) {
          const key = objectKey(row);
          if (row.kind === kind && !pageIds.includes(key) && pageIds.length < 50) pageIds.push(key);
        }
        pageIds = pageIds.filter(key => state.objects.has(key));
        $('object-page-note').textContent = `实时缓存窗口 ${pageIds.length} / 后端 ${total(state,kind)}；最多 50`;
        if ($('events').scrollTop > 12) unread += 1;
        if (caughtUp) for (const key of result.changed.slice(0,200)) pendingHighlights.set(key,value.event_id);
        scheduleRender();
      }
    } catch (error) { failStream(error,selected); }
  });
  current.addEventListener('telemetry',message => {
    if (selected!==generation || current!==source || !telemetry) return;
    try {if (telemetry.accept(JSON.parse(message.data),performance.now())) renderResources();}
    catch { telemetryError='样本合同被拒绝；重建快照重试';telemetry=null;renderResources(); }
  });
  current.addEventListener('heartbeat',message => {
    if (selected !== generation || current !== source) return;
    try {
      const value = JSON.parse(message.data), at = cursor(value.cursor);
      if (at.epoch !== state.epoch || typeof value.server_time !== 'string' || !value.server_time.endsWith('Z')) throw new SyncError('INVALID_HEARTBEAT');
      lastHeard = performance.now(); caughtUp = at.seq === state.seq;
      setConnection(caughtUp ? 'LIVE' : 'CATCHING UP'); $('sync-time').textContent = `服务端同步 ${value.server_time}`;
    } catch (error) { failStream(error,selected); }
  });
  current.addEventListener('resync_required',message => {
    if (selected !== generation || current !== source) return;
    try { const value = JSON.parse(message.data);
      closeStream();
      if (value.reason === 'AUTH_EXPIRED') { cpuUnits.clear();engineeringUnits.clear();goals.clear();fixtures.clear();cpuAssessments.clear();candidateOutputs.clear();session = null; $('login-panel').hidden = false; setConnection('AUTH EXPIRED'); problem('登录已到期。最后快照不代表当前状态。'); }
      else if (value.reason === 'SOURCE_UNAVAILABLE') { setConnection('OFFLINE'); problem('后端观测源不可用。保留最后快照，请重建快照重试。'); }
      else selectProject();
    } catch (error) { failStream(error,selected); }
  });
  let checkingAuth = false;
  current.onerror = () => {
    if (selected !== generation || current !== source) return;
    setConnection(navigator.onLine ? 'RECONNECTING' : 'OFFLINE');
    if (navigator.onLine && !checkingAuth) {
      checkingAuth = true;
      request('/api/v1/session').catch(error => {
        if (error.status === 401 && selected === generation && current === source) {
          cpuUnits.clear();engineeringUnits.clear();goals.clear();fixtures.clear();cpuAssessments.clear();candidateOutputs.clear();closeStream(); session = null; $('login-panel').hidden = false; setConnection('AUTH EXPIRED'); problem(error.message);
        }
      }).finally(() => { checkingAuth = false; });
    }
  };
}
function failStream(error, selected) {
  if (selected !== generation) return;
  cpuUnits.clear();engineeringUnits.clear();
  cpuAssessments.clear();candidateOutputs.clear();
  fixtures.clear();
  goals.clear();closeStream(); problem(`同步被拒绝：${error.message}。未推断业务状态。`);
  if (error.incompatible) setConnection('INCOMPATIBLE'); else selectProject();
}
async function selectProject() {
  finiteStops.clear();
  cpuUnits.clear();engineeringUnits.clear();
  cpuAssessments.clear();candidateOutputs.clear();
  goals.clear();
  fixtures.clear();
  const selected = ++generation; ++pageSerial; closeStream();
  telemetry=null;telemetryError='';renderResources();
  project = projects.find(value => value.id === $('project-select').value);
  if (state?.project !== project?.id) clearLogs();
  else {++logSerial; ++logDetailSerial; $('details').close(); $('detail-title').textContent = ''; $('detail-content').textContent = '';}
  if (!project) return;
  $('details').close(); setConnection('CONNECTING');
  problem(state && state.project !== project.id ? `正在切换到 ${project.id}；下方仍是 ${state.project} 的最后快照。` : '');
  try {
    const snapshot = await request(`${base()}/snapshot`);
    if (selected !== generation) return;
    state = installSnapshot(snapshot,project.id,project.data_mode); lastHeard = performance.now(); pageIds = []; nextPage = null; unread = 0;
    telemetry = new TelemetryView({project:state.project,mode:state.mode,epoch:state.epoch,sourceVersion:state.sourceVersion});
    if (logPage && cursor(logPage.high_water).epoch !== state.epoch) clearLogs();
    if (logPage) {logPending = Math.max(0,state.seq-cursor(logPage.high_water).seq);updateLogPending();}
    $('project-title').textContent = project.id;
    $('mode-note').className = 'notice ' + (project.data_mode === 'fixture' ? 'fixture' : '');
    $('mode-note').textContent = project.data_mode === 'fixture' ? 'FIXTURE / 隔离测试数据，不证明供应商模型或生产运行。' : 'LIVE / 真实公共投影。连接正常不代表模型运行，观察不足会明确显示。';
    problem(''); render(); openStream(selected);
    await Promise.allSettled([loadPage(), loadOverview('execution',30), loadOverview('stage',10),loadLogs(),goals.load(),fixtures.load(),cpuUnits.load(),engineeringUnits.load(),cpuAssessments.load(),candidateOutputs.load(),finiteStops.load()]);
  } catch (error) { if (selected === generation) { setConnection(error.incompatible ? 'INCOMPATIBLE' : 'OFFLINE'); problem(error.message); if (error.status === 401) $('login-panel').hidden = false; } }
}
async function loadOverview(kind, limit) {
  const selected = generation, at = state.cursor;
  try { const page = await request(`${base()}/objects?kind=${kind}&limit=${limit}`);
    if (selected === generation) { state = mergePage(state,page,at); scheduleRender(); }
  } catch (error) { if (selected === generation) problem(`部分 ${kind} 页尚未同步：${error.message}。可重建快照重试。`); }
}
async function authenticated(auth) {
  const verified = await request('/api/v1/session',{signal:auth.signal});
  if (auth.ticket !== authGeneration) return;
  // A newly verified identity must never inherit another principal's public cache or DOM.
  clearObservation(); session = verified; projects = []; $('project-select').replaceChildren();
  const result = await request('/api/v1/projects',{signal:auth.signal});
  if (auth.ticket !== authGeneration) return;
  projects = result.items;
  $('project-select').replaceChildren(...projects.map(project => { const option = text('option',project.id); option.value = project.id; return option; }));
  $('login-panel').hidden = true; $('dashboard').hidden = false;
  if (!projects.length) { problem('当前身份没有可见项目；没有加载任何观测数据。'); return; }
  await selectProject();
}
$('login-form').addEventListener('submit',async event => {
  event.preventDefault(); $('login-error').textContent = '';
  const passphrase = $('passphrase').value; $('passphrase').value = '';
  const auth = beginAuth();
  try { await request('/api/v1/login',{method:'POST',signal:auth.signal,headers:{'Content-Type':'application/json'},body:JSON.stringify({principal_id:$('principal').value,passphrase})});
    if (auth.ticket === authGeneration) await authenticated(auth); }
  catch (error) { if (auth.ticket === authGeneration && error.name !== 'AbortError') $('login-error').textContent = error.message; }
});
$('logout').addEventListener('click',async () => {
  const auth = beginAuth(), previous = session;
  clearObservation(); session = null; projects = []; $('project-select').replaceChildren();
  $('dashboard').hidden = true; $('login-panel').hidden = false;
  try { if (previous) await request('/api/v1/logout',{method:'POST',signal:auth.signal,headers:{'X-CSRF-Token':previous.csrf_token}}); }
  catch (error) { if (auth.ticket === authGeneration && error.name !== 'AbortError') $('login-error').textContent = '本地数据已清除，但服务端注销未确认，请重试。'; }
});
$('project-select').addEventListener('change',selectProject); $('refresh').addEventListener('click',selectProject);
$('kind-select').addEventListener('change',() => loadPage()); $('next-page').addEventListener('click',() => loadPage(nextPage));
$('event-filter').addEventListener('input',scheduleRender); $('close-details').addEventListener('click',() => $('details').close());
$('new-events').addEventListener('click',() => { unread = 0; $('events').scrollTop = 0; scheduleRender(); });
$('log-filters').addEventListener('submit',event => {event.preventDefault();loadLogs();});
$('log-next').addEventListener('click',() => loadLogs(logNext)); $('log-new').addEventListener('click',() => loadLogs());
$('log-filters').addEventListener('input',() => {$('log-next').disabled = true;});
$('details').addEventListener('close',() => {++logDetailSerial;});
$('reduce-motion').checked = motionPreference.matches;
$('reduce-motion').addEventListener('change',stopPulses); motionPreference.addEventListener('change',stopPulses);
document.addEventListener('visibilitychange',stopPulses);
window.addEventListener('offline',() => setConnection('OFFLINE'));
window.addEventListener('online',() => { if (state && session && source) setConnection('RECONNECTING'); });
setInterval(() => { if (state && source && lastHeard && performance.now() - lastHeard > 15000 && connection !== 'STALE') setConnection('STALE');renderResources(); },1000);
const bootAuth = beginAuth();
authenticated(bootAuth).catch(() => { if (bootAuth.ticket === authGeneration) $('login-panel').hidden = false; });

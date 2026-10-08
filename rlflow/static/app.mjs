import {installSnapshot, applyEvent, mergePage, total, cursor, objectKey, SyncError} from './reducer.mjs';
import {VirtualList} from './virtual-list.mjs';

const $ = id => document.getElementById(id);
const motionPreference = matchMedia('(prefers-reduced-motion: reduce)');
let session = null, projects = [], project = null, state = null, source = null, generation = 0;
let lastHeard = 0, connection = 'NOT CONNECTED', caughtUp = false, pageIds = [], nextPage = null;
let renderTimer = null, pendingHighlights = new Map(), pageSerial = 0, unread = 0;
let raf = null, pulseTimer = null;
let authGeneration = 0, authController = null;
const pulses = new Map();
const eventList = new VirtualList($('events'), eventNode, event => event.event_id);
function beginAuth() {
  authController?.abort(); authController = new AbortController();
  return {ticket:++authGeneration, signal:authController.signal};
}
function clearObservation() {
  ++generation; ++pageSerial; closeStream(); clearTimeout(renderTimer); renderTimer = null;
  state = null; project = null; pageIds = []; nextPage = null; unread = 0; lastHeard = 0;
  for (const id of ['executions','budgets','objects','events']) $(id).replaceChildren();
  eventList.setItems([]);
  for (const id of ['task-total','execution-total','approval-total']) $(id).textContent = 'UNKNOWN';
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
function short(value) { return value ? value.slice(0,14) + (value.length > 14 ? '…' : '') : '未提供'; }
function base() { return `/api/v1/projects/${encodeURIComponent(project.id)}`; }
function setConnection(value) {
  connection = value; $('connection').textContent = value;
  $('connection').className = 'status-pill ' + value.toLowerCase().replaceAll(' ','-');
  if (!['LIVE','CATCHING UP'].includes(value)) stopPulses();
}
function problem(message) { $('error-banner').textContent = message; $('error-banner').hidden = !message; }
async function request(url, options = {}) {
  const response = await fetch(url, {credentials:'same-origin', cache:'no-store', ...options});
  if (!response.ok) {
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
  $('cursor').textContent = state.cursor; $('sync-time').textContent = `服务端同步 ${state.serverTime}`;
  const executions = [...state.objects.values()].filter(row => row.kind === 'execution').slice(0,30);
  $('executions').replaceChildren();
  for (const row of executions) {
    const button = nodeButton(row), key = objectKey(row); $('executions').append(button);
    if (pendingHighlights.has(key)) highlight(button,key,pendingHighlights.get(key));
  }
  pendingHighlights.clear(); $('execution-empty').hidden = executions.length > 0;
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
    const button = text('button','', 'object-row'), title = text('span',row.description || row.reason || short(row.id),'object-title');
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
      state = result.state; lastHeard = performance.now();
      if (!result.duplicate) {
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
      if (value.reason === 'AUTH_EXPIRED') { session = null; $('login-panel').hidden = false; setConnection('AUTH EXPIRED'); problem('登录已到期。最后快照不代表当前状态。'); }
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
          closeStream(); session = null; $('login-panel').hidden = false; setConnection('AUTH EXPIRED'); problem(error.message);
        }
      }).finally(() => { checkingAuth = false; });
    }
  };
}
function failStream(error, selected) {
  if (selected !== generation) return;
  closeStream(); problem(`同步被拒绝：${error.message}。未推断业务状态。`);
  if (error.incompatible) setConnection('INCOMPATIBLE'); else selectProject();
}
async function selectProject() {
  const selected = ++generation; ++pageSerial; closeStream();
  project = projects.find(value => value.id === $('project-select').value);
  if (!project) return;
  $('details').close(); setConnection('CONNECTING');
  problem(state && state.project !== project.id ? `正在切换到 ${project.id}；下方仍是 ${state.project} 的最后快照。` : '');
  try {
    const snapshot = await request(`${base()}/snapshot`);
    if (selected !== generation) return;
    state = installSnapshot(snapshot,project.id,project.data_mode); lastHeard = performance.now(); pageIds = []; nextPage = null; unread = 0;
    $('project-title').textContent = project.id;
    $('mode-note').className = 'notice ' + (project.data_mode === 'fixture' ? 'fixture' : '');
    $('mode-note').textContent = project.data_mode === 'fixture' ? 'FIXTURE / 隔离测试数据，不证明供应商模型或生产运行。' : 'LIVE / 真实公共投影。连接正常不代表模型运行，观察不足会明确显示。';
    problem(''); render(); openStream(selected);
    await Promise.allSettled([loadPage(), loadOverview('execution',30), loadOverview('stage',10)]);
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
$('reduce-motion').checked = motionPreference.matches;
$('reduce-motion').addEventListener('change',stopPulses); motionPreference.addEventListener('change',stopPulses);
document.addEventListener('visibilitychange',stopPulses);
window.addEventListener('offline',() => setConnection('OFFLINE'));
window.addEventListener('online',() => { if (state && session && source) setConnection('RECONNECTING'); });
setInterval(() => { if (state && source && lastHeard && performance.now() - lastHeard > 15000 && connection !== 'STALE') setConnection('STALE'); },1000);
const bootAuth = beginAuth();
authenticated(bootAuth).catch(() => { if (bootAuth.ticket === authGeneration) $('login-panel').hidden = false; });

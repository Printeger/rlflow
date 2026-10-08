// Pure observation reducer: no clock, DOM, network, credentials or authority.
export const MAX_OBJECTS = 200;
export const MAX_EVENTS = 200;
const MAX_SEEN = 1000;
const idPattern = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/;
const kinds = new Set(['stage', 'task', 'execution', 'job', 'proposal', 'approval', 'experiment',
  'evidence', 'hypothesis', 'decision', 'usage', 'package', 'authorization', 'tool_return']);
const toolFields = ['id','kind','version','source_status','observability','state','tool','provenance','exit_code','timed_out',
  'wall_seconds','infrastructure_error','execution_id','task_id','observed_at'];
const opaque = value => typeof value === 'string' && /^ref_[0-9a-f]{64}$/.test(value);
const closed = (value,fields) => value && Object.keys(value).sort().join() === [...fields].sort().join();

export class SyncError extends Error {
  constructor(reason, incompatible = false) { super(reason); this.incompatible = incompatible; }
}
function requireThat(value, reason = 'INVALID_PUBLIC_DATA') {
  if (!value) throw new SyncError(reason, true);
}
function count(value) { return Number.isSafeInteger(value) && value >= 0; }
function identifier(value) { return typeof value === 'string' && idPattern.test(value); }
function timestamp(value) { return typeof value === 'string' && value.endsWith('Z') && Number.isFinite(Date.parse(value)); }
export function cursor(value) {
  requireThat(typeof value === 'string' && value.length <= 200);
  const match = /^([A-Za-z0-9][A-Za-z0-9_.:-]{0,159}):(0|[1-9][0-9]*)$/.exec(value);
  requireThat(match && count(Number(match[2])));
  return {epoch: match[1], seq: Number(match[2])};
}
function checkObject(row) {
  requireThat(row && identifier(row.id) && kinds.has(row.kind) && count(row.version) && row.version > 0);
  requireThat(['PARTIAL', 'OBSERVED', 'UNKNOWN'].includes(row.observability));
  if (row.kind === 'tool_return') {
    requireThat(closed(row,toolFields) && opaque(row.id) && row.version===1 && row.source_status==='COLLECTED' &&
      row.observability==='PARTIAL' && row.tool==='cpu_exec' && row.provenance==='BOUND_RETURN' &&
      Number.isSafeInteger(row.exit_code) && row.exit_code>=-2147483648 && row.exit_code<=2147483647 &&
      typeof row.timed_out==='boolean' && typeof row.wall_seconds==='number' && Number.isFinite(row.wall_seconds) && row.wall_seconds>=0 &&
      [null,'CPU_SANDBOX_SETUP_FAILED'].includes(row.infrastructure_error) && opaque(row.execution_id) &&
      (row.task_id===null || opaque(row.task_id)) && timestamp(row.observed_at), 'INVALID_TOOL_RETURN');
    requireThat(row.state === (row.infrastructure_error!==null ? 'SETUP_FAILED' : row.timed_out ? 'TIMED_OUT' : 'RETURNED'),'INVALID_TOOL_RETURN');
  }
}
function checkToolCoverage(value,seq,version) {
  if (value===undefined || value===null) return null;
  requireThat(closed(value,['status','policy','coverage_after_seq','coverage_after_source_version','source']) &&
    value.status==='PARTIAL' && value.policy==='LIVE_ONLY' && value.source==='BOUND_CPU_RETURN' &&
    count(value.coverage_after_seq) && value.coverage_after_seq<=seq && count(value.coverage_after_source_version) &&
    value.coverage_after_source_version<=version,'INVALID_TOOL_COVERAGE');
  return value;
}
function checkCounters(rows) {
  requireThat(Array.isArray(rows) && rows.length <= 1000);
  const seen = new Set();
  for (const row of rows) {
    requireThat(row && kinds.has(row.kind) && typeof row.status === 'string' && row.status.length <= 160 && count(row.count));
    const key = `${row.kind}/${row.status}`;
    requireThat(!seen.has(key)); seen.add(key);
  }
}
export function objectKey(row) { return `${row.kind}/${row.id}`; }
function recentEvent(event) {
  return {event_id:event.event_id, seq:event.seq, type:event.type, occurred_at:event.occurred_at, recorded_at:event.recorded_at,
    source_event_type:event.payload.source_event_type || event.type,
    changed_count:event.payload.upsert.length + event.payload.removed.length,
    refs:[...event.payload.upsert,...event.payload.removed].slice(0,30).map(objectKey)};
}
function boundedPut(map, key, value, limit) {
  map.delete(key); map.set(key, value);
  while (map.size > limit) map.delete(map.keys().next().value);
}
function putObject(map, key, row) {
  map.delete(key); map.set(key,row);
  if (map.size <= MAX_OBJECTS) return;
  // Preserve only the most recent 30 executions and 10 stages inside the
  // same 200-object cap; unrelated task traffic must not blank live cards.
  const protectedKeys = new Set(), counts = {execution:0,stage:0};
  for (const [candidate,value] of [...map].reverse()) {
    const limit = value.kind === 'execution' ? 30 : value.kind === 'stage' ? 10 : 0;
    if (limit && counts[value.kind]++ < limit) protectedKeys.add(candidate);
  }
  for (const candidate of map.keys()) {
    if (!protectedKeys.has(candidate)) map.delete(candidate);
    if (map.size <= MAX_OBJECTS) break;
  }
}
export function installSnapshot(snapshot, expectedProject, expectedMode) {
  requireThat(snapshot && snapshot.schema_version === '1.0', 'INCOMPATIBLE_SCHEMA');
  requireThat(snapshot.project_id === expectedProject && snapshot.data_mode === expectedMode, 'PROJECT_OR_MODE_MISMATCH');
  const at = cursor(snapshot.cursor);
  requireThat(at.epoch === snapshot.store_epoch && timestamp(snapshot.server_time));
  const projection = snapshot.projection;
  requireThat(projection && count(projection.source_state_version) && typeof projection.paused === 'boolean' && typeof projection.enabled === 'boolean');
  checkCounters(projection.counters);
  requireThat(projection.objects && Array.isArray(projection.objects.items) && projection.objects.items.length <= MAX_OBJECTS && count(projection.objects.total));
  const objects = new Map();
  for (const row of projection.objects.items) {
    checkObject(row); requireThat(!objects.has(objectKey(row)));
    objects.set(objectKey(row), row);
  }
  return {project: expectedProject, mode: expectedMode, epoch: at.epoch, seq: at.seq, cursor: snapshot.cursor,
    sourceVersion: projection.source_state_version, paused: projection.paused, enabled: projection.enabled,
    counters: projection.counters, objects, events: [], seen: new Map(), serverTime: snapshot.server_time,
    toolCoverage:checkToolCoverage(projection.tool_observations,at.seq,projection.source_state_version)};
}
export function applyEvent(state, event, durableId) {
  requireThat(state && event && event.schema_version === '1.0', 'INCOMPATIBLE_SCHEMA');
  requireThat(event.project_id === state.project && event.data_mode === state.mode, 'PROJECT_OR_MODE_MISMATCH');
  const at = cursor(durableId);
  if (at.epoch !== state.epoch || event.store_epoch !== state.epoch) throw new SyncError('EPOCH_CHANGED');
  requireThat(count(event.seq) && event.seq === at.seq && identifier(event.event_id) && timestamp(event.occurred_at) && timestamp(event.recorded_at));
  if (at.seq <= state.seq) return {state, changed: [], duplicate: true};
  if (at.seq !== state.seq + 1) throw new SyncError('SEQUENCE_GAP');
  if (state.seen.has(event.event_id)) throw new SyncError('EVENT_ID_CONFLICT');
  if (event.type !== 'legacy.observed') throw new SyncError('UNKNOWN_CRITICAL_EVENT', true);
  const objects = new Map(state.objects), seen = new Map(state.seen);
  let counters = state.counters, sourceVersion = state.sourceVersion, paused = state.paused, enabled = state.enabled;
  const changed = [];
  if (event.type === 'legacy.observed') {
    const payload = event.payload;
    requireThat(payload && count(payload.source_state_version) && typeof payload.paused === 'boolean' && typeof payload.enabled === 'boolean');
    requireThat(Array.isArray(payload.upsert) && payload.upsert.length <= 200 && Array.isArray(payload.removed) && payload.removed.length <= 200);
    checkCounters(payload.counters);
    // Outbox splits can share a source version, but it must never move backward.
    requireThat(payload.source_state_version >= state.sourceVersion);
    for (const row of payload.upsert) {
      checkObject(row); const key = objectKey(row), old = objects.get(key);
      if (!old || row.version > old.version) { putObject(objects, key, row); changed.push(key); }
    }
    for (const row of payload.removed) {
      requireThat(row && kinds.has(row.kind) && identifier(row.id)); objects.delete(objectKey(row));
    }
    const nextCounters = new Map(counters.map(row => [`${row.kind}/${row.status}`, row]));
    for (const row of payload.counters) {
      const key = `${row.kind}/${row.status}`;
      if (row.count === 0) nextCounters.delete(key); else nextCounters.set(key, row);
    }
    counters = [...nextCounters.values()];
    sourceVersion = payload.source_state_version; paused = payload.paused; enabled = payload.enabled;
  }
  boundedPut(seen, event.event_id, event.seq, MAX_SEEN);
  return {state: {...state, objects, seen, counters, sourceVersion, paused, enabled, seq: at.seq, cursor: durableId,
    serverTime: event.recorded_at, events: [recentEvent(event), ...state.events].slice(0, MAX_EVENTS)}, changed, duplicate: false};
}
export function mergePage(state, page, requestCursor) {
  // Server page and durable reducer state must represent the same commit, not
  // merely share the request's wall-clock start. Never revive deleted objects.
  if (page.cursor !== state.cursor) throw new SyncError('STALE_PAGE');
  requireThat(page.project_id === state.project && page.data_mode === state.mode, 'PROJECT_OR_MODE_MISMATCH');
  requireThat(page && Array.isArray(page.items) && page.items.length <= MAX_OBJECTS && count(page.total));
  const objects = new Map(state.objects);
  for (const row of page.items) {
    checkObject(row); const key = objectKey(row), old = objects.get(key);
    if (!old || row.version > old.version) putObject(objects, key, row);
  }
  return {...state, objects};
}
export function total(state, kind) { return state.counters.filter(row => row.kind === kind).reduce((n, row) => n + row.count, 0); }

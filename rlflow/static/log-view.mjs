import {cursor,SyncError} from './reducer.mjs';
const identifier = value => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(value);
const count = value => Number.isSafeInteger(value) && value >= 0;
const closed = (value,keys) => value && Object.keys(value).sort().join() === [...keys].sort().join();
const fields = ['schema_version','id','project_id','store_epoch','data_mode','source','template_version','event_id','seq','occurred_at','severity','object_count'];
export function checkLogSummary(row,scope) {
  if (!closed(row,fields) || row.schema_version !== '1.0' ||
      !identifier(row.id) || !identifier(row.event_id) || row.project_id !== scope.project || row.data_mode !== scope.mode ||
      row.store_epoch !== scope.epoch || row.source !== 'CORE_STATUS' || row.template_version !== 1 || !count(row.seq) ||
      !count(row.object_count) || !['INFO','WARNING','ERROR'].includes(row.severity) ||
      typeof row.occurred_at !== 'string' || !row.occurred_at.endsWith('Z') || !Number.isFinite(Date.parse(row.occurred_at))) throw new SyncError('INVALID_LOG_SUMMARY',true);
}
export function checkLogPage(value,scope,previousHigh=null) {
  const at = cursor(value?.high_water);
  if (!closed(value,['items','next_cursor','high_water','coverage_after_seq','project_id','data_mode']) || value.project_id !== scope.project || value.data_mode !== scope.mode || at.epoch !== scope.epoch ||
      previousHigh !== null && value.high_water !== previousHigh || !count(value.coverage_after_seq) || value.coverage_after_seq>at.seq ||
      !Array.isArray(value.items) || value.items.length > 200 || value.next_cursor !== null && typeof value.next_cursor !== 'string') throw new SyncError('INVALID_LOG_PAGE',true);
  let previous = at.seq+1;
  const ids = new Set();
  for (const row of value.items) {
    checkLogSummary(row,scope);
    if (row.seq >= previous || row.seq <= value.coverage_after_seq || ids.has(row.id)) throw new SyncError('INVALID_LOG_ORDER',true);
    previous = row.seq; ids.add(row.id);
  }
  return value;
}
export function checkLogBody(value,summary,scope) {
  checkLogSummary(value?.summary,scope);
  if (!closed(value,['summary','text','refs','raw_logs','tool_metadata']) || fields.some(key => value.summary[key] !== summary[key]) || typeof value.text !== 'string' || value.text.length>65536 ||
      !Array.isArray(value.refs) || value.refs.length>600 || value.raw_logs!=='PRIVATE_ONLY' || value.tool_metadata!=='UNAVAILABLE') throw new SyncError('INVALID_LOG_BODY',true);
  const kinds = ['stage','task','execution','job','proposal','approval','experiment','evidence','hypothesis','decision','usage','package','authorization'];
  if (value.refs.some(row => !closed(row,['kind','id','version']) || !kinds.includes(row.kind) || typeof row.id !== 'string' || !/^ref_[0-9a-f]{64}$/.test(row.id) || row.version !== null && !count(row.version))) throw new SyncError('INVALID_LOG_REFS',true);
  return value;
}

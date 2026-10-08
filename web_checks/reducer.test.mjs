import {test} from 'node:test';
import assert from 'node:assert/strict';
import {installSnapshot, applyEvent, mergePage, total, cursor, SyncError} from '../rlflow/static/reducer.mjs';

const time = '2026-10-08T00:00:00.000Z';
const object = (id = 'task_one', version = 1) => ({id, kind:'task', version, observability:'PARTIAL', state:'READY'});
const snapshot = () => ({schema_version:'1.0', project_id:'project_one', data_mode:'fixture', store_epoch:'store_one', cursor:'store_one:0', server_time:time,
  projection:{source_state_version:0, paused:true, enabled:false, counters:[], objects:{items:[], total:0, next_cursor:null}}});
const state = () => installSnapshot(snapshot(), 'project_one', 'fixture');
function event(seq, upsert = [object()], counters = []) {
  return {schema_version:'1.0', project_id:'project_one', data_mode:'fixture', store_epoch:'store_one', seq, event_id:`event_${seq}`,
    type:'legacy.observed', occurred_at:time, recorded_at:time,
    payload:{source_state_version:seq, paused:true, enabled:false, upsert, removed:[], counters}};
}
test('snapshot and seam apply only committed business facts', () => {
  const original = state();
  const next = applyEvent(original, event(1), 'store_one:1').state;
  assert.equal(original.objects.size, 0); assert.equal(next.objects.size, 1);
  assert.equal(next.seq, 1); assert.equal(next.paused, true);
});
test('duplicates do not change cursor, events, counters, or trigger highlights', () => {
  const first = applyEvent(state(), event(1), 'store_one:1').state;
  const duplicate = applyEvent(first, event(1), 'store_one:1');
  assert.equal(duplicate.state, first); assert.deepEqual(duplicate.changed, []); assert.equal(duplicate.duplicate, true);
});
test('gap, epoch, wrong project/mode and critical incompatible schema fail closed', () => {
  for (const [value, id] of [[event(2),'store_one:2'], [{...event(1),store_epoch:'other'},'other:1'],
    [{...event(1),project_id:'other'},'store_one:1'], [{...event(1),data_mode:'live'},'store_one:1'],
    [{...event(1),type:'unknown.critical'},'store_one:1'], [{...event(1),schema_version:'2.0'},'store_one:1']]) {
    assert.throws(() => applyEvent(state(), value, id), SyncError);
  }
});
test('late object versions and counters remain separate from bounded cached objects', () => {
  let current = applyEvent(state(), event(1,[object('task_one',3)],[{kind:'task',status:'READY',count:1000}]), 'store_one:1').state;
  current = applyEvent(current, event(2,[object('task_one',2)]), 'store_one:2').state;
  assert.equal(current.objects.get('task/task_one').version,3); assert.equal(total(current,'task'),1000);
  current = applyEvent(current, event(3,[],[{kind:'task',status:'READY',count:0}]), 'store_one:3').state;
  assert.equal(total(current,'task'),0);
});
test('HTTP page cannot revive entities deleted while the request was in flight', () => {
  let current = applyEvent(state(), event(1), 'store_one:1').state;
  const oldCursor = current.cursor, deletion = event(2,[]); deletion.payload.removed = [{kind:'task',id:'task_one'}];
  current = applyEvent(current,deletion,'store_one:2').state;
  assert.throws(() => mergePage(current,{items:[object()],total:1,cursor:oldCursor},oldCursor), /STALE_PAGE/);
  assert.equal(current.objects.size,0);
});
test('1000 events bound objects, recent rows and duplicate cache', () => {
  let current = state();
  for (let seq=1; seq<=1100; seq++) current = applyEvent(current,event(seq,[object(`task_${seq}`)]),`store_one:${seq}`).state;
  assert.equal(current.objects.size,200); assert.equal(current.events.length,200); assert.equal(current.seen.size,1000);
});
test('event-id reuse and unknown types fail closed without invented metrics', () => {
  const first = applyEvent(state(),event(1),'store_one:1').state;
  assert.throws(() => applyEvent(first,{...event(2),event_id:'event_1'},'store_one:2'), /EVENT_ID_CONFLICT/);
  assert.throws(() => applyEvent(first,{...event(2),type:'optional.note',critical:false},'store_one:2'), /UNKNOWN_CRITICAL_EVENT/);
});
test('cursor rejects unsafe JS integers, leading zeros and malformed public data', () => {
  for (const input of ['store:01','store:-1','store:9007199254740992',null]) assert.throws(() => cursor(input),SyncError);
  assert.throws(() => installSnapshot({...snapshot(),project_id:'wrong'},'project_one','fixture'),SyncError);
  assert.throws(() => applyEvent(state(),event(1,[{...object(),version:-1}]),'store_one:1'),SyncError);
});

test('tool returns are closed partial facts, not execution or task success', () => {
  const ref = 'ref_'+'1'.repeat(64);
  const tool = {id:ref,kind:'tool_return',version:1,source_status:'COLLECTED',observability:'PARTIAL',state:'RETURNED',
    tool:'cpu_exec',provenance:'BOUND_RETURN',exit_code:0,timed_out:false,wall_seconds:0.1,infrastructure_error:null,
    execution_id:'ref_'+'2'.repeat(64),task_id:null,observed_at:time};
  const next = applyEvent(state(),event(1,[tool],[{kind:'tool_return',status:'RETURNED',count:1}]),'store_one:1').state;
  assert.equal(total(next,'tool_return'),1);assert.equal(total(next,'execution'),0);
  for (const mutation of [{stdout:'PRIVATE'},{exit_code:true},{wall_seconds:NaN},{wall_seconds:Infinity},
    {state:'SUCCEEDED'},{state:'TIMED_OUT'},{execution_id:'private_session'},{task_id:['ref_'+'3'.repeat(64)]},{version:2}]) {
    assert.throws(() => applyEvent(state(),event(1,[{...tool,...mutation}]),'store_one:1'),/INVALID_TOOL_RETURN/);
  }
  const coverage = {status:'PARTIAL',policy:'LIVE_ONLY',coverage_after_seq:0,coverage_after_source_version:0,source:'BOUND_CPU_RETURN'};
  const snap = snapshot();snap.projection.tool_observations=coverage;
  assert.equal(installSnapshot(snap,'project_one','fixture').toolCoverage,coverage);
  for (const mutation of [{status:'COMPLETE'},{coverage_after_seq:1},{coverage_after_source_version:1},{raw:'PRIVATE'}]) {
    snap.projection.tool_observations={...coverage,...mutation};
    assert.throws(() => installSnapshot(snap,'project_one','fixture'),/INVALID_TOOL_COVERAGE/);
  }
  assert.equal(state().toolCoverage,null);
});

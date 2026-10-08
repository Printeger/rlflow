import test from 'node:test';
import assert from 'node:assert/strict';
import {checkLogPage,checkLogBody} from '../rlflow/static/log-view.mjs';
const scope = {project:'project_one',mode:'fixture',epoch:'store_one'};
const row = seq => ({schema_version:'1.0',id:`log_${seq}`,event_id:`event_${seq}`,project_id:scope.project,data_mode:scope.mode,
  store_epoch:scope.epoch,source:'CORE_STATUS',template_version:1,seq,occurred_at:'2026-10-08T00:00:00Z',severity:'INFO',object_count:1});
const page = () => ({items:[row(3),row(2)],next_cursor:'logpage/store_one/3/2/filterhash',high_water:'store_one:3',coverage_after_seq:1,project_id:scope.project,data_mode:scope.mode});
test('log cursor is display-only and page high water stays fixed',() => {
  const value = page();assert.equal(checkLogPage(value,scope,'store_one:3'),value);
  assert.throws(() => checkLogPage(value,scope,'store_one:4'));
  for (const mutation of [{project_id:'other'},{data_mode:'live'},{high_water:'store_other:3'},{coverage_after_seq:4},{items:[row(2),row(3)]},{items:[row(1)]},{private_log:'NEVER_SHOW'}]) {
    assert.throws(() => checkLogPage({...value,...mutation},scope));
  }
});
test('body must match selected summary and never accept raw/private extra fields',() => {
  const summary = row(3), value = {summary,text:'Core observed state UNKNOWN',refs:[],raw_logs:'PRIVATE_ONLY',tool_metadata:'UNAVAILABLE'};
  assert.equal(checkLogBody(value,summary,scope),value);
  for (const mutation of [{summary:row(2)},{text:'x'.repeat(65537)},{reasoning:'PRIVATE'},{raw_logs:'PUBLIC'},
    {refs:[{kind:'task',id:'raw_private',version:1}]},{refs:[{kind:'task',id:['ref_'+'0'.repeat(64)],version:1}]},
    {summary:{...summary,source:'MODEL_REASONING'}}]) {
    assert.throws(() => checkLogBody({...value,...mutation},summary,scope));
  }
});

import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {checkFixturePage,checkFixtureTimeline} from '../rlflow/static/fixture-view.mjs';
const original=JSON.parse(readFileSync(new URL('../docs/rlflow_hybrid_spec_v1/evidence/checkpoint-87-public-dashboard/public-task.json',import.meta.url),'utf8'));
const scope={project:original.project_id,mode:original.data_mode,epoch:original.store_epoch};
test('actual authenticated local history satisfies display contract; inflated capabilities and malformed data rejected',()=>{
  assert.equal(checkFixtureTimeline(original,scope,original.task),original);
  const {task,events,configured_result,recorded_settled_usage,...meta}=original;
  assert.equal(checkFixturePage({...meta,items:[task],next_after:null},scope).items.length,1);
  const mutations=[
    v=>v.managed_terminal_proof={},
    v=>v.task.controls_available=true,
    v=>v.task.independent_review_status='PASS',
    v=>v.task.condition_evidence=true,
    v=>v.task.recorded_unknown_exposure.wall_seconds=1,
    v=>v.recorded_settled_usage.experiment_starts=-1,
    v=>v.configured_result.source_id='private',
    v=>v.configured_result.outputs.stdout.text='é'.repeat(32769),
    v=>v.configured_result.machine_acceptance.status='FAIL',
    v=>v.configured_result.approved_acceptance.metrics.mean.min=5,
    v=>v.configured_result.approved_acceptance.metrics.mean.max=Infinity,
    v=>v.configured_result.approved_acceptance.metrics.mean.extra=true,
    v=>v.events.at(-1).state_version--,
  ];
  for(const change of mutations){const value=structuredClone(original);change(value);assert.throws(()=>checkFixtureTimeline(value,scope,task));}
});

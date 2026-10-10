import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {checkFixtureTimeline} from '../rlflow/static/fixture-view.mjs';
test('actual failed and deadline public evidence passes closed display contract without PASS',()=>{
  for(const name of ['nonzero','deadline']){
    const view=JSON.parse(readFileSync(new URL(`../docs/rlflow_hybrid_spec_v1/evidence/checkpoint-89-negative-evidence/${name}-public.json`,import.meta.url),'utf8'));
    const scope={project:view.project_id,mode:view.data_mode,epoch:view.store_epoch};
    assert.equal(checkFixtureTimeline(view,scope,view.task),view);
    assert.equal(view.configured_result.machine_acceptance.status,'FAIL');
    assert.equal(JSON.parse(view.configured_result.outputs.stdout.text).loss,.1);
    const bad=structuredClone(view);bad.configured_result.execution.status='SUCCEEDED';
    assert.throws(()=>checkFixtureTimeline(bad,scope,view.task));
  }
});

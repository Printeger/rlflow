import test from 'node:test';
import assert from 'node:assert/strict';
import {windowFor,ROW_HEIGHT} from '../rlflow/static/virtual-list.mjs';

test('virtual display window is viewport bounded, even for 100k retained rows',() => {
  for (const length of [0,1,200,100000]) for (const top of [0,64,640,5000000]) {
    const plan = windowFor(length,top,340);
    assert.ok(plan.first >= 0 && plan.end <= length && plan.end >= plan.first);
    assert.ok(plan.end-plan.first <= Math.ceil(340/ROW_HEIGHT)+9);
    assert.equal(plan.before+plan.after+(plan.end-plan.first)*ROW_HEIGHT,length*ROW_HEIGHT);
  }
});
test('invalid geometry fails, negative scroll is clamped',() => {
  for (const value of [NaN,Infinity,-1,0.1]) assert.throws(() => windowFor(value,0,340));
  assert.deepEqual(windowFor(200,-100,340),windowFor(200,0,340));
});

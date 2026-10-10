"""Arbitrary patch data and actual managed verification; NOT model autonomy."""
from dataclasses import replace
import hashlib
import json
import time

import pytest

from rlflow.hybrid_engineering_candidate import transform, verification_spec
from rlflow.hybrid_goals import digest
from rlflow.isolated_local_cpu import isolated_session
from rlflow.store import Conflict


def _hash(text):
    return 'sha256:' + hashlib.sha256(text.encode()).hexdigest()


def _patch(files, edits):
    return {'base_sha256': digest(files), 'edits': edits}


def _edit(path, before, after):
    return {'path': path, 'before_sha256': None if before is None else _hash(before), 'after': after}


def test_arbitrary_add_replace_delete_freezes_original_and_criteria():
    original = {'pkg/index.py': 'original\n', 'notes.txt': 'retain', 'obsolete.txt': 'old'}
    edits = [_edit('pkg/index.py', 'original\n', 'replacement with a different size\n'),
             _edit('pkg/settings.json', None, '{"limit":7}'), _edit('obsolete.txt', 'old', None)]
    patch = _patch(original, edits)
    candidate = transform(original, patch, allowed_paths=[row['path'] for row in edits])
    expected = {'pkg/index.py': edits[0]['after'], 'pkg/settings.json': edits[1]['after'], 'notes.txt': 'retain'}
    assert candidate.files() == expected and candidate.output_sha256 == digest(expected)
    original['notes.txt'] = 'caller mutation'; edits[0]['after'] = 'later mutation'
    assert candidate.files() == expected
    spec = verification_spec(candidate, checks='print("approved check",flush=True)', stdout='approved check\n')
    assert json.loads(spec['inputs']['candidate.json'])['files'] == expected
    assert spec['purpose'] == 'engineering'
    assert spec['acceptance']['stdout'] == 'approved check\n'
    with pytest.raises(Conflict): replace(candidate, output_sha256='sha256:' + '0'*64).files()
    with pytest.raises(Conflict): replace(candidate, raw=b'{"a":"x","a":"y"}').files()


@pytest.mark.parametrize('path', ['../escape', '/absolute', 'pkg/../escape', '.git/config',
                                  'pkg/.hidden', 'pkg//file', 'pkg/./file', 'pkg\\file', 'x\x00'])
def test_paths_cannot_escape_or_target_control_material(path):
    files = {'original.py': 'pass\n'}
    with pytest.raises(Conflict):
        transform(files, _patch(files, [_edit(path, None, 'untrusted')]), allowed_paths=[path])


def test_scope_before_base_duplicate_collision_and_bounds_reject():
    files = {'pkg/a.py': 'pass\n'}
    valid = _patch(files, [_edit('pkg/a.py', 'pass\n', 'other')])
    with pytest.raises(Conflict): transform(files, valid, allowed_paths=['other.py'])
    valid['base_sha256'] = 'sha256:'+'0'*64
    with pytest.raises(Conflict): transform(files, valid, allowed_paths=['pkg/a.py'])
    for edits in ([_edit('pkg/a.py', 'wrong', 'other')],
                  [_edit('pkg/a.py', 'pass\n', 'x')]*2,
                  [_edit('missing', None, None)], [_edit('pkg', None, 'collision')],
                  [_edit('pkg/a.py', 'pass\n', 'x'*49153)],
                  [{**_edit('pkg/a.py', 'pass\n', 'x'), 'command': 'ignored?'}]):
        with pytest.raises(Conflict):
            transform(files, _patch(files, edits), allowed_paths=['pkg/a.py', 'missing', 'pkg'])


def test_candidate_freezes_generic_contract_acceptance_and_rejects_override():
    files={'parser.py':'def parse(text):\n return text.splitlines()\n'}
    candidate=transform(files,_patch(files,[_edit('parser.py',files['parser.py'],
        'def parse(text):\n return [row for row in text.splitlines() if row]\n')]),allowed_paths=['parser.py'])
    criteria={'method':'JSON_METRICS_RANGE','metrics':{'cases':{'min':2,'max':2}},'stderr_empty':True}
    spec=verification_spec(candidate,checks='print("checks")',acceptance=criteria)
    criteria['metrics']['cases']['min']=0
    assert spec['acceptance']['metrics']['cases']=={'min':2,'max':2}
    with pytest.raises(Conflict,match='no stdout override'):
        verification_spec(candidate,checks='print("checks")',stdout='checks\n',acceptance=criteria)
    with pytest.raises(Conflict):
        verification_spec(candidate,checks='print("checks")',acceptance={'method':'UNDECLARED','stderr_empty':True})


@pytest.mark.parametrize('matching',[True,False])
def test_actual_candidate_generic_metrics_rule_pass_and_fail_in_managed_cpu(tmp_path,matching):
    # Isolated synthetic local task, NOT actual model output or A workflow.
    tmp_path.chmod(0o700)
    files={'parser.py':'def parse(text):\n return text.splitlines()\n'}
    candidate=transform(files,_patch(files,[_edit('parser.py',files['parser.py'],
        'def parse(text):\n return [row for row in text.splitlines() if row]\n')]),allowed_paths=['parser.py'])
    checks=('from parser import parse\nimport json\n'
        'assert parse("alpha\\n\\nbeta\\n")==["alpha","beta"]\n'
        'assert parse("")==[]\nprint(json.dumps({"cases":2}),flush=True)\n')
    count=2 if matching else 3
    spec=verification_spec(candidate,checks=checks,acceptance={'method':'JSON_METRICS_RANGE',
        'metrics':{'cases':{'min':count,'max':count}},'stderr_empty':True})
    with isolated_session(tmp_path,spec,approved=True,
            confirmation_reader=lambda p,c:'APPROVE '+c['scope_hash']) as session:
        runtime=session['runtime'];lease=session['lease'];attempt=runtime._issued(lease)
        row=runtime.sources._issued(attempt['source']);runtime.start(lease)
        end=time.monotonic()+15
        while row['task_closed'] is None:
            runtime.poll(lease)
            assert time.monotonic()<end
            time.sleep(.02)
        result=runtime.collect_local_result(lease)
        assert result['machine_acceptance']['status']==('PASS' if matching else 'FAIL')
        runtime.stop_to_terminal(lease)
        proof=attempt['terminal']['configured_local_result']
        assert proof==result
        assert runtime.pool.snapshot()['occupied']==0
        assert runtime._current(attempt)['status']=='SETTLED'
        assert runtime.store.audit()==runtime.store.replay()


def test_actual_arbitrary_candidate_runs_only_in_managed_cpu_scope(tmp_path):
    tmp_path.chmod(0o700)
    before = 'def normalize(rows):\n return rows\n'
    after = ('def normalize(rows):\n'
             ' return sorted({row.strip().casefold() for row in rows if row.strip()})\n')
    files = {'package/normalize.py': before, 'package/__init__.py': '', 'settings.json': '{"version":1}'}
    candidate = transform(files, _patch(files, [_edit('package/normalize.py', before, after)]),
                          allowed_paths=['package/normalize.py'])
    checks = ('from package.normalize import normalize\n'
              'assert normalize([" Amber ","BLUE","amber","  ","blue"]) == ["amber","blue"]\n'
              'assert normalize([]) == []\n'
              'import pathlib\n'
              'assert pathlib.Path("settings.json").read_text() == \'{"version":1}\'\n'
              'print("normalization checks passed",flush=True)\n')
    spec = verification_spec(candidate, checks=checks, stdout='normalization checks passed\n')
    # Existing explicit DEVELOPMENT synthetic confirmation; not human/model
    # authority, real engineering-task qualification or independent Reviewer.
    with isolated_session(tmp_path, spec, approved=True,
            confirmation_reader=lambda proposal,confirmation:'APPROVE '+confirmation['scope_hash']) as session:
        runtime=session['runtime']; lease=session['lease']; attempt=runtime._issued(lease)
        runtime.start(lease)
        deadline=time.monotonic()+10
        while attempt['source'] is not None:
            runtime.poll(lease)
            row=runtime.sources._issued(attempt['source'])
            if row['task_closed'] is not None: break
            assert time.monotonic()<deadline
            time.sleep(.01)
        result=runtime.collect_local_result(lease)
        assert result['outputs']['stdout']['text'] == 'normalization checks passed\n'
        assert result['outputs']['stderr']['text'] == ''
        assert result['execution']['status'] == 'SUCCEEDED'
        assert result['machine_acceptance']['status'] == 'PASS'
        assert not result['condition_evidence']
        runtime.stop_to_terminal(lease)
        assert runtime._current(attempt)['status']=='SETTLED'
        assert runtime.pool.snapshot()['occupied']==0
        assert all(fd is None for fd in row['fds'].values())
        assert files['package/normalize.py']==before
        for name,value in [('result',result),('terminal',attempt['terminal']),('command',row['command']),
                           ('candidate',{'base_sha256':candidate.base_sha256,'patch_sha256':candidate.patch_sha256,
                               'output_sha256':candidate.output_sha256,'files':candidate.files()})]:
            (tmp_path/('candidate-'+name+'.json')).write_text(json.dumps(value,sort_keys=True))


def test_actual_failed_checks_cannot_pass_by_printing_expected_stdout(tmp_path):
    tmp_path.chmod(0o700)
    files={'task.py':'VALUE = 1\n'}
    candidate=transform(files,_patch(files,[_edit('task.py',files['task.py'],'VALUE = 2\n')]),
                        allowed_paths=['task.py'])
    spec=verification_spec(candidate,checks='print("matched",flush=True)\nraise AssertionError("rejected")',
                           stdout='matched\n')
    with isolated_session(tmp_path,spec,approved=True,
            confirmation_reader=lambda proposal,confirmation:'APPROVE '+confirmation['scope_hash']) as session:
        runtime=session['runtime'];lease=session['lease'];attempt=runtime._issued(lease)
        runtime.start(lease);deadline=time.monotonic()+10
        row=runtime.sources._issued(attempt['source'])
        while row['task_closed'] is None:
            runtime.poll(lease)
            assert time.monotonic()<deadline
            time.sleep(.01)
        result=runtime.collect_local_result(lease)
        assert result['outputs']['stdout']['text']=='matched\n'
        assert result['execution']['status']=='NONZERO_EXIT'
        assert result['machine_acceptance']['status']=='FAIL'
        runtime.stop_to_terminal(lease)
        assert runtime._current(attempt)['status']=='SETTLED' and runtime.pool.snapshot()['occupied']==0
        assert all(fd is None for fd in row['fds'].values())
        for name,value in [('failed-result',result),('failed-terminal',attempt['terminal']),('failed-command',row['command'])]:
            (tmp_path/('candidate-'+name+'.json')).write_text(json.dumps(value,sort_keys=True))

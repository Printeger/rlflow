"""Actual isolated local copies and held locks, never runtime authorization."""
from datetime import datetime,timedelta,timezone
import json

import pytest

from rlflow.hybrid_snapshot import SnapshotBuilder,CandidateSnapshot
from rlflow.hybrid_working_copy import WorkingCopyOwner,WorkingCopyObservation,ClosedWorkingCopyWitness
from rlflow.hybrid_workspace_kernel import DirectoryHold
from rlflow.store import Conflict


@pytest.fixture
def setup(tmp_path):
    source=tmp_path/'source';source.mkdir(mode=0o700)
    (source/'a.py').write_bytes(b'original\n');(source/'a.py').chmod(0o700)
    library=tmp_path/'library';library.mkdir(mode=0o700)
    namespace=tmp_path/'working';namespace.mkdir(mode=0o700)
    builder=SnapshotBuilder(source,['a.py'],library);base=builder.build()
    clock=[datetime(2026,10,9,tzinfo=timezone.utc),10**9]
    owner=WorkingCopyOwner(builder,namespace,clock=lambda:clock[0],monotonic_ns=lambda:clock[1])
    return builder,base,owner,clock


def slot(owner,observation):return owner._issued[json.loads(observation.raw)['workspace_id']]


def test_real_working_copy_is_distinct_and_preserves_library(setup):
    builder,base,owner,_=setup;observation=owner.acquire(base)
    try:
        value=owner.check(observation);working=slot(owner,observation)['copy']
        assert working.path!=base.path
        assert value['base_snapshot_hash']==json.loads(base.raw)['tree_hash']
        assert value['initial_copy_hash']==json.loads(working.raw)['tree_hash']
        assert value['base_snapshot_hash']!=value['initial_copy_hash'] # executable provenance
        assert value['output_snapshot_hash'] is None and not value['execution_enabled'] and not value['release_enabled']
        (working.path/'a.py').write_bytes(b'fixture-only changed output\n')
        assert (base.path/'a.py').read_bytes()==b'original\n'
        assert builder.verify(base)['tree_hash']==value['base_snapshot_hash']
        # The working-copy observation binds inode/initial copy, not current
        # output content. No false immutable current-output hash is produced.
        assert owner.check(observation)['output_snapshot_hash'] is None
    finally:owner.close_pre_runtime(observation)


@pytest.mark.parametrize('clock_index',[0,1])
def test_either_deadline_expires_but_actual_fd_remains_held(setup,clock_index):
    _,base,owner,clock=setup;observation=owner.acquire(base,ttl_seconds=2)
    working=slot(owner,observation)['copy']
    try:
        clock[clock_index]+=timedelta(seconds=2) if clock_index==0 else 2*10**9
        with pytest.raises(Conflict,match='expired'):owner.check(observation)
        with pytest.raises(Conflict,match='expired'):owner.renew(observation)
        with pytest.raises(Conflict):DirectoryHold(working.path)
    finally:owner.close_pre_runtime(observation)
    next_hold=DirectoryHold(working.path);next_hold.close()


def test_renew_keeps_same_hold_and_invalidates_old_actual_object(setup):
    _,base,owner,_=setup;old=owner.acquire(base);original=slot(owner,old)['hold']
    new=owner.renew(old,ttl_seconds=60)
    try:
        assert slot(owner,new)['hold'] is original
        assert owner.check(new)['epoch']==2
        with pytest.raises(PermissionError):owner.check(old)
        with pytest.raises(PermissionError):owner.close_pre_runtime(old)
        forged=WorkingCopyObservation(new.id,new.raw,new.issued_monotonic_ns,new.expires_monotonic_ns)
        with pytest.raises(PermissionError):owner.check(forged)
    finally:owner.close_pre_runtime(new)


def test_no_snapshot_or_disk_capability_adoption(setup):
    builder,base,owner,clock=setup
    fake=CandidateSnapshot(base.id,base.raw,base.path)
    with pytest.raises(PermissionError):owner.acquire(fake)
    actual=owner.acquire(base)
    try:
        restarted=WorkingCopyOwner(builder,owner.namespace,clock=lambda:clock[0],monotonic_ns=lambda:clock[1])
        with pytest.raises(PermissionError):restarted.check(actual)
    finally:owner.close_pre_runtime(actual)


@pytest.mark.parametrize('ttl',[True,0,61,1.0,None])
def test_invalid_ttl_never_creates_copy(setup,ttl):
    _,base,owner,_=setup;before=list(owner.namespace.iterdir())
    with pytest.raises(Conflict,match='TTL'):owner.acquire(base,ttl_seconds=ttl)
    assert list(owner.namespace.iterdir())==before and not owner._issued


@pytest.mark.parametrize('clock_index',[0,1])
def test_clock_regression_denies_but_explicit_cleanup_still_works(setup,clock_index):
    _,base,owner,clock=setup;observation=owner.acquire(base)
    try:
        clock[clock_index]-=timedelta(seconds=1) if clock_index==0 else 1
        with pytest.raises(Conflict,match='regressed'):owner.check(observation)
    finally:owner.close_pre_runtime(observation)


def test_namespace_rebinding_does_not_adopt_new_directory(setup):
    _,base,owner,_=setup;observation=owner.acquire(base)
    try:
        owner.namespace.rename(owner.namespace.with_name('old-working'))
        owner.namespace.mkdir(mode=0o700)
        with pytest.raises(Conflict,match='rebound'):owner.check(observation)
        with pytest.raises(Conflict,match='rebound'):owner.acquire(base)
    finally:owner.close_pre_runtime(observation)


def test_final_clock_failure_closes_new_fd_but_preserves_artifact(setup):
    _,base,owner,clock=setup;clock[1]=True
    with pytest.raises(Conflict,match='clocks'):owner.acquire(base)
    assert not owner._issued
    paths=list(owner.namespace.iterdir());assert len(paths)==1
    hold=DirectoryHold(paths[0]);hold.close()
    assert (base.path/'a.py').read_bytes()==b'original\n'


@pytest.mark.parametrize('root',['source','library','base'])
def test_working_namespace_cannot_overlap_original_roots(setup,root):
    builder,base,_,_=setup
    path={'source':builder.source,'library':builder.root,'base':base.path}[root]
    with pytest.raises(Conflict,match='disjoint'):WorkingCopyOwner(builder,path)


@pytest.mark.parametrize('alias',['root','child','ancestor'])
def test_physical_alias_rejected_before_copy_io(setup,monkeypatch,alias):
    import rlflow.hybrid_working_copy as module
    from contextlib import contextmanager
    builder,base,owner,_=setup;original=module._chain
    protected=owner._protected_chains[builder.root]
    def no_copy(self):raise AssertionError('copy IO before physical disjointness proof')
    @contextmanager
    def simulated_bind(path):
        with original(path) as (fds,chain):
            if path==owner.namespace:
                if alias=='root':chain=chain[:-1]+(protected[-1][:2]+(chain[-1][2],),)
                elif alias=='child':chain=chain[:-1]+(protected[-1][:2]+(chain[-1][2],),chain[-1])
                else:chain=chain[:-1]+(protected[0][:2]+(chain[-1][2],),)
            yield fds,chain
    monkeypatch.setattr(module,'_chain',simulated_bind);monkeypatch.setattr(SnapshotBuilder,'build',no_copy)
    # Startup must refuse before any mutable copy is made. Simulation only;
    # no mount privilege or host mount mutation is requested by this test.
    with pytest.raises(Conflict,match='physical roots overlap'):
        WorkingCopyOwner(builder,owner.namespace)


@pytest.mark.parametrize('raw',[b'invalid',b'['*3000+b']'*3000,b'"'+b'x'*1024**2+b'"'])
def test_forged_exact_type_denied_before_any_json_parse(setup,monkeypatch,raw):
    _,base,owner,_=setup;actual=owner.acquire(base)
    forged=WorkingCopyObservation(actual.id,raw,actual.issued_monotonic_ns,actual.expires_monotonic_ns)
    def forbidden(*args,**kwargs):raise AssertionError('unissued object parsed')
    monkeypatch.setattr(json,'loads',forbidden)
    try:
        with pytest.raises(PermissionError):owner.check(forged)
        with pytest.raises(PermissionError):owner.close_pre_runtime(forged)
    finally:
        monkeypatch.undo();owner.close_pre_runtime(actual)


def test_physical_close_success_is_actual_witness_not_json_or_forged_copy(setup,monkeypatch):
    _,base,owner,_=setup;observation=owner.acquire(base);witness=owner.close_pre_runtime(observation)
    value=owner.check_closed_witness(witness)
    assert value['workspace_id']==json.loads(observation.raw)['workspace_id']
    assert value['state']=='CLOSED_PRE_RUNTIME' and not owner._issued
    forged=ClosedWorkingCopyWitness(witness.id,b'['*3000,observation)
    def forbidden(*args,**kwargs):raise AssertionError('unissued close object parsed')
    monkeypatch.setattr(json,'loads',forbidden)
    try:
        with pytest.raises(PermissionError):owner.check_closed_witness(forged)
    finally:monkeypatch.undo()
    owner.retire_closed_witness(witness)
    with pytest.raises(PermissionError):owner.check_closed_witness(witness)


def test_physical_close_failure_never_mints_success_witness(setup,monkeypatch):
    _,base,owner,_=setup;observation=owner.acquire(base);held=slot(owner,observation)['hold']
    def fail():raise Conflict('disposable physical close fault')
    monkeypatch.setattr(held,'close',fail)
    try:
        with pytest.raises(Conflict,match='physical close fault'):owner.close_pre_runtime(observation)
        assert not owner._closed_witnesses and slot(owner,observation)['hold'] is held
        with pytest.raises(Conflict):DirectoryHold(slot(owner,observation)['copy'].path)
    finally:monkeypatch.undo();owner.close_pre_runtime(observation)


def test_close_witness_mint_failure_retains_actual_closed_slot_for_explicit_retry(setup,monkeypatch):
    import rlflow.hybrid_working_copy as module
    _,base,owner,_=setup;observation=owner.acquire(base);held=slot(owner,observation)['hold']
    def fail(*args):raise Conflict('disposable close witness mint fault')
    monkeypatch.setattr(module,'canonical',fail)
    try:
        with pytest.raises(Conflict,match='mint fault'):owner.close_pre_runtime(observation)
        assert slot(owner,observation)['hold'] is held and held._closed and not owner._closed_witnesses
        with pytest.raises(Conflict,match='closed'):owner.check(observation)
    finally:monkeypatch.undo()
    witness=owner.close_pre_runtime(observation)
    assert owner.check_closed_witness(witness)['state']=='CLOSED_PRE_RUNTIME'
    owner.retire_closed_witness(witness)

"""Preallocated actual renewal only; persistent transaction integration pending."""
from datetime import timedelta
import json
import fcntl

import pytest

from rlflow.hybrid_working_copy import PendingRenewal
from rlflow.hybrid_workspace_kernel import DirectoryHold
from rlflow.store import Conflict
from tests.test_hybrid_working_copy import setup,slot


def test_candidate_is_not_current_until_original_memory_activation(setup):
    _,base,owner,_=setup;old=owner.acquire(base);held=slot(owner,old)['hold']
    pending=owner.prepare_renewal(old,ttl_seconds=60)
    try:
        assert owner.check(old)['epoch']==1 and slot(owner,old)['epoch']==1
        with pytest.raises(PermissionError):owner.check(pending.candidate)
        assert owner.check_renewal(pending)['candidate']['epoch']==2
        with pytest.raises(Conflict,match='unresolved'):owner.renew(old)
        with pytest.raises(Conflict,match='unresolved'):owner.prepare_renewal(old)
        with pytest.raises(Conflict,match='unresolved'):owner.close_pre_runtime(old)
        assert owner._activate_renewal(pending) is pending.candidate
        assert owner._activate_renewal(pending) is pending.candidate
        assert slot(owner,pending.candidate)['hold'] is held
        assert owner.check(pending.candidate)['epoch']==2
        with pytest.raises(PermissionError):owner.check(old)
        with pytest.raises(Conflict,match='activated'):owner.abort_renewal(pending)
        with pytest.raises(Conflict,match='unresolved'):owner.close_pre_runtime(pending.candidate)
        owner._retire_renewal(pending)
        with pytest.raises(PermissionError):owner.check_renewal(pending)
    finally:
        if owner._renewals:owner._retire_renewal(pending)
        owner.close_pre_runtime(pending.candidate)


def test_definite_abort_keeps_original_object_epoch_and_exclusive_fd(setup):
    _,base,owner,_=setup;old=owner.acquire(base);original=slot(owner,old)
    pending=owner.prepare_renewal(old)
    owner.abort_renewal(pending)
    try:
        assert slot(owner,old) is original and owner.check(old)['epoch']==1
        assert not owner._renewals
        with pytest.raises(PermissionError):owner._activate_renewal(pending)
        with pytest.raises(Conflict):DirectoryHold(original['copy'].path)
    finally:owner.close_pre_runtime(old)


@pytest.mark.parametrize('clock_index',[0,1])
def test_expired_candidate_ack_is_only_cleanup_lineage(setup,clock_index):
    _,base,owner,clock=setup;old=owner.acquire(base,ttl_seconds=1)
    pending=owner.prepare_renewal(old,ttl_seconds=2)
    clock[clock_index]+=timedelta(seconds=2) if clock_index==0 else 2*10**9
    with pytest.raises(Conflict,match='expired'):owner.check_renewal(pending)
    assert owner.check_renewal(pending,live=False)['candidate']==json.loads(pending.candidate.raw)
    owner._activate_renewal(pending);owner._retire_renewal(pending)
    with pytest.raises(Conflict,match='expired'):owner.check(pending.candidate)
    witness=owner.close_pre_runtime(pending.candidate)
    assert witness.observation is pending.candidate
    owner.retire_closed_witness(witness)


def test_foreign_and_copied_pending_identity_before_json(setup,monkeypatch):
    _,base,owner,_=setup;old=owner.acquire(base);pending=owner.prepare_renewal(old)
    fake=PendingRenewal(pending.id,None,None)
    def no_parse(*args,**kwargs):raise AssertionError('parsed forged pending')
    with monkeypatch.context() as patch:
        patch.setattr('rlflow.hybrid_working_copy.json.loads',no_parse)
        with pytest.raises(PermissionError):owner.check_renewal(fake)
        with pytest.raises(PermissionError):owner._activate_renewal(fake)
        with pytest.raises(PermissionError):owner.abort_renewal(fake)
    owner.abort_renewal(pending);owner.close_pre_runtime(old)


def test_candidate_kernel_loss_never_reflocks_for_ack(setup):
    _,base,owner,_=setup;old=owner.acquire(base);pending=owner.prepare_renewal(old)
    held=slot(owner,old)['hold']
    fcntl.flock(held._fd,fcntl.LOCK_UN)
    try:
        with pytest.raises(Conflict):owner.check_renewal(pending,live=False)
        competitor=DirectoryHold(slot(owner,old)['copy'].path);competitor.close()
    finally:owner.abort_renewal(pending);owner.close_pre_runtime(old)


@pytest.mark.parametrize('ttl',[True,0,61,1.0,None])
def test_invalid_pending_ttl_leaves_old_live(setup,ttl):
    _,base,owner,_=setup;old=owner.acquire(base)
    try:
        with pytest.raises(Conflict,match='TTL'):owner.prepare_renewal(old,ttl_seconds=ttl)
        assert owner.check(old)['epoch']==1 and not owner._renewals
    finally:owner.close_pre_runtime(old)


@pytest.mark.parametrize('field',['observation','epoch'])
def test_each_partial_activation_assignment_is_repaired_same_epoch(setup,field):
    _,base,owner,_=setup;old=owner.acquire(base);pending=owner.prepare_renewal(old)
    entry=owner._renewals[pending.id];original=entry['slot']
    class FaultSlot(dict):
        fired=False
        def __setitem__(self,key,value):
            super().__setitem__(key,value)
            if key==field and not self.fired:
                self.fired=True;raise MemoryError('partial '+field)
    faulty=FaultSlot(original);entry['slot']=faulty
    owner._issued[faulty['binding']['workspace_id']]=faulty
    with pytest.raises(MemoryError,match='partial'):owner._activate_renewal(pending)
    assert owner.check_renewal(pending,live=False)['candidate']['epoch']==2
    with pytest.raises(Conflict,match='unresolved'):owner.prepare_renewal(faulty['observation'])
    owner._activate_renewal(pending);owner._activate_renewal(pending)
    assert faulty['epoch']==2 and faulty['observation'] is pending.candidate
    assert faulty['hold'] is original['hold']
    owner._retire_renewal(pending);owner.close_pre_runtime(pending.candidate)


@pytest.mark.parametrize('operation',['attach','abort','retire'])
def test_canonical_pending_mutation_has_no_second_dangling_slot_write(setup,operation):
    _,base,owner,_=setup;old=owner.acquire(base)
    class FaultRegistry(dict):
        fired=False
        def __setitem__(self,key,value):
            super().__setitem__(key,value)
            if operation=='attach' and not self.fired:
                self.fired=True;raise MemoryError('lost attach return')
        def __delitem__(self,key):
            super().__delitem__(key)
            if operation!='attach' and not self.fired:
                self.fired=True;raise MemoryError('completed delete return')
    owner._renewals=FaultRegistry()
    if operation=='attach':
        with pytest.raises(MemoryError,match='lost attach'):owner.prepare_renewal(old)
        pending=owner.pending_renewal(old)
        assert type(pending) is PendingRenewal and len(owner._renewals)==1
        with pytest.raises(Conflict,match='unresolved'):owner.prepare_renewal(old)
        owner.abort_renewal(pending);current=old
    else:
        pending=owner.prepare_renewal(old)
        if operation=='retire':owner._activate_renewal(pending)
        with pytest.raises(MemoryError,match='completed delete'):
            (owner._retire_renewal if operation=='retire' else owner.abort_renewal)(pending)
        current=pending.candidate if operation=='retire' else old
        assert owner.pending_renewal(current) is None and not owner._renewals
    assert slot(owner,current)['hold'] is not None
    owner.close_pre_runtime(current)

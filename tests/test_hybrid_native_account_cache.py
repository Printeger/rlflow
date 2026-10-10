"""Temporary synthetic cache only; NEVER access the real host credentials."""
import os
import subprocess

import pytest

from rlflow.hybrid_native_account_cache import _AccountCache
from rlflow.store import Conflict
from tests.test_hybrid_a_workflow_derivation import original,native_setup,FILES

ACTUAL_POPEN=subprocess.Popen


def cache_for(source,destination):
    info=os.stat(destination)
    return _AccountCache(str(source),destination,destination_identity=(info.st_dev,info.st_ino))


@pytest.fixture
def account_original(native_setup,request):
    # Use the original fixture's already isolated CLI home. That fixture sets
    # CODEX_HOME itself; setting it before resolving it would be overwritten.
    home=native_setup[4]
    auth=home/'auth.json';auth.write_bytes(b'{"synthetic":"NOT_A_TOKEN"}');auth.chmod(0o600)
    return request.getfixturevalue('original'),home


def test_original_controller_prepares_synthetic_cache_and_stop_cleans_it(account_original,monkeypatch):
    (owner,bundle,token,obs,claim),home=account_original
    grant=owner.issue_workflow_engineer_grant(bundle,token,obs,files=FILES)
    lease=owner.register(bundle,token,obs,claim,request_key='account_cache',
        scenario='native_model',native_model_grant=grant)
    attempt=owner._issued(lease);source=attempt['source'];row=owner.sources._issued(source)
    owner.prepare_native_gate(lease)
    with pytest.raises(PermissionError,match='active Controller'):
        owner.sources._prepare_current_account_cache(owner,lease)
    assert id(source) not in owner.sources._account_caches
    versions=(owner.store.version(),owner.pool.snapshot()['version'])
    result=owner.prepare_current_account_cache(lease)
    assert result['cache_staged'] and not result['account_qualified']
    assert (row['path']/'auth-private'/'auth.json').read_bytes()==(home/'auth.json').read_bytes()
    assert row['producer'] is None and not attempt['release_entered']
    assert (owner.store.version(),owner.pool.snapshot()['version'])==versions
    with pytest.raises(PermissionError):owner.start(lease)
    with pytest.raises(Conflict):owner.prepare_current_account_cache(lease)
    def python_gate_only(argv,*args,**kwargs):
        assert argv[1:4]==['-B','-I','-S'] and argv[7]=='native_model'
        return ACTUAL_POPEN(argv,*args,**kwargs)
    monkeypatch.setattr(subprocess,'Popen',python_gate_only)
    ready=owner.prepare_no_release_producer(lease)
    assert ready['sandbox_ready'] and not ready['account_qualified'] and not ready['model_released']
    assert 'python' in os.readlink('/proc/'+str(row['producer'].pid)+'/exe')
    owner.stop_to_terminal(lease)
    cache=owner.sources._account_caches[id(source)]
    assert not cache.pending and not cache.descriptors()
    assert not (row['path']/'auth-private'/'auth.json').exists()
    assert (home/'auth.json').read_bytes()==b'{"synthetic":"NOT_A_TOKEN"}'
    assert owner.pool.snapshot()['occupied']==0
    assert owner._current(attempt)['status']=='UNKNOWN'
    assert owner.store.audit()==owner.store.replay()


def test_bounded_private_copy_is_not_authentication_and_stop_removes_only_copy(tmp_path):
    source=tmp_path/'host';source.mkdir(mode=0o700)
    destination=tmp_path/'session';destination.mkdir(mode=0o700)
    auth=source/'auth.json';auth.write_bytes(b'{"synthetic":"NOT_A_TOKEN"}');auth.chmod(0o600)
    cache=cache_for(source,destination);checks=[]
    result=cache.stage(lambda:checks.append(True))
    assert len(checks)==2 and result=={'cache_staged':True,'account_qualified':False,'model_released':False}
    assert (destination/'auth.json').read_bytes()==auth.read_bytes()
    assert os.stat(destination/'auth.json').st_mode&0o777==0o600
    with pytest.raises(Conflict):cache.stage(lambda:None)
    cache.close();cache.close()
    assert auth.read_bytes()==b'{"synthetic":"NOT_A_TOKEN"}'
    assert not (destination/'auth.json').exists() and cache.descriptors()==()


@pytest.mark.parametrize('damage',['symlink','mode','oversize','denied'])
def test_bad_or_unapproved_cache_never_copies_and_retained_fds_close(tmp_path,damage):
    source=tmp_path/'host';source.mkdir(mode=0o700)
    destination=tmp_path/'session';destination.mkdir(mode=0o700)
    auth=source/'auth.json';auth.write_bytes(b'fake');auth.chmod(0o600)
    if damage=='mode':auth.chmod(0o644)
    if damage=='oversize':auth.write_bytes(b'x'*65537)
    if damage=='symlink':
        auth.rename(source/'other');auth.symlink_to('other')
    def gate():
        if damage=='denied':raise PermissionError('original Controller deny')
    cache=cache_for(source,destination)
    with pytest.raises((Conflict,OSError,PermissionError)):cache.stage(gate)
    cache.close()
    assert not (destination/'auth.json').exists() and cache.descriptors()==()


@pytest.mark.parametrize('damage',['renamed','replaced'])
def test_secret_inode_replacement_never_deletes_other_file_or_reports_clean(tmp_path,damage):
    source=tmp_path/'host';source.mkdir(mode=0o700)
    destination=tmp_path/'session';destination.mkdir(mode=0o700)
    auth=source/'auth.json';auth.write_bytes(b'fake');auth.chmod(0o600)
    cache=cache_for(source,destination);cache.stage(lambda:None)
    target=destination/'auth.json';target.rename(destination/'original-renamed')
    if damage=='replaced':target.write_bytes(b'other file');target.chmod(0o600)
    with pytest.raises(Conflict):cache.close()
    assert cache.pending and cache.descriptors()
    assert (destination/'original-renamed').read_bytes()==b'fake'
    if damage=='replaced':
        assert target.read_bytes()==b'other file'
        target.rename(destination/'other-preserved')
    (destination/'original-renamed').rename(target)
    cache.close();assert not cache.pending and cache.descriptors()==()


def test_destination_open_swap_restore_rejected_before_copy(tmp_path,monkeypatch):
    source=tmp_path/'host';source.mkdir(mode=0o700)
    destination=tmp_path/'session';destination.mkdir(mode=0o700)
    foreign=tmp_path/'foreign';foreign.mkdir(mode=0o700)
    auth=source/'auth.json';auth.write_bytes(b'fake');auth.chmod(0o600)
    cache=cache_for(source,destination);original_directory=cache._directory
    def swapped(path):
        if path!=destination:return original_directory(path)
        destination.rename(tmp_path/'original-session');foreign.rename(destination)
        try:return original_directory(destination)
        finally:
            destination.rename(foreign);(tmp_path/'original-session').rename(destination)
    monkeypatch.setattr(cache,'_directory',swapped)
    with pytest.raises(Conflict,match='frozen session'):cache.stage(lambda:None)
    assert not (destination/'auth.json').exists() and not (foreign/'auth.json').exists()
    cache.close();assert cache.descriptors()==()


def test_missing_name_target_fstat_error_preserves_cleanup_cap_but_closes_other_fds(tmp_path,monkeypatch):
    source=tmp_path/'host';source.mkdir(mode=0o700)
    destination=tmp_path/'session';destination.mkdir(mode=0o700)
    auth=source/'auth.json';auth.write_bytes(b'fake');auth.chmod(0o600)
    cache=cache_for(source,destination);cache.stage(lambda:None)
    (destination/'auth.json').unlink()
    fstat=os.fstat
    def failed(fd):
        if fd==cache.target_fd:raise OSError('synthetic target identity unavailable')
        return fstat(fd)
    with monkeypatch.context() as patch:
        patch.setattr(os,'fstat',failed)
        with pytest.raises(Conflict,match='cleanup incomplete'):cache.close()
    assert cache.pending and set(cache.descriptors())=={cache.target_fd,cache.destination_fd}
    cache.close();assert not cache.pending and cache.descriptors()==()


@pytest.mark.parametrize('failure',['expiry','stop'])
def test_original_final_effect_gate_after_source_io_blocks_first_secret_read(account_original,monkeypatch,failure):
    from datetime import timedelta
    (owner,bundle,token,obs,claim),home=account_original
    grant=owner.issue_workflow_engineer_grant(bundle,token,obs,files=FILES)
    lease=owner.register(bundle,token,obs,claim,request_key='late_gate',
        scenario='native_model',native_model_grant=grant)
    attempt=owner._issued(lease);source=attempt['source'];row=owner.sources._issued(source)
    owner.prepare_native_gate(lease)
    identity=os.stat(home/'auth.json');secret_reads=[];pread=os.pread
    def observed(fd,*args):
        info=os.fstat(fd)
        if (info.st_dev,info.st_ino)==(identity.st_dev,identity.st_ino):secret_reads.append(True)
        return pread(fd,*args)
    fresh=owner._fresh;sample=owner.controller._sample
    def late(*args):
        fresh(*args)
        if id(source) in owner.sources._account_caches:
            if failure=='stop':attempt['source_stop_latched']=True
            else:
                now,mono=sample()
                monkeypatch.setattr(owner.controller,'_sample',lambda:(now+timedelta(hours=1),mono+3600*10**9))
    with monkeypatch.context() as patch:
        patch.setattr(os,'pread',observed);patch.setattr(owner,'_fresh',late)
        with pytest.raises(Conflict):owner.prepare_current_account_cache(lease)
    monkeypatch.setattr(owner.controller,'_sample',sample)
    assert secret_reads==[] and not (row['path']/'auth-private'/'auth.json').exists()
    owner.stop_to_terminal(lease)
    cache=owner.sources._account_caches[id(source)]
    assert cache.descriptors()==() and owner.pool.snapshot()['occupied']==0

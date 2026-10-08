"""Real local file copies/hashes, no model, process, Git or execution gate."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from rlflow import hybrid_snapshot as module
from rlflow.hybrid_snapshot import SnapshotBuilder, CandidateSnapshot
from rlflow.store import Conflict, sha


@pytest.fixture
def setup(tmp_path):
    source = tmp_path/'source'; source.mkdir()
    control = tmp_path/'private'; control.mkdir(mode=0o700)
    (source/'module').mkdir(); (source/'module/a.py').write_bytes(b'print(42)\n')
    (source/'module/b.txt').write_bytes('实际字节'.encode())
    (source/'not-approved').mkdir(); (source/'not-approved/secret').write_text('not copied')
    builder = SnapshotBuilder(source, ['module/a.py', 'module/b.txt'], control)
    return source, control, builder


def test_real_copy_descriptor_and_closed_inventory(setup):
    source, control, builder = setup
    snapshot = builder.build(); value = json.loads(snapshot.raw)
    expected = [{'name': name, 'bytes': len((source/name).read_bytes()),
                 'sha256': hashlib.sha256((source/name).read_bytes()).hexdigest(),
                 'mode': 0o600, 'source_executable': False}
                for name in builder.names]
    assert value == {'schema_version': '1.0', 'files': expected,
        'total_bytes': sum(r['bytes'] for r in expected), 'tree_hash': 'sha256:'+sha(expected),
        'execution_enabled': False}
    assert not (snapshot.path/'not-approved').exists()
    for row in expected:
        assert (snapshot.path/row['name']).read_bytes() == (source/row['name']).read_bytes()
        assert (snapshot.path/row['name']).stat().st_mode & 0o777 == 0o600
    assert (snapshot.path/'module').stat().st_mode & 0o777 == 0o700
    assert builder.verify(snapshot)['tree_hash'] == value['tree_hash']
    # Descriptor names copied content, not a promise the mutable source is now identical.
    (source/'module/a.py').write_text('changed source later')
    assert builder.verify(snapshot)['tree_hash'] == value['tree_hash']
    second = builder.build()
    assert second.path != snapshot.path and json.loads(second.raw)['tree_hash'] != value['tree_hash']


def test_no_mutable_input_or_forged_snapshot_adoption(setup):
    source, control, builder = setup
    names = ['module/a.py']; other = SnapshotBuilder(source, names, control); names.append('missing')
    snapshot = other.build()
    assert other.names == ('module/a.py',)
    fake = CandidateSnapshot(snapshot.id, snapshot.raw, snapshot.path)
    with pytest.raises(PermissionError): other.verify(fake)
    with pytest.raises(PermissionError): builder.verify(snapshot)
    restarted = SnapshotBuilder(source, ['module/a.py'], control)
    with pytest.raises(PermissionError): restarted.verify(snapshot)


@pytest.mark.parametrize('bad', ['generator', 'empty', 'too_many', 'duplicate', 'ancestor', 'traversal',
                               'absolute', 'backslash', 'null', 'surrogate', 'long', 'deep'])
def test_manifest_checked_before_directory_io(tmp_path, monkeypatch, bad):
    names = ['file']
    if bad == 'generator': names = (x for x in names)
    elif bad == 'empty': names = []
    elif bad == 'too_many': names = ['file']*4097
    elif bad == 'duplicate': names *= 2
    elif bad == 'ancestor': names = ['a', 'a/b']
    elif bad == 'traversal': names = ['a/../b']
    elif bad == 'absolute': names = ['/a']
    elif bad == 'backslash': names = ['a\\b']
    elif bad == 'null': names = ['a\x00b']
    elif bad == 'surrogate': names = ['a\ud800b']
    elif bad == 'long': names = ['a'*4001]
    else: names = ['/'.join(['a']*65)]
    def forbidden(*args, **kwargs): raise AssertionError('directory IO before manifest rejection')
    monkeypatch.setattr(module, '_directory', forbidden)
    with pytest.raises(Conflict): SnapshotBuilder(tmp_path/'missing', names, tmp_path/'missing-control')


@pytest.mark.parametrize('bad', ['boolean', 'float', 'too_large', 'zero', 'nan', 'infinite', 'too_long'])
def test_limits_fail_closed(setup, bad):
    source, control, _ = setup; kwargs = {}
    if bad == 'boolean': kwargs['byte_limit'] = True
    elif bad == 'float': kwargs['byte_limit'] = 1.0
    elif bad == 'too_large': kwargs['byte_limit'] = module.MAX_BYTES+1
    elif bad == 'zero': kwargs['seconds'] = 0
    elif bad == 'nan': kwargs['seconds'] = float('nan')
    elif bad == 'infinite': kwargs['seconds'] = float('inf')
    else: kwargs['seconds'] = 31
    with pytest.raises(Conflict): SnapshotBuilder(source, ['module/a.py'], control, **kwargs)


@pytest.mark.parametrize('bad', ['source_link', 'source_ancestor_link', 'control_link', 'overlap', 'control_mode'])
def test_roots_are_descriptor_relative_private_and_disjoint(setup, tmp_path, bad):
    source, control, _ = setup
    if bad == 'source_link':
        link = tmp_path/'source-link'; link.symlink_to(source, target_is_directory=True); source = link
    elif bad == 'source_ancestor_link':
        link = tmp_path/'ancestor'; link.symlink_to(tmp_path, target_is_directory=True); source = link/'source'
    elif bad == 'control_link':
        link = tmp_path/'control-link'; link.symlink_to(control, target_is_directory=True); control = link
    elif bad == 'overlap': control = source/'private'; control.mkdir(mode=0o700)
    else: control.chmod(0o755)
    with pytest.raises(Conflict): SnapshotBuilder(source, ['module/a.py'], control)


@pytest.mark.parametrize('bad', ['fifo', 'file_link', 'dir_link', 'hardlink', 'directory', 'oversize', 'missing'])
def test_source_refusal_is_bounded_and_cleans_own_stage(setup, tmp_path, bad):
    source, control, builder = setup; target = source/'module/a.py'
    retained = control/'retained'; retained.mkdir(mode=0o700); (retained/'sentinel').write_text('retained')
    if bad == 'fifo': target.unlink(); os.mkfifo(target)
    elif bad == 'file_link': target.unlink(); target.symlink_to(source/'module/b.txt')
    elif bad == 'dir_link':
        (source/'module').rename(source/'old-module'); (source/'module').symlink_to(source/'old-module', target_is_directory=True)
    elif bad == 'hardlink': os.link(target, tmp_path/'linked')
    elif bad == 'directory': target.unlink(); target.mkdir()
    elif bad == 'oversize':
        builder = SnapshotBuilder(source, ['module/a.py'], control, byte_limit=2)
    else: target.unlink()
    with pytest.raises(Conflict): builder.build()
    assert list(control.iterdir()) == [retained] and (retained/'sentinel').read_text() == 'retained'


def test_aggregate_byte_limit_not_per_file(setup):
    source, control, _ = setup
    first = (source/'module/a.py').stat().st_size; second = (source/'module/b.txt').stat().st_size
    builder = SnapshotBuilder(source, ['module/a.py', 'module/b.txt'], control, byte_limit=first+second-1)
    with pytest.raises(Conflict, match='budget'): builder.build()
    assert not list(control.iterdir())


@pytest.mark.parametrize('mutation', ['grow', 'change', 'replace', 'directory_replace'])
def test_source_changes_during_stream_are_not_accepted(setup, monkeypatch, mutation):
    source, control, builder = setup; target = source/'module/a.py'; inode = target.stat().st_ino
    original = module.os.read; mutated = [False]
    def reading(fd, size):
        result = original(fd, size)
        if result and os.fstat(fd).st_ino == inode and not mutated[0]:
            mutated[0] = True
            if mutation == 'grow':
                with target.open('ab') as stream: stream.write(b'extra')
            elif mutation == 'change': target.write_bytes(b'changed!!\n')
            elif mutation == 'replace':
                target.rename(target.with_name('old')); target.write_bytes(result)
            else:
                target.parent.rename(source/'old-module'); (source/'module').mkdir()
                (source/'module/a.py').write_bytes(result)
        return result
    monkeypatch.setattr(module.os, 'read', reading)
    with pytest.raises(Conflict): builder.build()
    assert mutated[0] and not list(control.iterdir())


@pytest.mark.parametrize('root', ['source', 'control'])
def test_root_rebind_before_copy_rejects(setup, root):
    source, control, builder = setup; path = source if root == 'source' else control
    path.rename(path.with_name(path.name+'.old')); path.mkdir(mode=0o700)
    with pytest.raises(Conflict): builder.build()


@pytest.mark.parametrize('bad', ['bytes', 'extra_file', 'extra_dir', 'fifo', 'file_link', 'dir_link', 'hardlink', 'mode', 'owner_exec', 'dir_mode', 'root_rebind'])
def test_copy_tamper_or_unexpected_inventory_rejected(setup, tmp_path, bad):
    _, _, builder = setup; snapshot = builder.build(); target = snapshot.path/'module/a.py'
    if bad == 'bytes': target.write_bytes(b'changed!!\n')
    elif bad == 'extra_file': (snapshot.path/'extra').write_text('unexpected')
    elif bad == 'extra_dir': (snapshot.path/'extra').mkdir()
    elif bad == 'fifo': target.unlink(); os.mkfifo(target, mode=0o600)
    elif bad == 'file_link': target.unlink(); target.symlink_to(snapshot.path/'module/b.txt')
    elif bad == 'dir_link':
        (snapshot.path/'module').rename(snapshot.path/'old-module')
        (snapshot.path/'module').symlink_to(snapshot.path/'old-module', target_is_directory=True)
    elif bad == 'hardlink': os.link(target, tmp_path/'linked-copy')
    elif bad == 'mode': target.chmod(0o644)
    elif bad == 'owner_exec': target.chmod(0o700)
    elif bad == 'dir_mode': (snapshot.path/'module').chmod(0o755)
    else:
        snapshot.path.rename(snapshot.path.with_name(snapshot.id+'.old')); snapshot.path.mkdir(mode=0o700)
    with pytest.raises(Conflict): builder.verify(snapshot)


def test_cooperative_deadline_without_sleep_cleans_stage(setup):
    source, control, _ = setup; calls = [0]
    def clock():
        calls[0] += 1
        return 0 if calls[0] < 5 else 31
    builder = SnapshotBuilder(source, ['module/a.py'], control, clock=clock)
    with pytest.raises(Conflict, match='deadline'): builder.build()
    assert calls[0] >= 5 and not list(control.iterdir())


def test_no_directory_discovery_or_git_invocation(setup, monkeypatch):
    source, control, builder = setup
    def forbidden(*args, **kwargs): raise AssertionError('no source discovery or process allowed')
    import subprocess
    monkeypatch.setattr(subprocess, 'run', forbidden); monkeypatch.setattr(subprocess, 'Popen', forbidden)
    original = module.os.scandir
    def scanning(path):
        assert type(path) is int  # bounded constructed copy only, never the source tree
        assert Path(os.readlink('/proc/self/fd/'+str(path))).is_relative_to(control)
        return original(path)
    monkeypatch.setattr(module.os, 'scandir', scanning)
    assert builder.verify(builder.build())['execution_enabled'] is False


def test_source_executable_is_metadata_copy_mode_is_exact_private(setup):
    source, _, builder = setup
    (source/'module/a.py').chmod(0o755)
    snapshot = builder.build(); rows = json.loads(snapshot.raw)['files']
    assert rows[0]['source_executable'] is True and rows[0]['mode'] == 0o600
    assert (snapshot.path/rows[0]['name']).stat().st_mode & 0o777 == 0o600
    assert builder.verify(snapshot)['execution_enabled'] is False


def test_fsync_failure_releases_issued_capacity_and_cleans_own_stage(setup, monkeypatch):
    _, control, builder = setup; original = module.os.fsync; inode = control.stat().st_ino
    def failing(fd):
        if os.fstat(fd).st_ino == inode: raise OSError('explicit final directory fsync fault')
        return original(fd)
    monkeypatch.setattr(module.os, 'fsync', failing)
    with pytest.raises(Conflict): builder.build()
    assert not builder._issued and not list(control.iterdir())


@pytest.mark.parametrize('mutation', ['earlier_file', 'extra_file', 'root_rebind'])
def test_copy_changes_during_final_verify_reject(setup, monkeypatch, mutation):
    _, _, builder = setup; snapshot = builder.build()
    first = snapshot.path/'module/a.py'; inode = (snapshot.path/'module/b.txt').stat().st_ino
    original = module.os.read; changed = [False]
    def reading(fd, size):
        data = original(fd, size)
        if data and os.fstat(fd).st_ino == inode and not changed[0]:
            changed[0] = True
            if mutation == 'earlier_file': first.write_bytes(b'changed!!\n')
            elif mutation == 'extra_file': (snapshot.path/'extra').write_text('unexpected')
            else:
                snapshot.path.rename(snapshot.path.with_name(snapshot.id+'.old')); snapshot.path.mkdir(mode=0o700)
        return data
    monkeypatch.setattr(module.os, 'read', reading)
    with pytest.raises(Conflict): builder.verify(snapshot)
    assert changed[0]


def test_nested_directory_fsync_failure_is_not_a_successful_snapshot(setup, monkeypatch):
    _, control, builder = setup; original = module.os.fsync
    def failing(fd):
        path = Path(os.readlink('/proc/self/fd/'+str(fd)))
        if path.is_relative_to(control) and path.name == 'module':
            raise OSError('explicit copied-directory fsync fault')
        return original(fd)
    monkeypatch.setattr(module.os, 'fsync', failing)
    with pytest.raises(Conflict): builder.build()
    assert not builder._issued and not list(control.iterdir())


@pytest.mark.parametrize('change', ['snapshot', 'control', 'deadline'])
def test_final_fsync_cannot_hide_rebind_or_deadline(setup, monkeypatch, change):
    source, control, _ = setup; now = [0]
    builder = SnapshotBuilder(source, ['module/a.py'], control, clock=lambda: now[0])
    original = module.os.fsync; inode = control.stat().st_ino; changed = [False]
    def syncing(fd):
        result = original(fd)
        if os.fstat(fd).st_ino == inode and not changed[0]:
            changed[0] = True
            if change == 'snapshot':
                path = next(control.iterdir()); path.rename(control/'preserved-old-copy')
                path.mkdir(mode=0o700); (path/'unknown-sentinel').write_text('preserved')
            elif change == 'control':
                control.rename(control.with_name('preserved-old-control')); control.mkdir(mode=0o700)
                (control/'unknown-sentinel').write_text('preserved')
            else: now[0] = 31
        return result
    monkeypatch.setattr(module.os, 'fsync', syncing)
    with pytest.raises(Conflict): builder.build()
    assert changed[0] and not builder._issued
    if change == 'snapshot':
        assert (control/'preserved-old-copy/module/a.py').read_bytes() == b'print(42)\n'
        assert next(control.glob('snapshot_*/unknown-sentinel')).read_text() == 'preserved'
    elif change == 'control': assert (control/'unknown-sentinel').read_text() == 'preserved'
    else: assert not list(control.iterdir())

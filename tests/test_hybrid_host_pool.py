"""Actual shared fixture slots; no paid model/provider or runtime handoff."""
import copy
import json
import os
from pathlib import Path
import select
import signal
import sqlite3
import shutil
import subprocess
import sys

import pytest

from rlflow.hybrid_fixture_materials import FixtureMaterialBuilder
from rlflow.hybrid_installation_service import FixtureInstallationService
from rlflow.hybrid_host_pool import HostPoolOwner, PoolClaim, ClosedSlotWitness
from rlflow.store import Conflict
from rlflow import hybrid_host_pool as pool_module
from rlflow.hybrid_host_pool_ledger import links
from rlflow.store import canonical


@pytest.fixture
def pool(tmp_path):
    tmp_path.chmod(0o700)
    owner = HostPoolOwner.create_fixture(tmp_path)
    memberships = []
    for index in range(2):
        parent = owner.projects_root / ('project' + str(index)); parent.mkdir(mode=0o700)
        builder = FixtureMaterialBuilder(parent, project_id='pool_project_' + str(index))
        installation = FixtureInstallationService(builder); material = builder.prepare()
        installation.persist_intent(material); installation.publish(material)
        memberships.append(owner.register_project(installation, material, expected_version=index))
    try: yield owner, memberships
    finally:
        if owner._live: owner.shutdown()


def take(owner, membership, key):
    return owner.claim(membership, expected_version=owner.snapshot()['version'], request_key=key)


def test_two_projects_share_three_actual_slots_and_fourth_is_denied(pool):
    owner, members = pool
    claims = [take(owner, members[i % 2], 'claim_' + str(i)) for i in range(3)]
    assert {owner.check(c)['slot'] for c in claims} == {0, 1, 2}
    before = owner.snapshot()
    with pytest.raises(Conflict, match='exhausted'): take(owner, members[1], 'fourth')
    assert owner.snapshot() == before and before['occupied'] == 3
    with pytest.raises(PermissionError): owner.start(claims[0])


def test_original_unknown_close_witness_and_reused_slot_idempotency(pool):
    owner, members = pool
    claim = take(owner, members[0], 'one')
    owner.mark_unknown(claim, expected_version=3)
    assert owner.snapshot()['occupied'] == 1 and owner.check(claim)['state'] == 'UNKNOWN'
    closing = owner.request_close_no_handoff(claim, expected_version=4)
    with pytest.raises(Conflict): owner.check(claim)
    with pytest.raises(PermissionError): owner.complete_close(copy.copy(closing), expected_version=5)
    witness = owner.close_original(closing)
    assert owner.close_original(closing) is witness and owner.snapshot()['occupied'] == 1
    assert owner.complete_close(witness, expected_version=5) == {'version': 6, 'duplicate': False, 'execution_enabled': False}
    newer = take(owner, members[1], 'newer')
    assert owner.check(newer)['slot'] == 0
    assert owner.complete_close(witness, expected_version=5)['duplicate'] is True
    assert owner.check(newer)['state'] == 'CLAIM' and owner.snapshot()['occupied'] == 1


@pytest.mark.parametrize('kind', ['member', 'claim', 'witness'])
def test_copied_or_json_capabilities_never_adopt_authority(pool, kind):
    owner, members = pool
    claim = take(owner, members[0], 'copy')
    if kind == 'member':
        for bad in (copy.copy(members[0]), json.loads(members[0].raw)):
            with pytest.raises(PermissionError): owner.claim(bad, expected_version=True, request_key=None)
    elif kind == 'claim':
        for bad in (copy.copy(claim), json.loads(claim.raw), PoolClaim(claim.id, claim.raw)):
            with pytest.raises(PermissionError): owner.check(bad)
    else:
        closing = owner.request_close_no_handoff(claim, expected_version=3); witness = owner.close_original(closing)
        for bad in (copy.copy(witness), json.loads(witness.raw), ClosedSlotWitness(closing, witness.raw)):
            with pytest.raises(PermissionError): owner.complete_close(bad, expected_version=True)


@pytest.mark.parametrize('phase', ['before', 'after'])
def test_true_commit_lost_return_keeps_original_attempt_and_fd(pool, monkeypatch, phase):
    owner, members = pool; original_connect = sqlite3.connect; injected = []
    class Fault(sqlite3.Connection):
        def commit(self):
            if not injected:
                injected.append(phase)
                if phase == 'after': super().commit()
                raise OSError('actual pool commit lost return ' + phase)
            return super().commit()
    def connect(path, *args, **kwargs):
        if str(path).startswith((owner.root / 'pool.db').as_uri()): kwargs['factory'] = Fault
        return original_connect(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, 'connect', connect)
        with pytest.raises(OSError, match='lost return'):
            owner.claim(members[0], expected_version=2, request_key='original')
    original = next(c for c in owner._claims.values())
    owner._claim_slots[id(original)].check()
    claim = owner.claim(members[0], expected_version=2, request_key='original')
    assert claim is original and owner.snapshot()['version'] == 3 and owner.snapshot()['occupied'] == 1
    assert owner.claim(members[0], expected_version=2, request_key='original') is original


def test_restart_joins_original_project_but_cannot_adopt_occupied_claim(pool):
    owner, members = pool; old = take(owner, members[0], 'old')
    owner.mark_unknown(old, expected_version=3)
    root, digest, inode = owner.application_root, owner.descriptor_sha256, owner.descriptor_identity
    owner.shutdown()
    restarted = HostPoolOwner.trusted_attach(root, digest, inode)
    try:
        member = restarted.join_registered('pool_project_0')
        assert restarted.snapshot()['occupied'] == 1
        with pytest.raises(PermissionError): restarted.check(old)
        take(restarted, member, 'second'); take(restarted, member, 'third')
        with pytest.raises(Conflict, match='exhausted'): take(restarted, member, 'fourth')
    finally: restarted.shutdown()


def test_changed_namespace_or_database_denies_without_recreation(pool):
    owner, members = pool
    database = owner.root / 'pool.db'; moved = owner.root / 'original.db'
    database.rename(moved)
    with pytest.raises((Conflict, OSError)): take(owner, members[0], 'cannot_recreate')
    assert not database.exists()


def test_project_outside_fixed_application_cannot_select_pool(tmp_path):
    tmp_path.chmod(0o700); owner = HostPoolOwner.create_fixture(tmp_path)
    try:
        outside = tmp_path / 'outside'; outside.mkdir(mode=0o700)
        builder = FixtureMaterialBuilder(outside, project_id='outside')
        installation = FixtureInstallationService(builder); material = builder.prepare()
        installation.persist_intent(material); installation.publish(material)
        with pytest.raises(Conflict, match='another application'):
            owner.register_project(installation, material, expected_version=0)
        assert owner.snapshot()['version'] == 0
    finally: owner.shutdown()


def child(owner):
    root = Path(__file__).resolve().parents[1]
    reference = [str(owner.application_root), owner.descriptor_sha256, owner.descriptor_identity]
    source = ('import sys,json,select;sys.path.insert(0,' + repr(str(root)) + ');'
        'from rlflow.hybrid_host_pool import HostPoolOwner;'
        'o=HostPoolOwner.trusted_attach(*json.loads(' + repr(json.dumps(reference)) + '));'
        'm=o.join_registered("pool_project_1");'
        'c=o.claim(m,expected_version=o.snapshot()["version"],request_key="child");'
        'print(json.dumps(o.snapshot()),flush=True);'
        'r,_,_=select.select([sys.stdin],[],[],8);'
        '\nif r and sys.stdin.readline().strip()=="close":'
        '\n closing=o.request_close_no_handoff(c,expected_version=o.snapshot()["version"]);'
        '\n w=o.close_original(closing);o.complete_close(w,expected_version=o.snapshot()["version"]);'
        '\n print(json.dumps(o.snapshot()),flush=True)'
        '\no.shutdown()')
    return subprocess.Popen([sys.executable, '-B', '-I', '-c', source], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)


def read_child(process):
    ready, _, _ = select.select([process.stdout], [], [], 8)
    assert ready, 'finite fixture child readiness timed out'
    raw = process.stdout.readline()
    assert raw, process.stderr.read()
    return json.loads(raw)


def test_actual_two_processes_share_three_slots_and_original_child_can_close(pool):
    owner, members = pool
    take(owner, members[0], 'parent1'); take(owner, members[0], 'parent2')
    process = child(owner)
    try:
        assert read_child(process)['occupied'] == 3
        with pytest.raises(Conflict, match='exhausted'): take(owner, members[1], 'fourth')
        process.stdin.write('close\n'); process.stdin.flush()
        assert read_child(process)['occupied'] == 2
        process.wait(timeout=4); assert process.returncode == 0, process.stderr.read()
        take(owner, members[1], 'after_child_closed')
        assert owner.snapshot()['occupied'] == 3
    finally:
        if process.poll() is None: process.kill(); process.wait(timeout=4)


def test_actual_dead_child_idle_kernel_lock_does_not_refund_durable_slot(pool):
    owner, members = pool
    take(owner, members[0], 'parent')
    process = child(owner)
    try:
        assert read_child(process)['occupied'] == 2
        os.kill(process.pid, signal.SIGKILL); process.wait(timeout=4)
        take(owner, members[1], 'third')
        assert owner.snapshot()['occupied'] == 3
        with pytest.raises(Conflict, match='exhausted'): take(owner, members[1], 'fourth')
    finally:
        if process.poll() is None: process.kill(); process.wait(timeout=4)


def damage(owner, sql, parameters=()):
    # Explicit test-only corruption, restoring the immutable trigger definition.
    with sqlite3.connect(owner.root / 'pool.db') as db:
        db.execute('DROP TRIGGER immutable_update')
        db.execute(sql, parameters)
        db.execute(next(ddl for ddl in pool_module._DDL if ddl.startswith('CREATE TRIGGER immutable_update')))


def test_raw_slot_index_cannot_hide_nonlatest_occupied_fact(pool):
    owner, members = pool
    claim = take(owner, members[0], 'hidden')
    take(owner, members[1], 'latest')
    damage(owner, "UPDATE ledger SET slot=NULL,action='REGISTER' WHERE key=?", (json.loads(claim.raw)['key'],))
    with sqlite3.connect(owner.root / 'pool.db') as db: db.execute("UPDATE heads SET raw='null' WHERE slot=0")
    with pytest.raises(Conflict): owner.snapshot()
    with pytest.raises(Conflict): take(owner, members[1], 'not_free')


def test_index_ddl_is_pinned_before_hot_lookup(pool):
    owner, _ = pool
    with sqlite3.connect(owner.root / 'pool.db') as db:
        db.execute('DROP INDEX slot_tip'); db.execute('CREATE INDEX slot_tip ON ledger(slot,seq DESC)')
    with pytest.raises(Conflict, match='schema/index'): owner.snapshot()


@pytest.mark.parametrize('target', ['head', 'member', 'key', 'action', 'hash', 'slot'])
def test_oversize_sql_cells_fail_closed_before_projection_adoption(pool, target):
    owner, members = pool; claim = take(owner, members[0], 'bounded')
    oversized = 'x' * (2 * 1024**2)
    if target == 'head':
        with sqlite3.connect(owner.root / 'pool.db') as db: db.execute('UPDATE heads SET raw=? WHERE slot=0', (oversized,))
    elif target == 'member':
        with sqlite3.connect(owner.root / 'pool.db') as db: db.execute('UPDATE members SET store_root=? WHERE id=?', (oversized, members[0].id))
    else:
        damage(owner, 'UPDATE ledger SET ' + target + '=? WHERE key=?', (oversized, json.loads(claim.raw)['key']))
    with pytest.raises(Conflict):
        if target == 'member': owner.join_registered('pool_project_0')
        else: owner.snapshot()


def test_head_numeric_equivalence_is_not_byte_identity(pool):
    owner, members = pool; take(owner, members[0], 'head')
    value = owner.snapshot()['heads'][0]; value['version'] = float(value['version'])
    with sqlite3.connect(owner.root / 'pool.db') as db:
        db.execute('UPDATE heads SET raw=? WHERE slot=0', (canonical(value).decode(),))
    with pytest.raises(Conflict, match='derived indexed head'): owner.snapshot()


def test_nonnull_prior_free_requires_original_fact(pool):
    owner, members = pool; claim = take(owner, members[0], 'prior')
    value = json.loads(claim.raw); value['payload']['prior_key'] = 'missing_free'
    registration = json.loads(members[0].raw)
    with pytest.raises(Conflict, match='prior FREE'):
        links(value, lambda _: None, lambda _: registration)


def test_actual_connection_swap_restore_is_denied_before_sql_writes(pool, monkeypatch):
    owner, _ = pool; connect = sqlite3.connect
    database = owner.root / 'pool.db'; copied = owner.root / 'copied.db'; saved = owner.root / 'saved.db'
    shutil.copyfile(database, copied); copied.chmod(0o600)
    def swapped(path, *args, **kwargs):
        if not str(path).startswith(database.as_uri()): return connect(path, *args, **kwargs)
        database.rename(saved); copied.rename(database)
        try: connection = connect(path, *args, **kwargs)
        finally: database.rename(copied); saved.rename(database)
        return connection
    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, 'connect', swapped)
        with pytest.raises(Conflict, match='native pool SQLite'): owner.snapshot()
    assert owner.snapshot()['version'] == 2
    with connect(copied) as db: assert db.execute('SELECT version FROM meta').fetchone()[0] == 2


def test_last_physical_io_expiry_prevents_real_claim_commit(pool, monkeypatch):
    owner, members = pool; original = owner._physical; calls = []
    def physical():
        original(); calls.append(1)
        if len(calls) == 3:
            value = json.loads(next(iter(owner._claims.values())).raw)['payload']
            patch.setattr(pool_module.time, 'time', lambda: value['deadline_wall'])
            patch.setattr(pool_module.time, 'monotonic', lambda: value['deadline_mono'])
    with monkeypatch.context() as patch:
        patch.setattr(owner, '_physical', physical)
        with pytest.raises(Conflict, match='expired/regressed'):
            owner.claim(members[0], expected_version=2, request_key='expiry', seconds=1)
    assert owner.snapshot()['version'] == 2
    retained = next(iter(owner._claims.values())); owner._claim_slots[id(retained)].check()


@pytest.mark.parametrize('action', ['UNKNOWN', 'CLOSE_INTENT'])
def test_last_physical_io_lost_slot_lock_rolls_back_transition(pool, monkeypatch, action):
    owner, members = pool; claim = take(owner, members[0], 'transition')
    slot = owner._claim_slots[id(claim)]; original = owner._physical; calls = []
    def physical():
        original(); calls.append(1)
        if len(calls) == 3: pool_module.fcntl.flock(slot.fds[0], pool_module.fcntl.LOCK_UN)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(owner, '_physical', physical)
            with pytest.raises((Conflict, PermissionError)):
                if action == 'UNKNOWN': owner.mark_unknown(claim, expected_version=3)
                else: owner.request_close_no_handoff(claim, expected_version=3)
        assert owner.snapshot()['version'] == 3 and not owner._closings
    finally: pool_module.fcntl.flock(slot.fds[0], pool_module.fcntl.LOCK_EX | pool_module.fcntl.LOCK_NB)


def test_explicit_and_startup_full_audit_find_old_nonlatest_corruption(pool):
    owner, members = pool; claim = take(owner, members[0], 'old')
    unknown = owner.mark_unknown(claim, expected_version=3)
    closing = owner.request_close_no_handoff(claim, expected_version=4)
    owner.complete_close(owner.close_original(closing), expected_version=5)
    take(owner, members[1], 'new')
    damage(owner, 'UPDATE ledger SET hash=? WHERE key=?', ('0' * 64, unknown['key']))
    with pytest.raises(Conflict, match='indexed pool event'): owner.audit()
    with pytest.raises(Conflict, match='indexed pool event'):
        HostPoolOwner.trusted_attach(owner.application_root, owner.descriptor_sha256, owner.descriptor_identity)


def test_actual_fork_child_closes_original_fds_without_unlocking_parent(pool):
    owner, members = pool; claim = take(owner, members[0], 'fork')
    descriptors = tuple(owner._pins.values()) + tuple(owner._claim_slots[id(claim)].fds)
    read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            closed = []
            for fd in descriptors:
                try: os.fstat(fd)
                except OSError: closed.append(fd)
            try: owner.check(claim)
            except PermissionError: denied = True
            else: denied = False
            os.write(write_fd, json.dumps([closed == list(descriptors), denied]).encode())
        finally: os._exit(0)
    os.close(write_fd)
    try:
        assert select.select([read_fd], [], [], 4)[0]
        assert json.loads(os.read(read_fd, 1024)) == [True, True]
        assert os.waitpid(pid, 0)[1] == 0
        owner._claim_slots[id(claim)].check()
        assert owner.check(claim)['state'] == 'CLAIM'
    finally:
        os.close(read_fd)
        try: os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)
        except ProcessLookupError: pass


def test_partial_close_retains_original_fd_and_retry_requires_all_closed(pool, monkeypatch):
    owner, members = pool; claim = take(owner, members[0], 'partial')
    closing = owner.request_close_no_handoff(claim, expected_version=3)
    slot = owner._claim_slots[id(claim)]; original = os.close; fail_fd = slot.fds[1]
    def close(fd):
        if fd == fail_fd: raise OSError('actual retained partial close')
        return original(fd)
    with monkeypatch.context() as patch:
        patch.setattr(os, 'close', close)
        with pytest.raises(Conflict, match='cleanup uncertain'): owner.close_original(closing)
    assert slot.fds[0] is None and slot.fds[1] == fail_fd and not slot.closed
    assert id(closing) not in owner._witnesses and owner.snapshot()['occupied'] == 1
    witness = owner.close_original(closing)
    assert slot.closed and slot.fds == [None, None]
    owner.complete_close(witness, expected_version=4)
    assert owner.snapshot()['occupied'] == 0


def test_actual_fork_inside_transaction_child_unwind_performs_zero_sql(pool, monkeypatch):
    owner, _ = pool; connect = sqlite3.connect; original_pid = os.getpid(); child_calls = []
    class Trace(sqlite3.Connection):
        def execute(self, *args, **kwargs):
            if os.getpid() != original_pid:
                child_calls.append(1); raise AssertionError('child touched inherited SQLite')
            return super().execute(*args, **kwargs)
    def connection(path, *args, **kwargs):
        if str(path).startswith((owner.root / 'pool.db').as_uri()): kwargs['factory'] = Trace
        return connect(path, *args, **kwargs)
    read_fd, write_fd = os.pipe2(os.O_CLOEXEC); pid = None; denied = False
    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, 'connect', connection)
        try:
            with owner._transaction() as db:
                db.execute('UPDATE meta SET version=version')  # Actual rollback journal open.
                native_fd = owner._sql_active[id(db)][1]
                pid = os.fork()
        except PermissionError:
            denied = True
        if pid == 0:
            try:
                try: os.fstat(native_fd)
                except OSError: closed = True
                else: closed = False
                os.close(read_fd)
                os.write(write_fd, json.dumps([denied, not child_calls, closed]).encode())
            finally: os._exit(0)
    os.close(write_fd)
    try:
        assert select.select([read_fd], [], [], 4)[0]
        assert json.loads(os.read(read_fd, 1024)) == [True, True, True]
        assert os.waitpid(pid, 0)[1] == 0
        assert owner.snapshot()['version'] == 2
    finally:
        os.close(read_fd)
        try: os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)
        except ProcessLookupError: pass


def test_oversize_project_source_projection_key_is_sql_bounded(pool):
    owner, members = pool
    root = Path(json.loads(members[0].raw)['payload']['store_root'])
    with sqlite3.connect(root / 'runtime/research.db') as db:
        db.execute('UPDATE projection SET object_key=? WHERE section=? AND object_key!=?',
                   ('x' * (2 * 1024**2), pool_module.SECTIONS[0], ''))
    with pytest.raises(Conflict, match='installation collections'):
        owner.join_registered('pool_project_0')

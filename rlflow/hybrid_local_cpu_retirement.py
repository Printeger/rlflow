"""Protected Pool-only physical retirement; no Project mutation or old STOP."""
from .hybrid_goals import digest
import json
import os
from pathlib import Path

from .hybrid_host_pool_ledger import RETIRE, count, identifier, links
from .hybrid_local_cpu_reads import LocalCpuTaskReader
from .hybrid_local_cpu_recovery import recover, REPORT, SCOPE_RUNTIME, validate_scope, _close_kernel_source, _pairs
from .hybrid_protocol import validate_schema
from .hybrid_runtime_boundary import _held_chain, _stamp
from .hybrid_reads import ReadBudget
from .hybrid_preparation_sources import historical_sources
from .hybrid_authority import SECTIONS as AUTHORITY
from .store import Store, Conflict, sha


def _actual_pool(pool):
    from .hybrid_host_pool import HostPoolOwner, _owners
    # Pure atomic identity read. Never take registry_lock while a Pool
    # transaction holds its owner lock: before-fork uses the reverse order.
    if type(pool) is not HostPoolOwner or _owners.get(id(pool)) is not pool:
        raise PermissionError('actual registered physical retirement Pool owner required')
    pool._actual()


def _capture_report(source):
    with _held_chain(Path(source['path'])) as (fds, chain):
        if chain != source['chain']: raise Conflict('original retirement publication rebound')
        fd=os.open('task-report',os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fds[-1])
        original=None
        try:
            info=os.fstat(fd);original=(info.st_dev,info.st_ino)
            if [info.st_dev,info.st_ino,info.st_uid]!=source['files']['task-report']:
                raise Conflict('original retirement report rebound')
            before=_stamp(info);raw=os.read(fd,32769)
            if len(raw)>32768 or len(raw)!=info.st_size or not raw.endswith(b'\n'):
                raise Conflict('bounded original retirement report required')
            if (_stamp(os.fstat(fd))!=before or
                    _stamp(os.stat('task-report',dir_fd=fds[-1],follow_symlinks=False))!=before):
                raise Conflict('original retirement report changed during capture')
            return json.loads(raw,object_pairs_hook=_pairs)
        finally:_close_kernel_source(fd,original,'retirement-report')


def _reader(pool, registration):
    member = registration['payload']
    pool._verify_member_sources(member)
    store = Store.attach_existing(member['store_root'], project_id=member['project_id'], data_mode='fixture')
    return LocalCpuTaskReader(store, project_id=member['project_id'], store_epoch=member['store_epoch'])


def _proof(pool, claim, registration, reader, db, meta, read, fact, reservation_id, archived=None):
    request = fact['request']; runtime = request.get('fixture_runtime'); member = registration['payload']
    origin = runtime['origin'] if runtime else {}
    if (request.get('reservation_id') != reservation_id or
            fact['prior_reservation'] is None or
            origin.get('pool_claim') != {'key': claim['key'], 'hash': digest(claim)} or
            origin.get('pool_id') != pool.binding['pool_id'] or
            origin.get('member_id') != member['member_id'] or
            origin.get('owner') != claim['payload']['owner']):
        raise Conflict('original physical retirement claim/project lineage differs')
    # UNKNOWN is retained in the original Project fact. We do not reconstruct
    # the missing final usage, manager job, owner or stopped Runtime grant.
    from .hybrid_budget_ledger import derived_heads, SECTIONS
    reservation = derived_heads(fact)[SECTIONS[2]].get(reservation_id)
    if reservation is None or reservation['status'] != 'UNKNOWN':
        raise Conflict('physical retirement requires original UNKNOWN reservation')
    original = historical_sources(reader.store, db, fact['policy_source'], read)
    approval = original[AUTHORITY[0]][fact['policy_source']['approval_key']]
    definition = approval['registry_witness']['tools']['local_cpu']['definition']
    source = runtime.get('local_cpu_recovery_source')
    if source is None: raise Conflict('original physical retirement publication missing')
    libcrypto = definition['modules'].get('libcrypto')
    if archived is None:
        evidence = recover(source, runtime, definition['spec'], libcrypto)
        if evidence is None or evidence['physical_scope_status'] != 'ORIGINAL_CONTROLLED_SCOPE_CLOSED':
            raise Conflict('original controlled producers not proven physically closed')
        report = _capture_report(source)
        proof = evidence['physical_scope_proof']
    else:
        report = archived
        proof = {'original_binding':runtime['local_cpu_scope_binding'],'keeper':report['task_closed']['keeper'],
            'signed_task_closed':report['task_closed'],'original_processes_terminal':True,
            'original_manager_job_recovered':False,'current_unit_state':'NOT_OBSERVED',
            'scope_observation':'HISTORICAL_ORIGINAL_INVOCATION'}
    validate_schema(REPORT,report)
    binding = runtime.get('local_cpu_scope_binding')
    validate_schema(SCOPE_RUNTIME,binding);validate_scope(binding['scope'],source['unit'])
    from .hybrid_local_runner_signature import verify
    if not verify(runtime['local_cpu_recovery_public_key'],{k:v for k,v in report.items() if k!='signature'},
                  report['signature'],libcrypto):
        raise Conflict('original retirement archived signature differs')
    closed = report['task_closed']
    if (report['format']!='local_cpu_recovery/2' or report['closed_scope']!=binding['scope'] or
            closed!=proof['signed_task_closed'] or closed['keeper']!=binding['keeper'] or
            binding['owner']!=origin['owner'] or
            any(closed['keeper'][k]!=runtime['producer'][k] for k in ('pid','starttime','boot_id')) or
            closed['config_sha256']!=source['config_sha256'] or
            closed['task']['source_sha256']!=origin['local_cpu']['code_sha256'].removeprefix('sha256:')):
        raise Conflict('original retirement archived scope/config differs')
    return runtime, digest(proof), report


def verify_retirement(pool, db, value):
    """Audit original immutable Project fact + signed report, not current head."""
    _actual_pool(pool)
    payload = value['payload']; claim = pool._point(db, payload['claim_key'])
    registration = pool._member_point(db, claim['payload']['member_id'])
    reader = _reader(pool, registration)
    with reader.snapshot() as (project_db, meta):
        read = ReadBudget(project_db, 16*1024**2)
        fact = reader._point(project_db, read, payload['project_fact_key'], meta['as_of_state_version'])
        runtime, proof_hash, _ = _proof(pool, claim, registration, reader, project_db, meta, read,
                                     fact, payload['reservation_id'],payload['signed_report'])
        if (digest(fact) != payload['project_fact_hash'] or
                runtime['origin']['lease_id'] != payload['runtime_lease_id'] or
                proof_hash != payload['physical_proof_hash'] or
                payload['recovery_owner']['boot_id']!=runtime['producer']['boot_id'] or
                payload['recovery_owner']['pid']==runtime['origin']['owner']['pid'] and
                    payload['recovery_owner']['starttime']==runtime['origin']['owner']['starttime']):
            raise Conflict('original physical retirement source changed')


def retire(pool, membership, claim_key, reservation_id, expected_version):
    _actual_pool(pool)
    pool._issued_member(membership)  # Actual protected process membership first.
    identifier(claim_key); identifier(reservation_id); count(expected_version)
    key = 'physical_retire_' + sha(claim_key)
    slot = None
    with pool._lock:
        try:
            with pool._transaction(final=lambda db: verify_retirement(pool, db, value)) as db:
                registration = pool._member_current(db, membership)
                claim = pool._point(db, claim_key)
                if claim is None or claim['action'] != 'CLAIM' or claim['payload']['member_id'] != membership.id:
                    raise Conflict('original registered physical retirement claim missing')
                value = pool._point(db, key)
                if value is not None:
                    if (value['action'] != RETIRE or value['payload']['reservation_id'] != reservation_id or
                            value['version'] != expected_version + 1):
                        raise Conflict('original physical retirement request differs')
                    # Replay after slot reuse cannot touch the new slot/claim.
                    verify_retirement(pool, db, value)
                    return value
                version, heads = pool._state(db); current = heads[claim['slot']]
                if version != expected_version or current is None or current['claim_key'] != claim_key:
                    raise Conflict('stale physical retirement Pool CAS')
                reader = _reader(pool, registration)
                with reader.snapshot() as (project_db, meta):
                    read = ReadBudget(project_db, 16*1024**2)
                    pair = reader._head(project_db, read, reservation_id, meta['as_of_state_version'])
                    if pair is None: raise Conflict('original configured task missing')
                    _, fact = pair
                    runtime, proof_hash, report = _proof(pool, claim, registration, reader, project_db, meta,
                                                read, fact, reservation_id)
                    value = {'pool_id': pool.binding['pool_id'], 'action': RETIRE, 'key': key,
                        'version': version + 1, 'slot': claim['slot'], 'payload': {
                            'claim_key': claim_key, 'claim_hash': digest(claim), 'prior_key': current['key'],
                            'runtime_lease_id': runtime['origin']['lease_id'], 'reservation_id': reservation_id,
                            'project_fact_key': reader._key(fact), 'project_fact_hash': digest(fact),
                            'physical_proof_hash': proof_hash,'signed_report':report,'recovery_owner':dict(pool.process)}}
                links(value, lambda k: pool._point(db, k), lambda k: pool._member_point(db, k), current=current)
                retained = pool._slots.get(claim['slot'])
                if retained is not None and not retained.closed:
                    raise Conflict('original local slot descriptors still retained')
                # Closed original producers alone do not prove the hardware
                # slot lock free. Acquire the actual original exclusive lock.
                from .hybrid_host_pool import _Slot
                slot = _Slot(pool, claim['slot']); slot.check(); slot.close()
                pool._append(db, value)
            return value
        finally:
            # _Slot is strongly retained by pool._slots before acquisition.
            # A failed close is not retried or hidden by an implicit finally.
            pass

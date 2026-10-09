"""Pure historical fact prototypes, NOT a Store write or installation grant."""
from copy import deepcopy
import hashlib

import pytest

from rlflow.hybrid_runtime_boundary import directory_chain, policy_source
from rlflow import hybrid_runtime_installation as domain
from rlflow.hybrid_goals import digest
from rlflow.store import canonical, sha, Conflict


@pytest.fixture
def facts(tmp_path):
    root = tmp_path / 'new-store'; root.mkdir(mode=0o700)
    working = tmp_path / 'working'; working.mkdir(mode=0o700)
    private = tmp_path / 'bootstrap'; private.mkdir(mode=0o700)
    db = root / 'research.db'; db.touch()
    catalog_path = private / 'catalog.json'; catalog_path.touch(mode=0o600)
    request = {'action': 'prepare_fixture_runtime_installation', 'project_id': 'p', 'data_mode': 'fixture',
               'store_epoch': 'store_original', 'installation_id': 'install_original',
               'idempotency_key': 'first', 'expected_state_version': 0}
    key = domain.intent_key(request)
    catalog = {'version': 1, 'mode': 'HYBRID_LEGACY_DENIED', 'execution_enabled': False,
               'release_enabled': False, 'installation_ref': {'intent_key': key, 'accepted_state_version': 1},
               'scopes': [{'reserved_path': str(path), 'directory_chain': directory_chain(path)}
                          for path in (root, working)]}
    descriptor = {'version': 1, 'mode': 'BOUND_HYBRID_NONEXECUTING', 'catalog_path': str(catalog_path),
                  'catalog_sha256': sha(catalog), 'catalog_parent_chain': directory_chain(private),
                  'catalog_identity': [catalog_path.stat().st_dev, catalog_path.stat().st_ino]}
    manifest = {'rlflow/hybrid_runtime_boundary.py': 'a' * 64,
                'rlflow/runtime_boundary_policy.py': hashlib.sha256(policy_source(descriptor)).hexdigest()}
    intent = {'request': request, 'request_hash': digest(request), 'accepted_state_version': 1,
              'binding': {'store_root': str(root), 'store_root_chain': directory_chain(root),
                          'working_namespace': str(working), 'working_namespace_chain': directory_chain(working),
                          'database_identity': [db.stat().st_dev, db.stat().st_ino],
                          'release_path': str(private / 'fixed-release'),
                          'release_parent_chain': directory_chain(private),
                          'bootstrap_template_hash': sha({'rlflow/hybrid_runtime_boundary.py': 'a' * 64})},
              'expected_seal': {'descriptor': descriptor, 'catalog': catalog,
                                'release_manifest': manifest, 'release_id': sha(manifest)},
              'state': 'LEGACY_DENIED_UNPUBLISHED', 'execution_enabled': False, 'release_enabled': False}
    ready_request = {**request, 'action': 'publish_fixture_runtime_installation', 'expected_state_version': 1,
                     'intent_key': key, 'intent_hash': digest(intent), 'idempotency_key': 'ready'}
    ready = {'request': ready_request, 'request_hash': digest(ready_request), 'accepted_state_version': 2,
             'catalog_sha256': descriptor['catalog_sha256'], 'release_id': sha(manifest),
             'state': 'LEGACY_DENIED_READY_NONEXECUTING', 'execution_enabled': False, 'release_enabled': False}
    return key, intent, domain.publication_key(ready_request), ready


def test_two_phase_dag_has_no_reverse_intent_digest_in_catalog(facts):
    key, intent, ready_key, ready = facts
    domain.validate_record(domain.SECTIONS[0], key, intent)
    domain.validate_record(domain.SECTIONS[1], ready_key, ready)
    assert sha(intent) not in canonical(intent['expected_seal']['catalog']).decode()
    state = {'version': 2, domain.SECTIONS[0]: {key: intent}, domain.SECTIONS[1]: {ready_key: ready}}
    def original(k):
        section, value, event = ((domain.SECTIONS[0], intent, domain.EVENTS[0]) if k == key else
                                 (domain.SECTIONS[1], ready, domain.EVENTS[1]))
        return ((event, 'hybrid-installer', 'install_original', value['accepted_state_version']),
                domain.expected_objects(section, k, value), domain.event_inputs(value))
    domain.validate_complete(state, ('p', 'fixture'), original, event_summary=((ready_key, 2), 2))


@pytest.mark.parametrize('change', ['ref', 'catalog_hash', 'release_hash', 'missing_policy',
                                   'scope_omission', 'scope_chain', 'bool_inode', 'nonfresh', 'escape_path',
                                   'descriptor_without_policy', 'policy_without_descriptor', 'template_hash'])
def test_intent_bad_seal_scope_or_nonfresh_contract_denies(facts, change):
    key, original, _, _ = facts; value = deepcopy(original); seal = value['expected_seal']
    if change == 'ref': seal['catalog']['installation_ref']['intent_key'] = 'other_intent'
    elif change == 'catalog_hash': seal['descriptor']['catalog_sha256'] = 'd' * 64
    elif change == 'release_hash': seal['release_id'] = 'd' * 64
    elif change == 'missing_policy':
        del seal['release_manifest']['rlflow/runtime_boundary_policy.py']
        seal['release_id'] = sha(seal['release_manifest'])
    elif change == 'scope_omission': seal['catalog']['scopes'].pop()
    elif change == 'scope_chain': seal['catalog']['scopes'][0]['directory_chain'][-1][1] += 1
    elif change == 'bool_inode': seal['descriptor']['catalog_identity'][0] = True
    elif change == 'nonfresh':
        value['request']['expected_state_version'] = 1; value['accepted_state_version'] = 2
    elif change == 'descriptor_without_policy': seal['descriptor']['catalog_identity'][1] += 1
    elif change == 'policy_without_descriptor':
        seal['release_manifest']['rlflow/runtime_boundary_policy.py'] = 'd' * 64
        seal['release_id'] = sha(seal['release_manifest'])
    elif change == 'template_hash': value['binding']['bootstrap_template_hash'] = 'd' * 64
    else: seal['release_manifest']['../escape'] = 'd' * 64; seal['release_id'] = sha(seal['release_manifest'])
    if change in ('ref', 'scope_omission', 'scope_chain'):
        seal['descriptor']['catalog_sha256'] = sha(seal['catalog'])
    value['request_hash'] = digest(value['request'])
    with pytest.raises((Conflict, ValueError)):
        domain.validate_record(domain.SECTIONS[0], key, value)


@pytest.mark.parametrize('change', ['missing', 'hash', 'epoch', 'cas', 'seal'])
def test_ready_requires_exact_original_intent_and_seal(facts, change):
    key, intent, ready_key, original = facts; ready = deepcopy(original)
    if change == 'hash': ready['request']['intent_hash'] = 'sha256:' + 'd' * 64
    elif change == 'epoch': ready['request']['store_epoch'] = 'store_other'
    elif change == 'cas': ready['request']['expected_state_version'] = 2; ready['accepted_state_version'] = 3
    elif change == 'seal': ready['release_id'] = 'd' * 64
    ready['request_hash'] = digest(ready['request'])
    lookup = lambda section, k: intent if change != 'missing' and (section, k) == (domain.SECTIONS[0], key) else None
    domain.validate_record(domain.SECTIONS[1], ready_key, ready)
    with pytest.raises(Conflict): domain.validate_links(ready, lookup)


@pytest.mark.parametrize('damage', ['omitted_phase', 'wrong_metadata', 'wrong_inputs', 'missing_original', 'count'])
def test_full_history_original_metadata_and_tip_count_cannot_be_omitted(facts, damage):
    key, intent, ready_key, ready = facts
    state = {'version': 2, domain.SECTIONS[0]: {key: intent}, domain.SECTIONS[1]: {ready_key: ready}}
    def original(k):
        if damage == 'missing_original': return None
        section, value, event = ((domain.SECTIONS[0], intent, domain.EVENTS[0]) if k == key else
                                 (domain.SECTIONS[1], ready, domain.EVENTS[1]))
        return ((event, 'wrong' if damage == 'wrong_metadata' else 'hybrid-installer',
                 'install_original', value['accepted_state_version']), domain.expected_objects(section, k, value),
                {'wrong': True} if damage == 'wrong_inputs' else domain.event_inputs(value))
    if damage == 'omitted_phase': state[domain.SECTIONS[1]] = {}
    with pytest.raises(Conflict):
        domain.validate_complete(state, ('p', 'fixture'), original,
                                 event_summary=((ready_key, 2), 1 if damage == 'count' else 2))

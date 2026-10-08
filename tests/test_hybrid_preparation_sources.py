from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient

from rlflow.hybrid_authority import SECTIONS as AUTHORITY, timestamp
from rlflow.hybrid_goals import head_key, digest, SECTIONS as GOALS
from rlflow.hybrid_preparation_sources import load_sources
from rlflow.hybrid_registry import Registry
from rlflow.observation import rotate_epoch
from rlflow.store import Conflict
from tests.test_hybrid_control_api import (setup, login, post, prepare, approve_payload, submit_payload,
                                         ORIGIN)


def sources(pair, p, now, registry=None):
    draft = pair.drafts
    with draft.store.read_connection() as db:
        db.execute('BEGIN')
        return load_sources(draft.store, db, registry or pair.approvals.registry,
            project_id=draft.project_id, data_mode=draft.data_mode, store_epoch=draft.store_epoch,
            goal_ref=head_key(draft.project_id, draft.data_mode, p['goal_id']), now=now)


def consent(client, pair, p):
    headers = login(client)
    assert post(client, submit_payload(p), headers, 'draft').status_code == 202
    view = prepare(client, p, headers)
    result = post(client, approve_payload(view), headers, 'approve')
    assert result.status_code == 202
    fact = pair.drafts.store.get(AUTHORITY[0], result.json()['result']['fact_key'])
    return headers, timestamp(fact['approved_at']), fact


def test_original_private_sources_are_complete_current_detached_and_nonexecuting(tmp_path):
    store, _, p, app, pair, _, _ = setup(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        _, now, fact = consent(client, pair, p); before = store.audit()
        value = sources(pair, p, now)
        assert value['source_version'] == 2 and value['draft_source_version'] == 1
        assert value['approval_source_version'] == 2 and value['approval_hash'] == digest(fact)
        assert value['record']['contract']['proposal'] == p and value['approval_fact'] == fact
        assert value['execution_enabled'] is False
        value['record']['contract']['proposal']['objective'] = 'mutated detached output'
        assert sources(pair, p, now)['record']['contract']['proposal'] == p
        assert store.audit() == before and not store.objects('sessions') and not store.objects('tasks')


@pytest.mark.parametrize('drift', ['expired', 'clock_regressed', 'revoked', 'contract', 'epoch', 'config', 'goal_ref', 'no_consent'])
def test_current_sources_reject_drift_without_side_effect(tmp_path, drift):
    store, _, p, app, pair, _, _ = setup(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        registry = pair.approvals.registry
        if drift == 'no_consent':
            headers = login(client); assert post(client, submit_payload(p), headers, 'draft').status_code == 202
            now = datetime.now(timezone.utc)
        else: headers, now, fact = consent(client, pair, p)
        if drift == 'expired': now = timestamp(fact['expires_at'])
        elif drift == 'clock_regressed': now -= timedelta(seconds=1)
        elif drift == 'revoked':
            pair.approvals.revoke(token=client.cookies.get('rlflow_session'), csrf=headers['X-CSRF-Token'],
                origin=ORIGIN, goal_id=p['goal_id'], approval_key=sources(pair,p,now)['approval_key'],
                expected_version=store.version(), expected_authority_revision=1, reason='explicit fixture revoke',
                idempotency_key='revoke')
        elif drift == 'contract':
            changed = deepcopy(p); changed['contract_version'] = 2; changed['objective'] += ' changed'
            assert post(client, submit_payload(changed, store.version()), headers, 'new-draft').status_code == 202
        elif drift == 'epoch': rotate_epoch(store)
        elif drift == 'config':
            config = json.loads(registry._raw); config['project_policy']['configuration']['changed'] = True
            registry = Registry(config)
        elif drift == 'goal_ref': p = {**p, 'goal_id': 'missing'}
        before = store.replay()
        with pytest.raises(Conflict): sources(pair, p, now, registry)
        assert store.replay() == before


def test_same_transaction_required_and_clock_fail_closed(tmp_path):
    store, _, p, _, pair, _, _ = setup(tmp_path)
    fixed = {'project_id':pair.drafts.project_id, 'data_mode':pair.drafts.data_mode,
        'store_epoch':pair.drafts.store_epoch,'goal_ref':head_key('project_fixture','fixture',p['goal_id'])}
    with store.read_connection() as db:
        with pytest.raises(Conflict, match='actual transaction'):
            load_sources(store,db,pair.approvals.registry,**fixed,now=datetime.now(timezone.utc))
        db.execute('BEGIN')
        with pytest.raises(Conflict, match='UTC'):
            load_sources(store,db,pair.approvals.registry,**fixed,now=datetime.now())

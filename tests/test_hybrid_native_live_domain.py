"""Fresh isolated LIVE registration/STOP only: zero model or credential IO."""
import json
from copy import deepcopy

import pytest

from rlflow.hybrid_fixture_runtime import FixtureRuntimeOwner
from rlflow.hybrid_host_pool_ledger import member as validate_member
from rlflow.hybrid_live_domain import PROFILE, PREPARE, PUBLISH
from rlflow.hybrid_protocol import ProtocolError
from rlflow.hybrid_runtime_installation import SECTIONS as INSTALLATION, intent_key, validate_record
from rlflow.hybrid_goals import digest
from rlflow.hybrid_usage_source import FixtureUsageSourceOwner
from rlflow.store import Conflict
from tests.test_hybrid_a_workflow_derivation import original, native_setup, FILES


@pytest.mark.parametrize('original',[{'data_mode':'live','project_id':'project_live'}],indirect=True)
def test_fresh_live_original_workflow_register_stop_and_replay_without_process(original,monkeypatch):
    owner,bundle,token,obs,claim=original
    monkeypatch.setattr('subprocess.Popen',lambda *a,**k:pytest.fail('LIVE registration cannot invoke models'))
    plans=owner.plans
    assert plans.workspace.data_mode==plans.installation.data_mode==plans.installation.builder.data_mode=='live'
    intent=plans.store.objects(INSTALLATION[0])[0][1]
    ready=plans.store.objects(INSTALLATION[1])[0][1]
    assert intent['request']['action']==PREPARE and ready['request']['action']==PUBLISH
    assert intent['request']['domain_profile']==ready['request']['domain_profile']==PROFILE
    sources=plans.observe_sources(token,obs)['sources']
    assert sources['data_mode']=='live' and sources['domain_profile']==sources['bootstrap']['domain_profile']==PROFILE
    member=owner.pool._issued_member(owner.membership)['payload']
    assert member['data_mode']=='live' and member['bootstrap']['domain_profile']==member['domain_profile']==PROFILE
    with pytest.raises(Conflict,match='process and scope'):
        FixtureRuntimeOwner(owner.pool,owner.membership,plans)
    plans.workspace.data_mode='fixture'
    try:
        with pytest.raises(Conflict,match='same-application'):
            FixtureRuntimeOwner(owner.pool,owner.membership,plans)
    finally:plans.workspace.data_mode='live'
    synthetic=FixtureUsageSourceOwner(owner.pool)
    try:
        with pytest.raises(PermissionError,match='cannot enter live'):
            synthetic.start_fixture(owner.membership,claim)
        assert not synthetic._attempts
    finally:synthetic.shutdown()
    grant=owner.issue_workflow_engineer_grant(bundle,token,obs,files=FILES)
    lease=owner.register(bundle,token,obs,claim,request_key='live_engineer',
        scenario='native_model',native_model_grant=grant)
    attempt=owner._issued(lease);source=attempt['source'];row=owner.sources._issued(source)
    assert json.loads(source.raw)['data_mode']=='live'
    assert row['producer'] is None and not attempt['release_entered']
    owner.stop_to_terminal(lease)
    assert owner._current(attempt)['status']=='SETTLED' and owner.pool.snapshot()['occupied']==0
    assert all(fd is None for fd in row['fds'].values())
    plans.store.snapshot()
    assert plans.store.recover()==plans.store.audit()==plans.store.replay()
    # Editing mode/profile cannot promote historical fixture actions.
    historical=deepcopy(intent)
    historical['request']['action']='prepare_fixture_runtime_installation'
    historical['request_hash']=digest(historical['request'])
    with pytest.raises((Conflict,ProtocolError)):
        validate_record(INSTALLATION[0],intent_key(historical['request']),historical)
    profile_only=deepcopy(member);profile_only['data_mode']='fixture'
    with pytest.raises(Conflict):validate_member(profile_only)
    changed=deepcopy(member);changed['bootstrap']['domain_profile']='CALLER_SELECTED'
    with pytest.raises(Conflict):validate_member(changed)

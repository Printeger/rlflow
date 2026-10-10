"""Workflow admission arithmetic; not authentic source/usage evidence."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from rlflow.hybrid_a_workflow_accounting import advance,check_window
from rlflow.store import Conflict

HASH='sha256:'+'a'*64
NOW=datetime(2026,10,11,tzinfo=timezone.utc)


def entry():
    workflow={'stage':'FIRST_ENGINEER','envelope_sha256':HASH,'accounting_version':'A_REGISTRATION_CEILINGS_V1',
        'limits':{'medium_sessions':6,'high_sessions':2,'controlled_seconds':3600,'wall_seconds':5400}}
    return {'request':{'project_id':'project_fixture','data_mode':'fixture','idempotency_key':'first',
        'fixture_runtime':{'phase':'REGISTER_NO_HANDOFF','origin':{'native_model':{
            'workflow':workflow,'role':'Engineer','effort':'medium','seconds':300}}}},
        'policy_source':{'approval_hash':HASH},'prior_reservation':{'amount':{'wall_seconds':310}},
        'recorded_at':NOW.isoformat().replace('+00:00','Z')}


def test_first_registration_charges_once_and_cleanup_cannot_reset():
    value=entry();head=advance(value,None)
    assert (head['medium_sessions'],head['high_sessions'],head['controlled_seconds_charged'])==(1,0,310)
    for stage in ('HANDOFF_UNKNOWN','STOP_REQUESTED','FIXTURE_SCOPE_STOPPED'):
        changed=deepcopy(value);changed['request']['fixture_runtime']['phase']=stage
        assert advance(changed,head)==head
    for key in ('same','new_attempt','reapproved'):
        changed=deepcopy(value);changed['request']['idempotency_key']=key
        changed['policy_source']['approval_hash']='sha256:'+'b'*64
        with pytest.raises(Conflict,match='already registered'):advance(changed,head)


@pytest.mark.parametrize('bad',['seconds','oversize_reservation','role','effort','boolean_limit','stage'])
def test_time_role_and_closed_limits_refuse(bad):
    value=entry();binding=value['request']['fixture_runtime']['origin']['native_model']
    if bad=='seconds':binding['workflow']['limits']['controlled_seconds']=300
    elif bad=='oversize_reservation':value['prior_reservation']['amount']['wall_seconds']=3601
    elif bad=='role':binding['role']='Evaluator'
    elif bad=='effort':binding['effort']='high'
    elif bad=='boolean_limit':binding['workflow']['limits']['high_sessions']=True
    else:binding['workflow']['stage']='REVIEW'
    from rlflow.hybrid_protocol import ProtocolError
    with pytest.raises((Conflict,ProtocolError)):advance(value,None)


def test_exact_wall_boundary_and_quota_exhaustion_refuse():
    value=entry();workflow=value['request']['fixture_runtime']['origin']['native_model']['workflow']
    head=advance(value,None)
    check_window(head,workflow,NOW+timedelta(seconds=5399))
    for offset in (-1,5400,5401):
        with pytest.raises(Conflict):check_window(head,workflow,NOW+timedelta(seconds=offset))
    for field,amount in (('medium_sessions',7),('high_sessions',3),('controlled_seconds_charged',3601)):
        changed={**head,field:amount}
        with pytest.raises(Conflict):check_window(changed,workflow,NOW)

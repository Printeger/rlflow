"""Pure arithmetic only: actual protected ledger integration is separate."""
from copy import deepcopy

import pytest

from rlflow.hybrid_budget import (DIMENSIONS,MAXIMUM,zero,vector,add,subtract,
    account_key,balances,validate_balances,finalization_floor,reserve,project_exposure,
    rebase,mark_unknown,cancel_held,settle_known)
from rlflow.store import Conflict


def amounts(**changes):
    return {**zero(),**changes}


def test_unknown_is_reserved_subset_not_second_charge():
    value=balances(amounts(model_sessions=10),amounts(model_sessions=2),
                   amounts(model_sessions=3),amounts(model_sessions=3))
    assert value['model_sessions']=={'limit':10,'consumed':2,'reserved':3,
        'unknown_exposure':3,'available':5,'overrun':0}
    assert validate_balances(value)['unknown_exposure']['model_sessions']==3


@pytest.mark.parametrize('damage',['bool','negative','float','overflow','missing','extra','list'])
def test_vectors_require_actual_closed_int64(damage):
    value=zero()
    if damage=='bool':value['model_sessions']=True
    elif damage=='negative':value['model_sessions']=-1
    elif damage=='float':value['model_sessions']=1.0
    elif damage=='overflow':value['model_sessions']=MAXIMUM+1
    elif damage=='missing':value.pop('wall_seconds')
    elif damage=='extra':value['cpu_seconds']=1
    else:value=list(value.values())
    with pytest.raises(Conflict):vector(value)


def test_arithmetic_does_not_wrap_or_underflow():
    with pytest.raises(Conflict):add(amounts(model_sessions=MAXIMUM),amounts(model_sessions=1))
    with pytest.raises(Conflict):subtract(zero(),amounts(model_sessions=1))
    with pytest.raises(Conflict):balances(zero(),amounts(model_sessions=MAXIMUM),amounts(model_sessions=1),zero())
    assert add(amounts(wall_seconds=1),amounts(wall_seconds=2))==amounts(wall_seconds=3)


@pytest.mark.parametrize('field',['available','overrun','reserved','unknown_exposure'])
def test_rehashed_derived_balances_cannot_break_conservation(field):
    value=balances(amounts(model_sessions=10),zero(),amounts(model_sessions=3),zero())
    value['model_sessions'][field]+=4 if field=='unknown_exposure' else 1
    with pytest.raises(Conflict):validate_balances(value)


def test_unknown_cannot_exceed_retained_reservation():
    with pytest.raises(Conflict):balances(amounts(model_sessions=10),zero(),zero(),amounts(model_sessions=1))


def test_approved_limit_reduction_preserves_exposure_and_overrun():
    value=balances(amounts(model_sessions=2),amounts(model_sessions=2),
                   amounts(model_sessions=1),amounts(model_sessions=1))
    assert value['model_sessions']['available']==0 and value['model_sessions']['overrun']==1
    with pytest.raises(Conflict):reserve(value,amounts(wall_seconds=1),purpose='RECOVERY',fraction=0)


def test_planning_floor_is_not_spent_and_execution_cannot_invade_it():
    limits=amounts(model_sessions=10,wall_seconds=11)
    assert finalization_floor(limits,0.2)==amounts(model_sessions=2,wall_seconds=3)
    value=balances(limits,zero(),zero(),zero());original=deepcopy(value)
    next_value=reserve(value,amounts(model_sessions=8),purpose='EXECUTION',fraction=0.2)
    assert value==original and next_value['model_sessions']['consumed']==0
    with pytest.raises(Conflict):reserve(next_value,amounts(model_sessions=1),purpose='EXECUTION',fraction=0.2)
    final=reserve(next_value,amounts(model_sessions=2),purpose='FINAL_VALIDATION',fraction=0.2)
    assert final['model_sessions']['reserved']==10


@pytest.mark.parametrize('fraction',[True,'0.2',float('nan'),float('inf'),-0.1,0.9])
def test_invalid_planning_fraction_refused(fraction):
    with pytest.raises(Conflict):finalization_floor(zero(),fraction)


def test_stable_account_identity_has_no_epoch_revision_adapter_slot():
    scope={'project_id':'project_fixture','data_mode':'fixture','goal_ref':'goal_original'}
    assert account_key(dict(scope))==account_key(scope)
    for field in ('store_epoch','contract_revision','adapter'):
        with pytest.raises(ValueError):account_key({**scope,field:'different'})
    assert account_key({**scope,'goal_ref':'goal_other'})!=account_key(scope)


def test_project_aggregate_does_not_invent_project_limit_or_host_pool():
    one=balances(amounts(model_sessions=10),amounts(model_sessions=2),amounts(model_sessions=1),zero())
    two=balances(amounts(model_sessions=10),zero(),amounts(model_sessions=2),amounts(model_sessions=2))
    assert project_exposure([one,two])=={'consumed':amounts(model_sessions=2),
        'reserved':amounts(model_sessions=3),'unknown_exposure':amounts(model_sessions=2)}


@pytest.mark.parametrize('purpose',['','unknown','execution'])
def test_explicit_purpose_and_nonempty_request_required(purpose):
    value=balances(amounts(model_sessions=10),zero(),zero(),zero())
    with pytest.raises(Conflict):reserve(value,amounts(model_sessions=1),purpose=purpose,fraction=0)
    with pytest.raises(Conflict):reserve(value,zero(),purpose='EXECUTION',fraction=0)


def test_rebase_preserves_all_cumulative_exposure_and_records_overrun():
    original=balances(amounts(model_sessions=10),amounts(model_sessions=3),
                      amounts(model_sessions=4),amounts(model_sessions=2))
    changed=rebase(original,amounts(model_sessions=5))
    assert changed['model_sessions']=={'limit':5,'consumed':3,'reserved':4,
        'unknown_exposure':2,'available':0,'overrun':2}
    assert original['model_sessions']['limit']==10


def test_unknown_transition_retains_exact_reservation():
    original=balances(amounts(model_sessions=10),zero(),amounts(model_sessions=3),zero())
    changed=mark_unknown(original,amounts(model_sessions=3))
    assert changed['model_sessions']['reserved']==3 and changed['model_sessions']['unknown_exposure']==3
    assert changed['model_sessions']['available']==original['model_sessions']['available']==7
    with pytest.raises(Conflict):mark_unknown(changed,amounts(model_sessions=1))


def test_cancel_math_preserves_other_unknown_and_never_returns_consumed():
    original=balances(amounts(model_sessions=10),amounts(model_sessions=2),
                      amounts(model_sessions=5),amounts(model_sessions=3))
    changed=cancel_held(original,amounts(model_sessions=2))
    assert changed['model_sessions']['consumed']==2 and changed['model_sessions']['reserved']==3
    assert changed['model_sessions']['unknown_exposure']==3
    with pytest.raises(Conflict):cancel_held(original,amounts(model_sessions=3))


@pytest.mark.parametrize('status',['HELD','UNKNOWN'])
def test_known_usage_math_consumes_even_failed_work_and_exposes_overrun(status):
    original=balances(amounts(model_sessions=2),amounts(model_sessions=1),
        amounts(model_sessions=1),amounts(model_sessions=1) if status=='UNKNOWN' else zero())
    changed=settle_known(original,amounts(model_sessions=1),amounts(model_sessions=2),prior_status=status)
    assert changed['model_sessions']=={'limit':2,'consumed':3,'reserved':0,
        'unknown_exposure':0,'available':0,'overrun':1}
    with pytest.raises(Conflict):reserve(changed,amounts(model_sessions=1),purpose='RECOVERY',fraction=0)


@pytest.mark.parametrize('status',['CANCELLED','SETTLED','',True])
def test_terminal_or_unknown_status_cannot_settle_again(status):
    original=balances(amounts(model_sessions=10),zero(),amounts(model_sessions=1),zero())
    with pytest.raises(Conflict):settle_known(original,amounts(model_sessions=1),zero(),prior_status=status)

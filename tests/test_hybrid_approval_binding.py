"""Full approval validation once, with exact outer revision correspondence."""
from copy import deepcopy

import pytest

from rlflow.hybrid_authority import _approval_binding, _validate_approval, SECTIONS as AUTHORITY
from rlflow.hybrid_goals import SECTIONS as GOALS, revision_key, digest, validate_record
from rlflow.hybrid_preparation import _references
from rlflow.hybrid_registry import Registry
from rlflow.store import Conflict
from tests.test_hybrid_preparation import prepared
from tests.test_execution_adapter import setup as native_setup


def test_preparation_reuses_full_binding_once_not_a_skipped_validation(prepared,monkeypatch):
    store, _, _, value, _, state = prepared; sources=value['sources']; calls=[]
    resolve=Registry.resolve
    def counted(self,proposal): calls.append(True); return resolve(self,proposal)
    monkeypatch.setattr(Registry,'resolve',counted)
    lookup=lambda s,k:state.get(s,{}).get(k)
    fact=_references(sources,lookup)
    assert len(calls)==1
    assert _approval_binding(fact,lookup)[:2] == (sources['goal_ref'],sources['contract_key'])
    assert _validate_approval(fact,lookup) == (sources['goal_ref'],sources['contract_key'])
    assert store.version()==2


def test_deduplicated_binding_cannot_validate_another_valid_contract_revision(prepared):
    _, _, _, value, _, state=prepared; sources=deepcopy(value['sources'])
    newer=deepcopy(state[GOALS[0]][sources['contract_key']]); proposal=newer['contract']['proposal']
    proposal['contract_version'] += 1; proposal['objective'] += ' Different immutable revision.'
    newer['contract']['version'] += 1
    newer['contract']['hash'] = digest(proposal)
    newer['previous_hash']=sources['proposal_hash']
    key=revision_key(proposal); validate_record(GOALS[0],key,newer)
    state=deepcopy(state); state[GOALS[0]][key]=newer
    sources.update(contract_key=key,contract_revision=proposal['contract_version'],
                   proposal_hash=digest(proposal),record_hash=digest(newer))
    # Original approval/confirmation still exactly resolves ORIGINAL revision.
    lookup=lambda s,k:state.get(s,{}).get(k)
    assert _approval_binding(state[AUTHORITY[0]][sources['approval_key']],lookup)[1] != key
    with pytest.raises(Conflict,match='binding differs from original source revision'):
        _references(sources,lookup)


def test_fixed_cpu_trial_catalog_is_detached_and_strict_requests_are_denied():
    from rlflow.hybrid_cpu_trial import registration, approved_binding
    from tests.test_hybrid_goal_v1_1 import explicit
    pins=['sha256:'+'a'*64,'sha256:'+'b'*64]; registered=registration(*pins)
    proposal=explicit(); proposal.update(goal_kind='research',allowed_tools=['cpu_trial'])
    proposal['scope']['allowed_command_templates']=['cpu_trial']
    proposal['evaluation_data']={'mode':'EXPLICIT_NONE','datasets':[],
        'evaluation_rule':{'id':'cpu_trial_rule','version_hash':digest(registered['rule'])}}
    proposal['budget']['experiment_starts']=3
    config={'tools':{'cpu_trial':registered['tool']},'commands':{'cpu_trial':registered['command']},
        'evaluation_rules':{'cpu_trial_rule':registered['rule']},'resource_profile':registered['resources']}
    assert approved_binding(proposal,config,*pins)['profile']=='FIXED_CPU_PI_TRIAL_V1'
    config['resource_profile']['mode']='strict'
    with pytest.raises(Conflict,match='partial limits'): approved_binding(proposal,config,*pins)
    # A returned catalog mutation never changes the trusted module's limits.
    assert registration(*pins)['resources']['mode']=='compatible_cpu'

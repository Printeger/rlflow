import copy
import pytest
from rlflow import packages,search,experiments
from rlflow.store import Conflict
from test_engine import harness
from test_packages import specification,approved
from test_experiments_v2 import spec,wait


def family(h):
    template=spec(h);template['stage_id']='PKG';template['argv']+=['{{seed}}','{{gain}}']
    return {'id':'grid','template':template,'parameters':{'seed':{'minimum':1,'maximum':2,'step':1},'gain':{'minimum':0.1,'maximum':0.2,'step':0.1}}}


def test_approved_ranges_expand_bind_execute_once_and_share_authority(harness):
    h=harness;value=specification(h);value['parameter_search']=[family(h)]
    h.store.transact('FIXTURE_CONDITION','condition',lambda s:s['evidence'].update(condition={'id':'condition','sha256':'1'*64,'accepted':True}))
    p=approved(h,value);trials=p['spec']['experiments']
    assert len(trials)==4 and {t['seed'] for t in trials}=={1,2}
    assert packages.validate(p['spec'],h.store.root)==p['spec']
    for trial in trials:
        j=experiments.submit(h.store,trial);assert wait(h,j['id'])['status']=='SUCCEEDED'
        assert experiments.submit(h.store,trial)['id']==j['id']
    assert (h.repo/'starts.txt').read_text()=='4'
    assert len(h.store.replay()['approvals'])==1
    drift=copy.deepcopy(trials[0]);drift['argv'][-1]='0.3'
    with pytest.raises(Conflict):experiments.submit(h.store,drift)


@pytest.mark.parametrize('mutation',[
 lambda v:v['parameters']['gain'].update(step=0),
 lambda v:v['parameters']['gain'].update(maximum=1000),
 lambda v:v['parameters']['gain'].update(minimum=True),
 lambda v:v['parameters']['gain'].update(step=float('nan')),
 lambda v:v['parameters'].update(unwired={'minimum':1,'maximum':1,'step':1}),
 lambda v:v['parameters']['seed'].update(step=0.5),
])
def test_search_cannot_escape_numeric_bounds_or_omit_parameter_binding(harness,mutation):
    v=family(harness);mutation(v)
    with pytest.raises(Conflict):search.expand(v)

"""Operator-owned first real-task checks, not editable Engineer input.

Run inside the existing managed candidate CPU scope. Failure is JSON metrics,
not expected exception output or a model-selected test/threshold.
"""
import json

from rlflow.web_auth import AuthStore,Credential,Principal


def measure():
    outcomes={}
    def check(name,operation):
        try:outcomes[name]=operation() is True
        except Exception:outcomes[name]=False
    clock=[10.0]
    human=Principal('a_task_human','human',frozenset({'viewer','operator'}),frozenset({'project_a'}))
    password='isolated-task-not-a-real-passphrase'
    store=AuthStore([Credential.create(human,password)],clock=lambda:clock[0])
    viewer=Principal('a_task_reader','agent',frozenset({'viewer'}),frozenset({'project_a'}))
    token,access=store.issue_bearer(viewer,ttl=30)
    request_token,request_access=store.issue_request_token(viewer,ttl=30)
    result=store.login(human.id,password)
    check('valid_request',lambda:store.resolve(request_token,'request') is request_access)
    check('valid_bearer',lambda:store.resolve(token,'bearer') is access)
    check('wrong_method',lambda:store.resolve(token,'session') is None)
    check('project_scope',lambda:access.principal.allows('project_a') and not access.principal.allows('project_b'))
    check('readonly_role',lambda:not access.principal.allows('project_a','operator') and not access.principal.allows('project_a','approver'))
    # Generated cases are external inputs, not instructions prescribing a fix.
    for name,value in [('none',None),('bytes',b'x'*32),('integer',7),('short','a'*19),
            ('long','a'*129),('unknown','a'*32),('unicode','界'*32),
            ('high_surrogate','a'*20+chr(0xd800)),('low_surrogate','a'*20+chr(0xdfff))]:
        check(name,lambda value=value:store.resolve(value,'bearer') is None)
        check(name+'_preserves_live_purposes',lambda:
            store.resolve(token,'bearer') is access and
            store.resolve(request_token,'request') is request_access and
            result is not None and store.resolve(result[0],'session') is result[1] and
            access.principal.roles==frozenset({'viewer'}) and
            access.principal.projects==frozenset({'project_a'}) and
            result[1].principal.roles==frozenset({'viewer','operator'}) and
            result[1].principal.projects==frozenset({'project_a'}))
    store.revoke(token)
    check('revoked',lambda:store.resolve(token,'bearer') is None)
    token,_=store.issue_bearer(viewer,ttl=30);clock[0]+=30
    check('expired',lambda:store.resolve(token,'bearer') is None)
    check('valid_session',lambda:result is not None and store.resolve(result[0],'session') is result[1])
    check('session_not_bearer',lambda:result is not None and store.resolve(result[0],'bearer') is None)
    return {'cases':len(outcomes),'passed':sum(outcomes.values()),
        'failed':sum(not value for value in outcomes.values())}


if __name__=='__main__':print(json.dumps(measure(),sort_keys=True),flush=True)

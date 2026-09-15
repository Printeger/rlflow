"""Revocations are terminal append-only facts and never return resources."""
import time
from .store import Conflict


def revoke(store, aid, reason):
    if not reason.strip(): raise Conflict('revocation reason required')
    def change(s):
        a = s['approvals'].get(aid)
        if not a or a.get('decision') != 'APPROVED': raise Conflict('no effective approval')
        a.update(revoked=True, revocation_reason=reason)
        sid = a['stage_id']
        if a['scope'] in {'STAGE','STAGE_EXTENSION','PACKAGE'}:
            if sid in s['stages']: s['stages'][sid]['status'] = 'REVOKED'
            if sid in s.get('packages', {}): s['packages'][sid]['status'] = 'REVOKED'
            s['autonomous_tasks'] = [tid for tid in s.get('autonomous_tasks', []) if s['tasks'][tid]['stage_id'] != sid]
        return {'approval_id': aid, 'reason': reason}
    return store.transact('AUTHORIZATION_REVOKED', 'revoke:' + aid, change, object_id=aid, producer='user-cli')

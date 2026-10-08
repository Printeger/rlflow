"""Protected operator session service for immutable, non-executable DRAFTs.

This is an internal integration API. It opens no HTTP route, creates no approval
or lease, and never interprets caller Principal/Access/JSON as authentication.
"""
from contextlib import contextmanager
import threading
from urllib.parse import urlsplit

from .hybrid_goals import bounded_copy, validate_request, digest, propose
from .hybrid_protocol import ProtocolError, validate_schema, ID
from .web_auth import AuthStore


class DraftService:
    def __init__(self, store, auth, *, project_id, data_mode, origin):
        parsed=urlsplit(origin)
        if (type(auth) is not AuthStore or parsed.scheme not in ('http','https') or not parsed.netloc
                or parsed.username or parsed.path or parsed.query or parsed.fragment or data_mode not in ('live','fixture')):
            raise ValueError('invalid protected draft service')
        validate_schema(ID,project_id)
        self.store,self.auth,self.project_id,self.data_mode,self.origin=store,auth,project_id,data_mode,origin
        with store.connect() as db:
            meta=db.execute('SELECT project_id,data_mode,store_epoch FROM observation_meta WHERE singleton=1').fetchone()
        if meta is None or tuple(meta[:2])!=(project_id,data_mode):raise ValueError('draft registration differs from protected service')
        self.store_epoch=meta['store_epoch']
        self._active_writes={};self._active_lock=threading.Lock()
        store.bind_hybrid_drafts(auth,self)

    def check_live_request(self, request_hash, guard):
        # Caller has already authenticated the actual issued operator guard.
        with self._active_lock:staged=self._active_writes.get(guard)
        if staged is None or staged!=request_hash:
            raise PermissionError('actual service-staged draft request required')

    def submit(self, proposal, *, token, csrf, origin, idempotency_key, expected_revision, expected_state_version,
               _control_command_id=None):
        if origin!=self.origin:raise PermissionError('same-origin draft submission required')
        with self.auth.operator_guard(token,project_id=self.project_id,csrf=csrf) as guard:
            principal=guard.check().principal
        if expected_state_version is None:raise ProtocolError('explicit global expected version required')
        request={'action':'propose_goal_draft','project_id':self.project_id,'data_mode':self.data_mode,
            'actor':{'id':principal.id,'kind':principal.kind},'idempotency_key':idempotency_key,
            'expected_revision':expected_revision,'expected_state_version':expected_state_version,'proposal':proposal}
        if _control_command_id is not None:request['control_command_id']=_control_command_id
        request=bounded_copy(request)
        validate_request(request)
        request_hash=digest(request)
        @contextmanager
        def authorization():
            with self.auth.operator_guard(token,project_id=self.project_id,csrf=csrf) as current:
                with self._active_lock:self._active_writes[current]=request_hash
                try:yield current
                finally:
                    with self._active_lock:self._active_writes.pop(current,None)
        return propose(self.store,request['proposal'],principal=principal,project_id=self.project_id,data_mode=self.data_mode,
            idempotency_key=idempotency_key,expected_revision=expected_revision,expected_state_version=expected_state_version,
            _authorization=authorization,_control_command_id=_control_command_id)

"""One project-CWD client, no local Store, scheduler or human credentials.

Credential delivery and the destination origin are trusted launcher inputs,
never repository configuration. HTTP is loopback-only; no proxy or redirects.
"""
import argparse
import json
import os
from pathlib import Path
import re
import stat
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from .hybrid_goals import digest

import yaml

MAX_BYTES = 256 * 1024
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}')


class ClientError(ValueError):
    pass


def read_regular(path, limit):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ClientError('regular input file required')
            value = handle.read(limit + 1)
        if len(value) > limit:
            raise ClientError('bounded regular input required')
        return value
    except OSError as exc:
        raise ClientError('regular input unavailable') from exc


def closed_json(raw,limit=MAX_BYTES):
    if len(raw) > limit:
        raise ClientError('bounded JSON required')
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ClientError('duplicate JSON key')
            value[key] = item
        return value
    try:
        return json.loads(raw, object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ClientError('nonfinite JSON')))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ClientError('closed bounded JSON required') from exc


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ClientError('redirect refused; credential destination is fixed')


class AgentClient:
    def __init__(self, *, cwd=None, environ=None):
        environ = os.environ if environ is None else environ
        cwd = Path.cwd() if cwd is None else Path(cwd)
        # The skill runs in the target project's root, not rlflow's source tree.
        path = cwd / '.rlflow' / 'project.yaml'
        if path.is_symlink() or path.parent.is_symlink():
            raise ClientError('project configuration cannot be a symlink')
        try:
            from .client_project_config import parse
            project_id,config_origin,config_mode=parse(read_regular(path,MAX_BYTES),cwd)
        except (OSError, ValueError, yaml.YAMLError, TypeError, RecursionError) as exc:
            raise ClientError('project configuration unavailable or invalid') from exc
        origin = environ.get('RLFLOW_CONTROL_ORIGIN')
        token = environ.get('RLFLOW_REQUEST_TOKEN')
        if (not isinstance(origin, str) or origin != config_origin
                or not isinstance(token, str) or not token.isascii() or not 20 <= len(token) <= 128
                or not re.fullmatch(r'[A-Za-z0-9_-]+', token)):
            raise ClientError('trusted matching origin and request-only token required')
        try:
            parsed = urlsplit(origin)
            port = parsed.port
        except ValueError as exc:
            raise ClientError('canonical loopback origin required') from exc
        host = '[::1]' if parsed.hostname == '::1' else parsed.hostname
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', '::1')
                or port is None or not 1 <= port <= 65535 or parsed.netloc != f'{host}:{port}'
                or parsed.path or parsed.query or parsed.fragment or parsed.username):
            raise ClientError('canonical loopback origin required; remote transport not enabled')
        self.project_id, self.origin, self._token = project_id, origin, token
        self.data_mode = config_mode
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def _call(self, suffix, *, payload=None, key=None, contract=False):
        headers = {'Authorization': 'Bearer ' + self._token, 'Origin': self.origin, 'Accept': 'application/json'}
        raw = None
        if payload is not None:
            try:
                raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
            except (ValueError, TypeError, RecursionError) as exc:
                raise ClientError('valid bounded proposal required') from exc
            if len(raw) > MAX_BYTES:
                raise ClientError('proposal request exceeds bounds')
            headers.update({'Content-Type': 'application/json', 'Idempotency-Key': key})
        endpoint='proposal-contract' if contract else 'agent-requests'+suffix
        url = f'{self.origin}/api/v1/projects/{self.project_id}/{endpoint}'
        limit=512*1024 if contract else MAX_BYTES
        try:
            with self._opener.open(Request(url, data=raw, headers=headers), timeout=5) as response:
                if response.headers.get_content_type() != 'application/json':
                    raise ClientError('JSON receipt required')
                value = closed_json(response.read(limit + 1),limit)
        except HTTPError as exc:
            # Do not print URLs, response bodies or supplied credentials.
            raise ClientError(f'inbox HTTP {exc.code}; reconcile the same request/key, no automatic retry') from None
        except (URLError, TimeoutError, OSError) as exc:
            raise ClientError('inbox response unknown; reconcile the same request/key, no automatic retry') from None
        if self.data_mode is not None and (type(value) is not dict or value.get('data_mode')!=self.data_mode):
            raise ClientError('registered local project mode differs from original service')
        if contract:
            from .hybrid_contract_discovery import validate_public
            try:return validate_public(value,self.project_id,self.data_mode)
            except ValueError:raise ClientError('closed original proposal contract required') from None
        if type(value) is dict and value.get('action') == 'request_finite_stop':
            from .hybrid_agent_stop_requests import validate_public
            try:return validate_public(value, self.project_id)
            except ValueError:raise ClientError('closed original finite STOP receipt required') from None
        if (type(value) is not dict or value.get('schema_version') != '1.0'
                or set(value) != {'schema_version','request_id','project_id','data_mode','store_epoch','action','request_hash','submitted_by','status','execution_enabled','result'}
                or not isinstance(value.get('request_id'), str) or re.fullmatch(r'request_[0-9a-f]{64}', value['request_id']) is None
                or not isinstance(value.get('request_hash'), str) or re.fullmatch(r'sha256:[0-9a-f]{64}', value['request_hash']) is None
                or value.get('data_mode') not in ('fixture', 'live')
                or not isinstance(value.get('store_epoch'), str) or re.fullmatch(r'store_[0-9a-f]{32}', value['store_epoch']) is None
                or value.get('project_id') != self.project_id or value.get('action') != 'submit_goal'
                or value.get('status') not in ('AWAITING_HUMAN', 'UNKNOWN', 'STALE', 'ADOPTED')
                or value.get('execution_enabled') is not False):
            raise ClientError('receipt does not match the non-executing request boundary')
        actor = value['submitted_by']
        if (type(actor) is not dict or set(actor) != {'id', 'kind'} or actor.get('kind') != 'agent'
                or not isinstance(actor.get('id'), str) or ID.fullmatch(actor['id']) is None):
            raise ClientError('scoped agent request identity required')
        result = value['result']
        if value['status'] == 'ADOPTED':
            if (type(result) is not dict or set(result) != {'schema_version','command_id','action','status','accepted_state_version','duplicate','result'}
                    or result.get('schema_version') != '1.1'
                    or not isinstance(result.get('command_id'), str) or re.fullmatch(r'control_[0-9a-f]{64}', result['command_id']) is None
                    or result.get('action') != 'submit_goal' or result.get('status') != 'SUCCEEDED'
                    or type(result.get('result')) is not dict or result['result'].get('state') != 'DRAFT'
                    or set(result['result']) != {'goal_id','state','proposal_hash','contract_version','execution_enabled','as_of_state_version'}
                    or result['result'].get('execution_enabled') is not False
                    or not isinstance(result['result'].get('goal_id'), str) or ID.fullmatch(result['result']['goal_id']) is None
                    or not isinstance(result['result'].get('proposal_hash'), str) or re.fullmatch(r'sha256:[0-9a-f]{64}', result['result']['proposal_hash']) is None
                    or type(result['result'].get('contract_version')) is not int or result['result']['contract_version'] < 1
                    or type(result.get('accepted_state_version')) is not int or not 1 <= result['accepted_state_version'] <= 2**63 - 1
                    or result['result']['as_of_state_version'] != result['accepted_state_version']
                    or type(result['result']['as_of_state_version']) is not int or type(result['duplicate']) is not bool):
                raise ClientError('original non-executing Core DRAFT receipt required')
        elif result is not None:
            raise ClientError('unaccepted request cannot carry a successful result')
        return value

    def submit_goal(self, proposal, *, key):
        if not isinstance(key, str) or ID.fullmatch(key) is None:
            raise ClientError('explicit original idempotency key required')
        if (type(proposal) is not dict or proposal.get('project_id') != self.project_id
                or self.data_mode is not None and proposal.get('data_mode') != self.data_mode
                or type(proposal.get('contract_version')) is not int or proposal['contract_version'] < 1):
            raise ClientError('explicit project-scoped proposal required')
        result = self._call('', payload={'action': 'submit_goal', 'proposal': proposal,
            'expected_revision': proposal['contract_version'] - 1}, key=key)
        original = {'action': 'propose_goal_draft', 'project_id': self.project_id, 'data_mode': proposal.get('data_mode'),
            'actor': result['submitted_by'], 'idempotency_key': key,
            'expected_revision': proposal['contract_version'] - 1, 'proposal': proposal}
        if result['data_mode'] != proposal.get('data_mode') or result['request_hash'] != digest(original):
            raise ClientError('receipt differs from the exact submitted proposal/key')
        expected_id = 'request_' + digest([self.project_id, result['data_mode'], result['store_epoch'], result['submitted_by'], key]).removeprefix('sha256:')
        if result['request_id'] != expected_id:
            raise ClientError('receipt ID differs from the original scoped request/key')
        if result['status'] == 'ADOPTED':
            r = result['result']['result']
            if (r['goal_id'], r['proposal_hash'], r['contract_version']) != (proposal['goal_id'], digest(proposal), proposal['contract_version']):
                raise ClientError('original draft does not match submitted proposal')
        return result

    def get_status(self, request_id):
        if not isinstance(request_id, str) or re.fullmatch(r'request_[0-9a-f]{64}', request_id) is None:
            raise ClientError('original request ID required')
        value = self._call('/' + request_id)
        if value.get('request_id') != request_id:
            raise ClientError('receipt request identity mismatch')
        return value

    get_report = get_status

    def describe(self):
        return self._call('',contract=True)

    def request_finite_stop(self, stop_scope, *, key):
        from .hybrid_agent_stop_requests import validate_scope
        if self.data_mode not in (None,'fixture'):
            raise ClientError('original finite STOP requires fixture project mode')
        if not isinstance(key,str) or ID.fullmatch(key) is None:
            raise ClientError('explicit original finite request key required')
        try:validate_scope(stop_scope)
        except ValueError:raise ClientError('explicit complete original finite scope required') from None
        result=self._call('',payload={'action':'request_finite_stop','stop_scope':stop_scope},key=key)
        if result['action']!='request_finite_stop' or result['stop_scope']!=stop_scope:
            raise ClientError('finite receipt differs from explicit original scope')
        original={'schema_version':'1.0','action':'request_finite_stop','project_id':self.project_id,
            'data_mode':'fixture','store_epoch':result['store_epoch'],'actor':result['submitted_by'],
            'idempotency_key':key,'stop_scope':stop_scope}
        rid='request_'+digest([self.project_id,'fixture',result['store_epoch'],result['submitted_by'],key]).removeprefix('sha256:')
        if result['request_id']!=rid or result['request_hash']!=digest(original):
            raise ClientError('finite receipt differs from exact scoped original key/body')
        return result


def arguments(parser):
    actions = parser.add_subparsers(dest='client_action', required=True)
    actions.add_parser('skill-path', help='print the packaged single rlflow skill location')
    actions.add_parser('describe',help='read original registered proposal schema/catalog; never authority')
    submit = actions.add_parser('submit-goal')
    submit.add_argument('--proposal', type=Path, required=True)
    submit.add_argument('--key', required=True)
    stop=actions.add_parser('request-finite-stop',help='suggest explicitly enumerated original finite scope STOP; no direct cancellation')
    stop.add_argument('--scope',type=Path,required=True)
    stop.add_argument('--key',required=True)
    for name in ('status', 'report'):
        read = actions.add_parser(name)
        read.add_argument('--request', required=True)


def main(args):
    try:
        if args.client_action == 'skill-path':
            print(Path(__file__).parent / 'skills' / 'rlflow' / 'SKILL.md')
            return 0
        client = AgentClient()
        if args.client_action == 'describe':
            result=client.describe()
        elif args.client_action == 'submit-goal':
            value = closed_json(read_regular(args.proposal, MAX_BYTES))
            result = client.submit_goal(value, key=args.key)
        elif args.client_action == 'request-finite-stop':
            value=closed_json(read_regular(args.scope, MAX_BYTES))
            result=client.request_finite_stop(value,key=args.key)
        else:
            result = client.get_status(args.request)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (ClientError, OSError):
        print('rlflow client failed or result unknown; retain the original request/key and check trusted provisioning. No automatic retry.', file=__import__('sys').stderr)
        return 2

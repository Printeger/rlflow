"""Loopback web service with explicit, protected non-executing controls.

No default password, public listener, scheduler, model invocation or artifact API.
"""
from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import math
import os
import stat
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

from .web_api import Project, create_app
from .web_auth import AuthStore, Credential, Principal


def local_origin(origin):
    parsed = urlsplit(origin)
    try:
        if parsed.scheme != "http" or parsed.username or parsed.path or parsed.query or parsed.fragment or not ipaddress.ip_address(parsed.hostname).is_loopback or not 1 <= parsed.port <= 65535:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("local service requires an explicit loopback HTTP origin and port") from None
    return parsed.hostname, parsed.port


def provision(root, project_id, config_path, passphrase, *, data_mode="live", origin="http://127.0.0.1:8765"):
    """Explicit trusted operator action; refuses fresh stores/overwrites."""
    local_origin(origin)
    root = Path(root).resolve(strict=True)
    if not (root / "runtime" / "research.db").is_file():
        raise ValueError("provisioning requires an existing rlflow store")
    principal = Principal("local", "human", frozenset({"viewer"}), frozenset({project_id}))
    credential = Credential.create(principal, passphrase)
    config = {"schema_version": "1.0", "origin": origin,
              "projects": [{"id": project_id, "root": str(root), "data_mode": data_mode}],
              "credentials": [{"principal_id": principal.id, "kind": "human", "roles": sorted(principal.roles),
                               "projects": sorted(principal.projects), "salt": credential.salt, "digest": credential.digest}]}
    # The operator requested this migration explicitly, never a GET side effect.
    from .observation import enable
    from .store import Store
    path = Path(config_path).absolute()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        enable(Store(root), project_id, data_mode=data_mode)
        with os.fdopen(fd, "w") as output:
            fd = -1
            json.dump(config, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        if fd != -1:
            os.close(fd)
        # Keep the failed provision file for explicit recovery; never overwrite
        # another operator's existing configuration or silently delete material.
        raise
    return config


MAX_CONFIG_BYTES = 2 * 1024 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate configuration key')
        result[key] = value
    return result


def _read_config(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size > MAX_CONFIG_BYTES:
            raise ValueError("configuration must be an owner-only regular file (0600)")
        with os.fdopen(fd, "rb") as source:
            fd = -1
            raw = source.read(MAX_CONFIG_BYTES + 1)
            if len(raw) > MAX_CONFIG_BYTES:
                raise ValueError('configuration exceeds byte bound')
            # Bound nesting before JSON parsing; quoted braces are not nesting.
            depth = 0; quoted = False; escaped = False
            for byte in raw:
                if quoted:
                    if escaped: escaped = False
                    elif byte == 92: escaped = True
                    elif byte == 34: quoted = False
                elif byte == 34: quoted = True
                elif byte in (91, 123):
                    depth += 1
                    if depth > 48: raise ValueError('configuration nesting exceeds bound')
                elif byte in (93, 125): depth -= 1
            def reject_constant(value):
                raise ValueError('nonfinite configuration number')
            def finite_float(value):
                number = float(value)
                if not math.isfinite(number): raise ValueError('nonfinite configuration number')
                return number
            config = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=reject_constant, parse_float=finite_float)
    finally:
        if fd != -1:
            os.close(fd)
    if not isinstance(config, dict) or config.get('schema_version') not in ('1.0','1.1'):
        raise ValueError('invalid dashboard configuration')
    if config['schema_version'] == '1.0' and (len(raw) > 65536 or 'controls' in config):
        raise ValueError('legacy configuration cannot enable controls')
    return config


def _identities(config):
    if not config.get("projects") or not config.get("credentials"):
        raise ValueError("invalid dashboard configuration")
    local_origin(config["origin"])
    projects = [Project(**p) for p in config["projects"]]
    credentials = [Credential(Principal(c["principal_id"], c["kind"], frozenset(c["roles"]), frozenset(c["projects"])), c["salt"], c["digest"]) for c in config["credentials"]]
    if len({c.principal.id for c in credentials}) != len(credentials):
        raise ValueError("duplicate login principal")
    return config["origin"], projects, AuthStore(credentials)


def load_config(path):
    """Legacy read-only three-tuple API; never silently discard new controls."""
    config = _read_config(path)
    if config['schema_version'] != '1.0':
        raise ValueError('use explicit server configuration loader for schema 1.1')
    return _identities(config)


def load_server_config(path):
    """Private startup only. Registry JSON is never accepted from HTTP."""
    from .hybrid_protocol import ID, TEXT, array, obj, enum, validate_schema
    from .hybrid_registry import Registry, CATALOG
    from .hybrid_drafts import DraftService
    from .hybrid_authority import ApprovalService
    from .hybrid_control import ControlServices
    from .store import Store
    config = _read_config(path)
    if config['schema_version'] == '1.0':
        return (*_identities(config), {})
    project_schema = obj({'id': ID, 'root': TEXT, 'data_mode': enum('live','fixture')})
    credential_schema = obj({'principal_id': ID, 'kind': {'const':'human'},
        'roles': {**array(enum('viewer','operator','approver'),3), 'minItems':1, 'uniqueItems':True},
        'projects': {**array(ID,128), 'minItems':1, 'uniqueItems':True},
        'salt': {'type':'string','pattern':'^[0-9a-f]{32}$'},
        'digest': {'type':'string','pattern':'^[0-9a-f]{64}$'}})
    schema = obj({'schema_version': {'const':'1.1'}, 'origin': TEXT,
        'projects': {**array(project_schema,128),'minItems':1},
        'credentials': {**array(credential_schema,128),'minItems':1},
        'controls': {'type':'object','maxProperties':128,'propertyNames':ID,'additionalProperties':CATALOG}})
    validate_schema(schema, config)
    origin, projects, auth = _identities(config)
    project_map = {p.id:p for p in projects}
    if len(project_map) != len(projects) or not set(config['controls']) <= project_map.keys():
        raise ValueError('invalid control project identities')
    if any(not c.principal.projects <= project_map.keys() for c in auth.credentials.values()):
        raise ValueError('credential scope names an unknown project')
    roots = [Path(p.root).resolve(strict=True) for p in projects]
    if len(set(roots)) != len(roots):
        raise ValueError('project roots must be distinct')
    projects = [Project(p.id,str(root),p.data_mode) for p,root in zip(projects,roots)]
    project_map = {p.id:p for p in projects}
    # Finish validating every catalog before touching any database.
    registries = {key:Registry(value) for key,value in config['controls'].items()}
    for key, registry in registries.items():
        p = project_map[key]
        value = config['controls'][key]
        if (value['project_id'],value['data_mode']) != (p.id,p.data_mode):
            raise ValueError('control registry registration mismatch')
    # No constructors that migrate/create stores. Invalid later projects cannot
    # leave an earlier project migrated or partially enabled.
    from .observation import ObservationReader
    stores = {}
    for p in projects:
        if p.id in registries:
            stores[p.id] = Store.attach_existing(p.root,project_id=p.id,data_mode=p.data_mode)
        else:
            ObservationReader(p.root,expected_project_id=p.id,expected_data_mode=p.data_mode).head()
    services = {}
    for key, registry in registries.items():
        p = project_map[key]; store = stores[key]
        drafts = DraftService(store,auth,project_id=p.id,data_mode=p.data_mode,origin=origin)
        approvals = ApprovalService(store,auth,registry,project_id=p.id,data_mode=p.data_mode,origin=origin)
        services[key] = ControlServices(drafts,approvals)
    return origin, projects, auth, services


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="explicitly enable observations and create private login config")
    prepare.add_argument("--root", required=True)
    prepare.add_argument("--project-id", required=True)
    prepare.add_argument("--config", required=True)
    prepare.add_argument("--data-mode", choices=("live", "fixture"), default="live")
    prepare.add_argument("--origin", default="http://127.0.0.1:8765")
    serve = sub.add_parser("serve", help="serve configured APIs on explicit loopback address")
    serve.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            phrase = getpass.getpass("New local dashboard passphrase (20+ characters): ")
            if phrase != getpass.getpass("Confirm passphrase: "):
                raise ValueError("passphrases do not match")
            provision(args.root, args.project_id, args.config, phrase, data_mode=args.data_mode, origin=args.origin)
            print("Private configuration created. No scheduler or model was started.")
        else:
            origin, projects, auth, controls = load_server_config(args.config)
            host, port = local_origin(origin)
            import uvicorn
            uvicorn.run(create_app(projects, auth, origin=origin, control_services=controls or None), host=host, port=port,
                        proxy_headers=False, access_log=False, server_header=False)
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error, RecursionError):
        # CLI error messages must not echo private config contents or filenames.
        parser.exit(2, "Dashboard configuration rejected; check owner-only config and explicit loopback origin.\n")


if __name__ == "__main__":
    main()

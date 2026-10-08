"""Loopback-only read-only web service and explicit observation provisioning.

No default password, public listener, scheduler, model invocation or artifact API.
"""
from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import os
import stat
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


def load_config(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size > 65536:
            raise ValueError("configuration must be an owner-only regular file (0600)")
        with os.fdopen(fd, "r") as source:
            fd = -1
            config = json.load(source)
    finally:
        if fd != -1:
            os.close(fd)
    if config.get("schema_version") != "1.0" or not config.get("projects") or not config.get("credentials"):
        raise ValueError("invalid dashboard configuration")
    local_origin(config["origin"])
    projects = [Project(**p) for p in config["projects"]]
    credentials = [Credential(Principal(c["principal_id"], c["kind"], frozenset(c["roles"]), frozenset(c["projects"])), c["salt"], c["digest"]) for c in config["credentials"]]
    if len({c.principal.id for c in credentials}) != len(credentials):
        raise ValueError("duplicate login principal")
    return config["origin"], projects, AuthStore(credentials)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="explicitly enable observations and create private login config")
    prepare.add_argument("--root", required=True)
    prepare.add_argument("--project-id", required=True)
    prepare.add_argument("--config", required=True)
    prepare.add_argument("--data-mode", choices=("live", "fixture"), default="live")
    prepare.add_argument("--origin", default="http://127.0.0.1:8765")
    serve = sub.add_parser("serve", help="serve read-only APIs on configured loopback address")
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
            origin, projects, auth = load_config(args.config)
            host, port = local_origin(origin)
            import uvicorn
            uvicorn.run(create_app(projects, auth, origin=origin), host=host, port=port,
                        proxy_headers=False, access_log=False, server_header=False)
    except (ValueError, OSError, KeyError, TypeError):
        # CLI error messages must not echo private config contents or filenames.
        parser.exit(2, "Dashboard configuration rejected; check owner-only config and explicit loopback origin.\n")


if __name__ == "__main__":
    main()

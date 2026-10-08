"""Bounded trusted-core observations, NOT execution or approval authority.

START_ACK precedes exec: it proves the held wrapper received a bound release,
not vendor/model activity. Public state therefore remains STARTING/PARTIAL.
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import re
import stat
from .hybrid_protocol import validate
from .observation import utc
from .store import Conflict, sha

ACTIVE = {"START_INTENT", "RUNNING", "RECONCILE"}
FACT_LIMIT = 64 * 1024
REQUEST_LIMIT = 4 * 1024 * 1024


def identity_valid(record):
    return (isinstance(record, dict) and set(record) == {"pid", "pgid", "starttime", "boot_id"}
            and all(type(record[k]) is int and 0 < record[k] < 2**31 for k in ("pid", "pgid"))
            and isinstance(record["starttime"], str) and re.fullmatch(r"[0-9]{1,20}", record["starttime"]) is not None
            and isinstance(record["boot_id"], str) and re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", record["boot_id"]) is not None)


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def read_json(directory_fd, name, limit=FACT_LIMIT):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("invalid launch fact storage")
        raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("launch fact exceeds read bound")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("invalid launch fact")
        return value


def phase(fact, name, binding):
    if fact.get("phase") != name or fact.get("binding") != binding or fact.get("binding_sha256") != sha(binding) or not number(fact.get("time")):
        raise ValueError("launch phase binding mismatch")


def collect(store, sid, session):
    """Read only trusted files anchored at root/roles/sid, with closed bounds."""
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", sid) is None:
        raise ValueError("invalid session identity")
    directory = store.root / "roles" / sid
    if session.get("directory") != str(directory):
        raise ValueError("session directory not anchored")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with contextlib.ExitStack() as stack:
        root_fd = os.open(store.root, flags); stack.callback(os.close, root_fd)
        roles_fd = os.open("roles", flags, dir_fd=root_fd); stack.callback(os.close, roles_fd)
        directory_fd = os.open(sid, flags, dir_fd=roles_fd); stack.callback(os.close, directory_fd)
        # Missing ACK is common while launching: do not read the larger request
        # and other facts on every reconciliation of a still-held wrapper.
        ack = read_json(directory_fd, "launch-start_ack.json")
        request = read_json(directory_fd, "request.json", REQUEST_LIMIT)
        release = read_json(directory_fd, "release")
        committed = read_json(directory_fd, "launch-release_committed.json")
        ready = read_json(directory_fd, "launch-ready.json")
        held = read_json(directory_fd, "held-role.json")
        command = read_json(directory_fd, "command.json")
        cli = read_json(directory_fd, "codex-identity.json")
        model_release = read_json(directory_fd, "model-release.json")
    generation = session.get("generation")
    worker = session.get("identity")
    if not isinstance(generation, str) or not generation or not identity_valid(worker) or not identity_valid(cli):
        raise ValueError("invalid launch generation/identity")
    if (type(request.get("recovery_protocol")) is not int or request["recovery_protocol"] < 2
            or request.get("id") != sid or request.get("generation") != generation
            or request.get("root") != str(store.root) or request.get("directory") != str(directory)
            or request.get("scratch") != session.get("scratch") or request.get("before") != session.get("before")
            or request.get("limit") != session.get("limit") or request.get("resources") != session.get("resources")):
        raise ValueError("request binding mismatch")
    if (release != session.get("release_binding") or release.get("session") != sid
            or release.get("generation") != generation or release.get("identity") != worker
            or release.get("request_sha256") != sha(request) or release.get("candidate_sha256") != sha(session["before"])
            or release.get("reservation_seconds") != session.get("limit") or release.get("resources") != session.get("resources")):
        raise ValueError("release is not the committed request")
    phase(committed, "RELEASE_COMMITTED", release)
    phase(ready, "READY", {"session": sid, "generation": generation, "identity": worker})
    if (held.get("session") != sid or held.get("generation") != generation or held.get("owner") != worker
            or held.get("root") != str(store.root) or held.get("directory") != str(directory)
            or held.get("scratch") != session.get("scratch") or not isinstance(held.get("argv"), list)
            or not held["argv"] or held["argv"] != command.get("argv") or held.get("resources") != session.get("resources")):
        raise ValueError("held command binding mismatch")
    if (model_release.get("session") != sid or model_release.get("generation") != generation
            or model_release.get("identity") != cli or not number(model_release.get("started_monotonic"))):
        raise ValueError("CLI release identity mismatch")
    phase(ack, "START_ACK", {"session": sid, "generation": generation, "identity": cli})
    proof = {"kind": "CLI_RELEASE_ACK", "generation": generation, "request_sha256": sha(request),
             "ack_sha256": sha(ack), "released_at": utc(ack["time"]), "observed_at": utc()}
    validate("StartupObservation", proof)
    return proof


def observe(store, sid):
    """Persist once, without changing dispatch/status/authority/budget semantics.

    File errors or stale generations reject ONLY this observation. They are not
    receipt evidence and must not prevent other core reconciliation work.
    """
    session = store.get("sessions", sid)
    if not session or session.get("status") not in ACTIVE or session.get("launch_phase") != "RELEASE_COMMITTED" or session.get("startup_observation") is not None:
        return False
    try:
        proof = collect(store, sid, session)

        def attach(state):
            current = state["sessions"][sid]
            fields = ("generation", "release_binding", "identity", "directory", "scratch", "launch_phase", "before", "limit", "resources")
            if current.get("status") not in ACTIVE or any(current.get(k) != session.get(k) for k in fields) or current.get("startup_observation") is not None:
                raise Conflict("startup observation generation changed")
            current["startup_observation"] = proof

        result = store.transact_objects("ROLE_START_ACK_OBSERVED", sid + ":startup-ack:" + proof["ack_sha256"],
                                        [("sessions", sid)], attach, object_id=sid)
        return not result["duplicate"]
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        return False

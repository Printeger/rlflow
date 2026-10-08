"""Model-free startup facts; fixtures are explicitly not provider evidence."""
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from rlflow import engine, startup_observation
from rlflow.jobs import identity
from rlflow.observation import ObservationReader, enable
from rlflow.store import atomic, canonical, sha
from test_engine import harness  # noqa: F401 -- reuse isolated deterministic dispatch


@pytest.fixture
def startup(harness):
    store = harness.store
    enable(store, "project_startup", data_mode="fixture")
    sid = engine.dispatch_one(store)
    session = store.get("sessions", sid)
    directory = Path(session["directory"])
    worker = identity(os.getpid())
    cli = dict(worker, pid=99999998, pgid=99999998)
    binding = dict(session["release_binding"], identity=worker)
    store.transact_objects("FIXTURE_LAUNCH_IDENTITY", sid + ":fixture", [("sessions", sid)],
                           lambda s: s["sessions"][sid].update(identity=worker, release_binding=binding))
    def phase(name, binding):
        return {"phase": name, "binding": binding, "binding_sha256": sha(binding), "time": time.time()}
    argv = ["/usr/bin/python3", "-c", "pass"]
    facts = {"release": binding, "launch-release_committed.json": phase("RELEASE_COMMITTED", binding),
             "launch-ready.json": phase("READY", {"session": sid, "generation": session["generation"], "identity": worker}),
             "held-role.json": {"session": sid, "generation": session["generation"], "owner": worker,
                                "root": str(store.root), "directory": str(directory), "scratch": session["scratch"], "argv": argv},
             "command.json": {"argv": argv}, "codex-identity.json": cli,
             "model-release.json": {"session": sid, "generation": session["generation"], "identity": cli, "started_monotonic": time.monotonic()},
             "launch-start_ack.json": phase("START_ACK", {"session": sid, "generation": session["generation"], "identity": cli})}
    for name, value in facts.items():
        atomic(directory / name, canonical(value))
    return store, sid, directory, facts


def test_ack_persisted_once_with_no_budget_authority_or_running_inference(startup):
    store, sid, directory, facts = startup
    reader = ObservationReader(store.root)
    before = reader.snapshot()
    prior = store.view()
    assert startup_observation.observe(store, sid)
    session = store.get("sessions", sid)
    assert session["status"] == "RUNNING" and session["launch_phase"] == "RELEASE_COMMITTED"
    assert session["startup_observation"]["kind"] == "CLI_RELEASE_ACK"
    for section in ("stages", "tasks", "approvals", "authorizations", "usage"):
        assert dict(store.view().get(section, {})) == dict(prior.get(section, {}))
    event = reader.events(before["cursor"])[0]
    public = event["payload"]["upsert"][0]
    assert public["state"] == "STARTING" and public["observability"] == "PARTIAL"
    assert public["startup_observation"] == "CLI_RELEASE_ACK" and public["launch_phase"] == "START_ACK"
    assert "started_at" not in public and public["startup_released_at"].endswith("Z")
    assert public["usage_status"] == "UNKNOWN"
    assert "pid" not in json.dumps(public) and str(store.root) not in json.dumps(public)
    version = store.version()
    assert not startup_observation.observe(store, sid)
    assert store.version() == version


@pytest.mark.parametrize("name,field", [("request.json", "generation"), ("request.json", "root"),
    ("release", "request_sha256"), ("release", "candidate_sha256"), ("release", "reservation_seconds"),
    ("request.json", "before"), ("request.json", "limit"), ("request.json", "resources"), ("held-role.json", "resources"),
    ("launch-release_committed.json", "phase"),
    ("launch-ready.json", "binding_sha256"), ("held-role.json", "owner"),
    ("held-role.json", "argv"), ("command.json", "argv"), ("codex-identity.json", "pid"),
    ("model-release.json", "generation"), ("model-release.json", "identity"),
    ("launch-start_ack.json", "binding_sha256"), ("launch-start_ack.json", "time")])
def test_inconsistent_binding_locally_rejected_without_writes(startup, name, field):
    store, sid, directory, facts = startup
    value = json.loads((directory / name).read_text())
    value[field] = "tampered"
    atomic(directory / name, canonical(value))
    version = store.version()
    assert not startup_observation.observe(store, sid)
    assert store.version() == version and "startup_observation" not in store.get("sessions", sid)


def test_fact_fifo_symlink_and_oversize_do_not_block_or_write(startup, monkeypatch):
    store, sid, directory, facts = startup
    ack = directory / "launch-start_ack.json"
    ack.unlink()
    os.mkfifo(ack)
    begin = time.monotonic()
    assert not startup_observation.observe(store, sid)
    assert time.monotonic() - begin < 0.5
    ack.unlink()
    elsewhere = directory / "other.json"
    atomic(elsewhere, canonical(facts["launch-start_ack.json"]))
    ack.symlink_to(elsewhere)
    assert not startup_observation.observe(store, sid)
    ack.unlink()
    atomic(ack, canonical(facts["launch-start_ack.json"]))
    monkeypatch.setattr(startup_observation, "REQUEST_LIMIT", 128)
    assert not startup_observation.observe(store, sid)


def test_directory_symlink_escape_is_rejected(startup):
    store, sid, directory, facts = startup
    other = store.root / "rogue"
    directory.rename(other)
    directory.symlink_to(other, target_is_directory=True)
    assert not startup_observation.observe(store, sid)


def test_generation_changed_before_commit_cannot_attach_old_ack(startup, monkeypatch):
    store, sid, directory, facts = startup
    original = store.transact_objects
    def concurrent(event_type, key, objects, mutate, **kwargs):
        original("FIXTURE_NEW_GENERATION", sid + ":new", [("sessions", sid)],
                 lambda s: s["sessions"][sid].update(generation="new-generation"))
        return original(event_type, key, objects, mutate, **kwargs)
    monkeypatch.setattr(store, "transact_objects", concurrent)
    assert not startup_observation.observe(store, sid)
    assert "startup_observation" not in store.get("sessions", sid)


def test_concurrent_collectors_commit_exactly_one_ack(startup):
    store, sid, directory, facts = startup
    version = store.version()
    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(lambda _: startup_observation.observe(store, sid), range(2)))
    assert sorted(outcomes) == [False, True]
    assert store.version() == version + 1


def test_real_held_wrapper_short_lived_release_ack_remains_observable_after_exit(startup):
    store, sid, directory, facts = startup
    session = store.get("sessions", sid)
    held = dict(facts["held-role.json"], argv=[sys.executable, "-c", "pass"], release_wait_seconds=5,
                deadline=time.monotonic() + 10)
    atomic(directory / "held-role.json", canonical(held))
    atomic(directory / "command.json", canonical({"argv": held["argv"]}))
    for name in ("codex-identity.json", "model-release.json", "launch-start_ack.json"):
        (directory / name).unlink()
    child = subprocess.Popen([sys.executable, "-m", "rlflow.lifeguard", "held-role", str(directory / "held-role.json")], start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not (directory / "codex-identity.json").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        cli = json.loads((directory / "codex-identity.json").read_text())
        atomic(directory / "model-release.json", canonical({"session": sid, "generation": session["generation"],
                                                            "identity": cli, "started_monotonic": time.monotonic()}))
        assert child.wait(timeout=5) == 0
        assert startup_observation.observe(store, sid)
        row = ObservationReader(store.root).page(kind="execution")["items"][0]
        assert row["startup_observation"] == "CLI_RELEASE_ACK" and row["state"] == "STARTING"
    finally:
        if child.poll() is None:
            child.kill(); child.wait()


def test_short_lived_ack_is_collected_at_receipt_acceptance_not_only_first_scan(startup, monkeypatch):
    store, sid, directory, facts = startup
    ack = directory / "launch-start_ack.json"
    ack.unlink()
    assert not startup_observation.observe(store, sid)
    atomic(ack, canonical(facts["launch-start_ack.json"]))
    # A malformed receipt leaves the original reservation uncertain; the startup
    # observer must not settle it merely because the ACK subsequently appeared.
    atomic(directory / "receipt.json", canonical({"session_id": sid, "exit_code": "unknown"}))
    stage_id = store.get("sessions", sid)["stage_id"]
    budget_before = store.get("stages", stage_id)
    engine.accept_result(store, sid)
    assert store.get("sessions", sid)["startup_observation"]["kind"] == "CLI_RELEASE_ACK"
    assert store.get("sessions", sid)["status"] == "RECONCILE"
    assert store.get("stages", stage_id) == budget_before

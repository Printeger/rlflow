import json
import os
import sqlite3
import subprocess
import sys

import pytest

from rlflow import observation
from rlflow.hybrid_protocol import ProtocolError
from rlflow.observation import ObservationReader, enable, rotate_epoch, summary
from rlflow.store import Store


@pytest.fixture
def observed(tmp_path):
    store = Store(tmp_path / "state")
    enable(store, "project_test", data_mode="fixture")
    return store, ObservationReader(store.root)


def change_usage(store, key="s1", **values):
    return store.transact_objects("USAGE_OBSERVED", key, [("usage", "session1")],
                                  lambda s: s.setdefault("usage", {}).update(session1=values))


def test_snapshot_stream_seam_and_idempotency(observed):
    store, reader = observed
    before = reader.snapshot()
    change_usage(store, input_tokens=4, output_tokens=2, cached_tokens=1, complete=True)
    events = reader.events(before["cursor"])
    assert len(events) == 1 and events[0]["seq"] == int(before["cursor"].rsplit(":", 1)[1])+1
    row = events[0]["payload"]["upsert"][0]
    assert row["input_tokens"] == 4
    assert row["actual_cost"] is None and row["actual_cost_status"] == "UNKNOWN"
    assert reader.snapshot()["projection"]["source_state_version"] == store.version()
    cursor = reader.snapshot()["cursor"]
    change_usage(store, input_tokens=4, output_tokens=2, cached_tokens=1, complete=True)
    assert reader.events(cursor) == []
    assert store.version() == 1


def test_bridge_failure_rolls_back_authoritative_event_and_both_projections(observed, monkeypatch):
    store, reader = observed
    before = reader.snapshot()
    original = observation.validate_event
    def reject(*args, **kwargs):
        raise ProtocolError("injected envelope validation failure")
    monkeypatch.setattr(observation, "validate_event", reject)
    with pytest.raises(ProtocolError): change_usage(store, input_tokens=4)
    monkeypatch.setattr(observation, "validate_event", original)
    assert reader.snapshot()["cursor"] == before["cursor"]
    assert reader.snapshot()["projection"] == before["projection"]
    assert store.version() == 0 and store.get("usage", "session1") is None
    assert store.replay() == store.audit()


def test_missing_usage_stays_unknown_and_role_identity_is_not_start_proof():
    row = summary("sessions", "s", {"status": "RUNNING", "role": "Engineer", "compute": {"model": "actual-model"}}, 1)
    assert row["state"] == "STARTING" and row["source_status"] == "RUNNING"
    assert row["usage_status"] == "UNKNOWN"
    assert row["model_id"] == "actual-model"
    assert summary("usage", "s", {}, 1)["input_tokens"] is None
    assert summary("usage", "s", {"complete": True}, 1)["usage_status"] == "UNKNOWN"
    assert summary("usage", "s", {"complete": True,"input_tokens":1,"output_tokens":1,"cached_tokens":2}, 1)["usage_status"] == "PARTIAL"


def test_each_read_transaction_checks_bound_project_and_mode(observed):
    store, base = observed
    cursor = base.head()["cursor"]
    for expected in ({"expected_project_id": "project_other"}, {"expected_data_mode": "live"}):
        reader = ObservationReader(store.root, **expected)
        for call in (reader.head, reader.snapshot, reader.page, lambda: reader.events(cursor)):
            with pytest.raises(ProtocolError, match="identity mismatch"):
                call()


@pytest.mark.parametrize("proof", [{}, {"kind":"CLI_RELEASE_ACK"}, {"kind":"CLI_RELEASE_ACK","generation":None},
    {"kind":"CLI_RELEASE_ACK","generation":"g","observed_at":"broken"},
    {"kind":"CLI_RELEASE_ACK","generation":"g","observed_at":"2026-10-08T00:00:00Z", "released_at":"2026-10-08T00:00:00Z",
     "request_sha256":"invalid","ack_sha256":"invalid"}])
def test_malformed_optional_startup_proof_cannot_claim_ack_or_block_public_bridge(proof):
    row = summary("sessions", "s", {"status":"RUNNING", "generation":"g", "startup_observation":proof}, 1)
    assert row["state"] == "STARTING" and row["usage_status"] == "UNKNOWN"
    assert "startup_observation" not in row


def test_same_entity_version_is_not_source_global_version(observed):
    store, reader = observed
    change_usage(store, "one", input_tokens=1)
    store.transact("CONTROL", "control", lambda s: s.update(enabled=True))
    change_usage(store, "two", input_tokens=2)
    assert store.version() == 3
    assert reader.page(kind="usage")["items"][0]["version"] == 2
    assert reader.snapshot()["projection"]["enabled"]


def test_public_outputs_allowlist_and_redact_free_text(observed):
    store, reader = observed
    secret = "sk-syntheticSecret123"
    value = dict(input_tokens=3, description=f"do task token={secret} /home/mint/.codex/auth.json",
                 auth={"password": "DO_NOT_COPY"}, stderr="PRIVATE_LOG", raw_output="PRIVATE_LOG", complete=False)
    change_usage(store, **value)
    for result in [reader.snapshot(), reader.page(), reader.events(reader.snapshot()["store_epoch"]+":0")]:
        text = json.dumps(result)
        assert secret not in text and "/home/mint" not in text
        assert "DO_NOT_COPY" not in text and "PRIVATE_LOG" not in text
    assert store.get("usage", "session1")["auth"]["password"] == "DO_NOT_COPY"
    assert "SYNTHETIC_SECRET" not in observation.public_text('{"api_key":"SYNTHETIC_SECRET"}')
    assert "/srv/private" not in observation.public_text("/srv/private/auth.json")
    assert "SYNTHETICSECRET" not in summary("tasks", "sk-SYNTHETICSECRET", {}, 1)["id"]


@pytest.mark.parametrize("text,secret", [
    ('{"password":"synthetic private phrase"}', "private phrase"),
    ('{"api_key":"synthetic \\"escaped\\" private phrase"}', "private phrase"),
    ("password='synthetic private phrase'", "private phrase"),
    ('{"token":"synthetic private phrase', "private phrase"),
])
def test_quoted_secret_with_spaces_is_redacted_across_public_exits(observed,text,secret):
    store,reader=observed
    change_usage(store, description=text)
    epoch=reader.snapshot()["store_epoch"]
    for result in (reader.snapshot(),reader.page(),reader.events(epoch+":0")):
        assert secret not in json.dumps(result)


def test_projection_drift_and_missing_event_force_resync(observed):
    store,reader=observed
    change_usage(store,input_tokens=3)
    with store.connect() as db: db.execute("UPDATE observation_meta SET source_version=99")
    with pytest.raises(ProtocolError,match="projection mismatch"): reader.snapshot()
    with store.connect() as db:
        db.execute("UPDATE observation_meta SET source_version=?",(store.version(),))
        db.execute("DROP TRIGGER observation_no_delete")
        db.execute("DELETE FROM observation_events WHERE seq=1")
    # The remaining last event exists, but the durable sequence has a gap.
    epoch=reader.snapshot()["store_epoch"]
    with pytest.raises(ProtocolError,match="sequence gap"): reader.events(epoch+":0")


def test_epoch_rotation_retains_history_and_invalidates_old_cursors(observed):
    store, reader = observed
    change_usage(store, input_tokens=3)
    old = reader.snapshot()
    with store.connect() as db:
        history = [tuple(row) for row in db.execute("SELECT * FROM observation_events")]
    old_state = store.audit()
    rotate_epoch(store)
    assert store.audit() == old_state
    with store.connect() as db:
        assert [tuple(row) for row in db.execute("SELECT * FROM observation_events")] == history
    with pytest.raises(ProtocolError) as error: reader.events(old["cursor"])
    assert error.value.code == "RESYNC_REQUIRED"
    new = reader.snapshot()
    change_usage(store, "next", input_tokens=4)
    assert len(reader.events(new["cursor"])) == 1


def test_cursor_bounds_and_read_only_connection(observed):
    store, reader = observed
    with reader.connect() as db:
        with pytest.raises(sqlite3.OperationalError): db.execute("DELETE FROM observation_projection")
    epoch = reader.snapshot()["store_epoch"]
    with pytest.raises(ProtocolError): reader.events(epoch+":999999")
    assert reader.events(reader.snapshot()["cursor"]) == []
    with store.connect() as db:
        with pytest.raises(sqlite3.IntegrityError): db.execute("DELETE FROM observation_events")


def test_large_commit_is_chunked_with_bounded_projection_pages(observed):
    store, reader = observed
    before = reader.snapshot()
    store.transact("MANY_USAGE", "many", lambda s: s.setdefault("usage", {}).update(
        {f"s{i:04}": {"input_tokens": i} for i in range(420)}))
    events = reader.events(before["cursor"])
    assert len(events) == 3 and sum(len(e["payload"]["upsert"]) for e in events) == 420
    assert reader.snapshot()["projection"]["objects"]["total"] == 420
    assert len(reader.snapshot()["projection"]["objects"]["items"]) == 30
    ids = []
    cursor = ""
    while True:
        page = reader.page(kind="usage", after=cursor, limit=50)
        ids.extend(row["id"] for row in page["items"])
        cursor = page["next_cursor"]
        if cursor is None: break
    assert len(ids) == len(set(ids)) == 420
    with reader.connect() as db:
        plan = db.execute("EXPLAIN QUERY PLAN SELECT kind,object_id,summary FROM observation_projection WHERE (kind,object_id) > (?,?) ORDER BY kind,object_id LIMIT ?", ("", "", 31)).fetchall()
    assert any("SEARCH" in row[3] and "INDEX" in row[3] for row in plan)


def test_removal_and_counter_zero_are_durable(observed):
    store, reader = observed
    change_usage(store, input_tokens=3)
    before = reader.snapshot()
    store.transact_objects("REMOVE", "remove", [("usage", "session1")], lambda s: s["usage"].pop("session1"))
    event = reader.events(before["cursor"])[0]
    assert event["payload"]["removed"] == [{"kind": "usage", "id": observation.public_id("session1")}]
    assert event["payload"]["counters"] == [{"kind": "usage", "status": "UNKNOWN", "count": 0}]
    assert reader.page()["total"] == 0


def test_enable_is_idempotent_identity_cannot_change_and_legacy_bytes_unchanged(tmp_path):
    store = Store(tmp_path / "state")
    change_usage(store, input_tokens=3)
    with store.connect() as db: before = [tuple(row) for row in db.execute("SELECT * FROM events")]
    epoch = enable(store, "project", data_mode="fixture")
    assert enable(store, "project", data_mode="fixture") == epoch
    with pytest.raises(ProtocolError): enable(store, "other", data_mode="fixture")
    with pytest.raises(ProtocolError): enable(store, "project", data_mode="live")
    assert ObservationReader(store.root).page()["items"][0]["input_tokens"] == 3
    with store.connect() as db: assert [tuple(row) for row in db.execute("SELECT * FROM events")] == before


def test_reader_does_not_initialize_missing_state(tmp_path):
    reader = ObservationReader(tmp_path / "missing")
    with pytest.raises(sqlite3.OperationalError): reader.snapshot()
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("boundary, expected", [("before", 0), ("after", 1)])
def test_process_exit_before_and_after_commit_preserves_outbox(observed, boundary, expected):
    store, reader = observed
    before = reader.snapshot()
    program = '''
import os, sqlite3, sys
from rlflow.store import Store
boundary=sys.argv[2]; armed=False
class Connection(sqlite3.Connection):
    def commit(self):
        super().commit()
        if armed and boundary=='after': os._exit(81)
original=sqlite3.connect
sqlite3.connect=lambda *a,**kw: original(*a,**kw,factory=Connection)
store=Store(sys.argv[1]);armed=True
if boundary=='before':
    original_commit=store._commit
    def crash(*a,**kw): original_commit(*a,**kw);os._exit(80)
    store._commit=crash
store.transact_objects('USAGE_OBSERVED','crash',[('usage','s')],lambda s:s.setdefault('usage',{}).update(s={'input_tokens':5}))
'''
    result = subprocess.run([sys.executable, "-c", program, str(store.root), boundary], capture_output=True, text=True, timeout=10)
    assert result.returncode == (80 if boundary == "before" else 81), result.stderr
    recovered = Store(store.root)
    assert recovered.version() == expected
    assert len(reader.events(before["cursor"])) == expected
    assert recovered.audit() == recovered.replay()

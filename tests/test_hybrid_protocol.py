import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from rlflow.hybrid_protocol import OBJECTS, ProtocolError, parse_cursor, payload_registry, validate, validate_event

SPEC = Path(__file__).resolve().parents[1] / "docs" / "hybrid-v1"


def test_all_contracts_are_valid_json_schema_and_closed():
    for schema in [*OBJECTS.values(), *payload_registry().values()]:
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False


def test_spec_examples_validate_with_production_contracts():
    validate("goal", json.loads((SPEC / "examples/goal.fixture.json").read_text()))
    validate("command", json.loads((SPEC / "examples/command.fixture.json").read_text()))
    for line in (SPEC / "examples/events.fixture.ndjson").read_text().splitlines():
        event = json.loads(line)
        validate_event(event, data_mode="fixture")
        with pytest.raises(ProtocolError):
            validate_event(event, data_mode="live")


def test_unknown_critical_payload_and_non_utc_rejected():
    event = json.loads((SPEC / "examples/events.fixture.ndjson").read_text().splitlines()[0])
    unknown = copy.deepcopy(event); unknown["type"] = "unknown.critical"
    with pytest.raises(ProtocolError, match="unknown critical"):
        validate_event(unknown)
    invalid = copy.deepcopy(event); invalid["payload"]["state"] = "SUCCESSFUL"
    with pytest.raises(ProtocolError):
        validate_event(invalid)
    invalid = copy.deepcopy(event); invalid["recorded_at"] = "not-a-date"
    with pytest.raises(ProtocolError):
        validate_event(invalid)
    invalid["recorded_at"] = "2026-10-07T14:30:00+08:00"
    with pytest.raises(ProtocolError, match="UTC"):
        validate_event(invalid)
    invalid = copy.deepcopy(event); invalid["entity"]["kind"] = "execution"
    with pytest.raises(ProtocolError, match="entity kind"): validate_event(invalid)


def test_command_cannot_supply_actor_or_shell_and_proposal_cannot_approve_itself():
    command = json.loads((SPEC / "examples/command.fixture.json").read_text())
    command["actor"] = "human"
    with pytest.raises(ProtocolError): validate("command", command)
    command.pop("actor"); command["parameters"]["shell"] = "arbitrary"
    with pytest.raises(ProtocolError): validate("command", command)
    goal = json.loads((SPEC / "examples/goal.fixture.json").read_text())
    goal["approval_status"] = "APPROVED"
    with pytest.raises(ProtocolError): validate("goal", goal)


def test_budget_unknown_is_subset_not_double_subtracted():
    budget = dict(dimension="calls", limit=10, consumed=2, reserved=4,
                  unknown_exposure=3, available=4, overrun=0, unit="calls")
    validate("Budget", budget)
    for changes in [{"unknown_exposure": 5}, {"available": 1}, {"consumed": True}, {"overrun": 1}]:
        with pytest.raises(ProtocolError): validate("Budget", {**budget, **changes})


def test_usage_missing_is_unknown_and_cached_is_subset():
    usage = dict(source_id="provider", scope_id="thread", scope="thread_including_children",
                 included_child_scopes=["child"], semantics="cumulative", status="UNKNOWN",
                 input_tokens=None, output_tokens=None, cached_tokens=None)
    validate("Usage", usage)
    with pytest.raises(ProtocolError): validate("Usage", {**usage, "scope": "guess"})
    with pytest.raises(ProtocolError): validate("Usage", {**usage, "input_tokens": 2, "cached_tokens": 3})
    with pytest.raises(ProtocolError): validate("Usage", {**usage, "status": "KNOWN"})


@pytest.mark.parametrize("cursor", ["old:1", "epoch:-1", "epoch:01", "epoch:1.2", "epoch:9999999999999999999", "epoch:999999999999999999999999", "epoch", None])
def test_bad_cursor_forces_resync(cursor):
    with pytest.raises(ProtocolError) as error: parse_cursor(cursor, "epoch")
    assert error.value.code == "RESYNC_REQUIRED"
    assert parse_cursor("epoch:0", "epoch") == 0


def test_error_messages_do_not_embed_sensitive_input():
    with pytest.raises(ProtocolError) as error:
        validate("Task", {"id": "sk-secret-fixture", "password": "SECRET"})
    assert "sk-secret" not in str(error.value) and "SECRET" not in str(error.value)


def test_contract_hash_identity_and_completion_are_explicit():
    from rlflow.store import sha
    proposal=json.loads((SPEC/"examples/goal.fixture.json").read_text())
    contract=dict(id=proposal["goal_id"],version=1,hash="sha256:"+sha(proposal),
                  proposal=proposal,state="DRAFT",approval_id=None,outcome=None)
    validate("GoalContract",contract)
    for changes in ({"hash":"sha256:"+"0"*64},{"version":2},{"id":"other"},{"state":"COMPLETED"}):
        with pytest.raises(ProtocolError): validate("GoalContract",{**contract,**changes})


def test_same_session_cannot_supply_passing_independent_evidence():
    digest="sha256:"+"a"*64
    evidence=dict(id="e",goal_id="g",condition_id="c",artifact_ids=["a"],candidate_hash=digest,
                  configuration_hash=digest,data_version_hash=digest,evaluation_rule_hash=digest,
                  verifier_version="v1",implementer_session_id="writer",reviewer_session_id="reviewer",
                  verdict="PASS",limitations=[],counter_evidence_ids=[])
    validate("Evidence",evidence)
    with pytest.raises(ProtocolError,match="independent"):
        validate("Evidence",{**evidence,"reviewer_session_id":"writer"})


def test_reader_lease_cannot_request_writes():
    digest="sha256:"+"a"*64
    lease=dict(id="l",project_id="p",task_id="t",attempt_id="a",contract_hash=digest,
               base_snapshot_hash=digest,runtime_profile_hash=digest,role="reviewer",
               writable_paths=[],readonly_snapshot_hash=digest,max_sessions_including_children=3,
               max_delegation_depth=1,reservation_ids=["r"],expires_at="2026-10-08T00:00:00Z",
               controller_epoch=1,idempotency_key="key")
    validate("Lease",lease)
    with pytest.raises(ProtocolError,match="write"):
        validate("Lease",{**lease,"writable_paths":["src"]})

"""Versioned, closed contracts for Hybrid queries and domain events.

This module validates data, never grants authority. Legacy observations cannot
drive privileged transitions. Unknown critical event types fail closed.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from referencing import Registry, Resource

VERSION = "1.0"
ID = {"type": "string", "minLength": 1, "maxLength": 160,
      "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"}
HASH = {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"}
COUNT = {"type": "integer", "minimum": 0}
TEXT = {"type": "string", "maxLength": 4000}
TIME = {"type": "string", "format": "date-time"}
GOAL_STATES = ("DRAFT", "AWAITING_APPROVAL", "READY", "RUNNING", "WAITING_EXTERNAL", "BLOCKED",
               "PAUSE_REQUESTED", "PAUSED", "STOP_REQUESTED", "STOPPED", "COMPLETED", "BUDGET_EXHAUSTED", "FAILED")
TASK_STATES = ("PROPOSED", "READY", "RUNNING", "AWAITING_REVIEW", "SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED")
ATTEMPT_STATES = ("CREATED", "RESERVED", "STARTING", "RUNNING", "FINISHING", "SUCCEEDED", "FAILED", "CANCEL_REQUESTED", "CANCELLED", "UNKNOWN")
ERROR_CODES = ("AUTH_REQUIRED", "PERMISSION_DENIED", "VERSION_CONFLICT", "IDEMPOTENCY_CONFLICT",
               "BUDGET_EXHAUSTED", "UNKNOWN_EXECUTION", "UNSUPPORTED_CAPABILITY",
               "RESOURCE_ENFORCEMENT_PARTIAL", "RESYNC_REQUIRED", "VALIDATION_ERROR", "NOT_FOUND")
CAPABILITIES = ("planner", "engineer", "explorer", "researcher", "reviewer", "architect", "critic", "designer")


class ProtocolError(ValueError):
    def __init__(self, message, code="VALIDATION_ERROR"):
        super().__init__(message)
        self.code = code


def enum(*values):
    return {"type": "string", "enum": list(values)}


def nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


def array(schema, maximum=200):
    return {"type": "array", "items": schema, "maxItems": maximum}


def obj(properties, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required, "additionalProperties": False}


PUBLIC_KINDS = ("stage", "task", "execution", "job", "proposal", "approval", "experiment",
                "evidence", "hypothesis", "decision", "usage", "package", "authorization", "tool_return")
PUBLIC_PROPERTIES = {
    "id": ID, "kind": enum(*(k for k in PUBLIC_KINDS if k!='tool_return')), "version": {"type": "integer", "minimum": 1},
    "source_status": nullable(TEXT), "observability": enum("OBSERVED", "PARTIAL", "UNKNOWN"),
    "state": nullable(TEXT), "role": nullable(TEXT), "model_id": nullable(TEXT),
    "description": TEXT, "reason": TEXT, "candidate_hash": nullable(HASH),
    "task_id": nullable(ID), "parent_id": nullable(ID), "started_at": nullable(TIME),
    "launch_phase": nullable(TEXT), "usage_status": enum("KNOWN", "PARTIAL", "UNKNOWN"),
    "startup_observation": enum("CLI_RELEASE_ACK"), "startup_observed_at": nullable(TIME), "startup_released_at": nullable(TIME),
    "input_tokens": nullable(COUNT), "output_tokens": nullable(COUNT), "cached_tokens": nullable(COUNT),
    "actual_cost_status": enum("KNOWN", "UNKNOWN"), "actual_cost": nullable({"type": "string", "pattern": r"^[0-9]+(\.[0-9]+)?$"}),
    "used_calls": nullable(COUNT), "reserved_calls": nullable(COUNT), "limit_calls": nullable(COUNT),
    "used_seconds": nullable({"type": "number", "minimum": 0}),
    "reserved_seconds": nullable({"type": "number", "minimum": 0}),
    "limit_seconds": nullable({"type": "number", "minimum": 0}),
}
OPAQUE_ID = {"type":"string","pattern":"^ref_[0-9a-f]{64}$"}
TOOL_RETURN = obj({"id":OPAQUE_ID,"kind":{"const":"tool_return"},"version":{"const":1},
                   "source_status":{"const":"COLLECTED"},"observability":{"const":"PARTIAL"},
                   "state":enum("RETURNED","TIMED_OUT","SETUP_FAILED"),"tool":{"const":"cpu_exec"},
                   "provenance":{"const":"BOUND_RETURN"},"exit_code":{"type":"integer","minimum":-2147483648,"maximum":2147483647},
                   "timed_out":{"type":"boolean"},"wall_seconds":{"type":"number","minimum":0},
                   "infrastructure_error":nullable(enum("CPU_SANDBOX_SETUP_FAILED")),
                   "execution_id":OPAQUE_ID,"task_id":nullable(OPAQUE_ID),"observed_at":{**TIME,"pattern":"Z$"}})
TOOL_RETURN['allOf'] = [{
    'if':{'properties':{'infrastructure_error':{'const':'CPU_SANDBOX_SETUP_FAILED'}}},
    'then':{'properties':{'state':{'const':'SETUP_FAILED'}}},
    'else':{
        'if':{'properties':{'timed_out':{'const':True}}},
        'then':{'properties':{'state':{'const':'TIMED_OUT'}}},
        'else':{'properties':{'state':{'const':'RETURNED'}}},
    },
}]
PUBLIC_OBJECT = obj({name:{} for name in set(PUBLIC_PROPERTIES)|set(TOOL_RETURN['properties'])},[])
PUBLIC_OBJECT['oneOf'] = [obj(PUBLIC_PROPERTIES, ["id", "kind", "version", "source_status", "observability"]),TOOL_RETURN]
TOOL_COVERAGE = obj({"status":{"const":"PARTIAL"},"policy":{"const":"LIVE_ONLY"},
                     "coverage_after_seq":COUNT,"coverage_after_source_version":COUNT,"source":{"const":"BOUND_CPU_RETURN"}})
COUNTER = obj({"kind": enum(*PUBLIC_KINDS), "status": TEXT, "count": COUNT})
PAGE = obj({"items": array(PUBLIC_OBJECT), "next_cursor": nullable(TEXT), "total": COUNT})

OBJECTS = {
    "PublicObject": PUBLIC_OBJECT,
    "ToolReturn": TOOL_RETURN,
    "ToolCoverage": TOOL_COVERAGE,
    "Error": obj({"code": enum(*ERROR_CODES), "message": TEXT, "retryable": {"type": "boolean"},
                  "correlation_id": ID, "details": obj({"current_version": COUNT}, [])},
                 ["code", "message", "retryable", "correlation_id"]),
    "Task": obj({"id": ID, "goal_id": ID, "parent_id": nullable(ID), "dependencies": array(ID),
                 "local_conditions": array(ID), "contributes_to": array(ID),
                 "risk": enum("low", "medium", "high"), "state": enum(*TASK_STATES),
                 "version": {"type": "integer", "minimum": 1}}),
    "Lease": obj({"id": ID, "project_id": ID, "task_id": ID, "attempt_id": ID,
                  "contract_hash": HASH, "base_snapshot_hash": HASH, "runtime_profile_hash": HASH,
                  "role": enum(*CAPABILITIES), "writable_paths": array(TEXT), "readonly_snapshot_hash": HASH,
                  "max_sessions_including_children": {"type": "integer", "minimum": 1, "maximum": 3},
                  "max_delegation_depth": {"type": "integer", "minimum": 0, "maximum": 1},
                  "reservation_ids": array(ID), "expires_at": TIME,
                  "controller_epoch": {"type": "integer", "minimum": 1}, "idempotency_key": ID}),
    "Attempt": obj({"id": ID, "lease_id": ID, "task_id": ID, "session_id": nullable(ID),
                    "thread_id": nullable(ID), "turn_id": nullable(ID), "state": enum(*ATTEMPT_STATES),
                    "controller_epoch": {"type": "integer", "minimum": 1}, "contract_hash": HASH,
                    "base_snapshot_hash": HASH, "output_snapshot_hash": nullable(HASH),
                    "input_hash": HASH, "retry_of": nullable(ID), "version": {"type": "integer", "minimum": 1}}),
    "Usage": obj({"source_id": ID, "scope_id": ID,
                  "scope": enum("session", "turn", "thread_including_children", "child_session"),
                  "included_child_scopes": array(ID), "semantics": enum("cumulative", "incremental"),
                  "status": enum("KNOWN", "PARTIAL", "UNKNOWN"),
                  "input_tokens": nullable(COUNT), "output_tokens": nullable(COUNT), "cached_tokens": nullable(COUNT)}),
    "Budget": obj({"dimension": ID, "limit": COUNT, "consumed": COUNT, "reserved": COUNT,
                   "unknown_exposure": COUNT, "available": COUNT, "overrun": COUNT, "unit": ID}),
    "CommandReceipt": obj({"command_id": ID, "project_id": ID,
                           "status": enum("ACCEPTED", "EXECUTING", "SUCCEEDED", "REJECTED", "FAILED"),
                           "accepted_at": TIME, "result_code": nullable(enum(*ERROR_CODES)), "reason": TEXT}),
    "Snapshot": obj({"schema_version": {"const": VERSION}, "project_id": ID, "store_epoch": ID,
                     "cursor": TEXT, "server_time": TIME, "data_mode": enum("live", "fixture"),
                     "projection": obj({"source_state_version": COUNT, "paused": {"type": "boolean"},
                                        "enabled": {"type": "boolean"}, "counters": array(COUNTER, 1000),
                                    "objects": PAGE, "observability": enum("PARTIAL", "OBSERVED"),
                                    "tool_observations":nullable(TOOL_COVERAGE)},
                                   ["source_state_version","paused","enabled","counters","objects","observability"]) }),
    "ObjectPage": obj({"items": array(PUBLIC_OBJECT), "next_cursor": nullable(TEXT), "total": COUNT,
                       "cursor": TEXT, "project_id": ID, "data_mode": enum("live", "fixture")}),
    "Heartbeat": obj({"server_time": TIME, "cursor": TEXT}),
    "Resync": obj({"code": {"const": "RESYNC_REQUIRED"}, "reason": TEXT}),
    "StartupObservation": obj({"kind": {"const": "CLI_RELEASE_ACK"}, "generation": ID,
                               "request_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                               "ack_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                               "released_at": TIME, "observed_at": TIME}),
}
OBJECTS.update({
    "LogSummary": obj({"schema_version": {"const": VERSION}, "id": ID, "project_id": ID,
                       "store_epoch": ID, "data_mode": enum("live", "fixture"), "source": enum("CORE_STATUS", "TOOL_METADATA"),
                       "template_version": {"const": 1}, "event_id": ID, "seq": COUNT,
                       "occurred_at": TIME, "severity": enum("INFO", "WARNING", "ERROR"), "object_count": COUNT}),
    "LogBody": obj({"summary": obj({"schema_version": {"const": VERSION}, "id": ID, "project_id": ID,
                       "store_epoch": ID, "data_mode": enum("live", "fixture"), "source": enum("CORE_STATUS", "TOOL_METADATA"),
                       "template_version": {"const": 1}, "event_id": ID, "seq": COUNT,
                       "occurred_at": TIME, "severity": enum("INFO", "WARNING", "ERROR"), "object_count": COUNT}),
                    "text": {"type": "string", "maxLength": 65536},
                    "refs": array(obj({"kind": enum(*PUBLIC_KINDS), "id": ID, "version": nullable(COUNT)}), 600),
                    "raw_logs": enum("PRIVATE_ONLY"), "tool_metadata": enum("UNAVAILABLE", "BOUND_RETURN")}),
    "LogPage": obj({"items": array(obj({"schema_version": {"const": VERSION}, "id": ID, "project_id": ID,
                       "store_epoch": ID, "data_mode": enum("live", "fixture"), "source": enum("CORE_STATUS", "TOOL_METADATA"),
                       "template_version": {"const": 1}, "event_id": ID, "seq": COUNT,
                       "occurred_at": TIME, "severity": enum("INFO", "WARNING", "ERROR"), "object_count": COUNT})),
                    "next_cursor": nullable(TEXT), "high_water": TEXT, "coverage_after_seq": COUNT,
                    "project_id": ID, "data_mode": enum("live", "fixture")}),
    "Project": obj({"id": ID, "name": TEXT, "workspace_root": TEXT, "state_root": TEXT,
                    "artifact_root": TEXT, "host_pool_id": ID, "config_hash": HASH,
                    "data_mode": enum("live", "fixture")}),
    "GoalContract": obj({"id": ID, "version": {"type": "integer", "minimum": 1},
                         "hash": HASH, "proposal": {"oneOf": [{"$ref": "urn:rlflow:spec:goal-proposal:1.0"}, {"$ref": "urn:rlflow:spec:goal-proposal:1.1"}]},
                         "state": enum(*GOAL_STATES), "approval_id": nullable(ID),
                         "outcome": nullable(enum("SUCCESS", "NOT_SUPPORTED", "INCONCLUSIVE"))}),
    "Approval": obj({"id": ID, "project_id": ID, "proposal_hash": HASH,
                     "proposal_version": {"type": "integer", "minimum": 1},
                     "principal_id": ID, "principal_kind": {"const": "human"},
                     "scope_hash": HASH, "approved_at": TIME, "expires_at": nullable(TIME),
                     "state": enum("APPROVED", "REJECTED", "REVOKED")}),
    "Evidence": obj({"id": ID, "goal_id": ID, "condition_id": ID,
                     "artifact_ids": {**array(ID), "minItems": 1}, "candidate_hash": HASH,
                     "configuration_hash": HASH, "data_version_hash": HASH,
                     "evaluation_rule_hash": HASH, "verifier_version": ID,
                     "implementer_session_id": ID, "reviewer_session_id": ID,
                     "verdict": enum("PASS", "FAIL", "UNASSESSED", "INCONCLUSIVE"),
                     "limitations": array(TEXT), "counter_evidence_ids": array(ID)}),
    "Experiment": obj({"id": ID, "project_id": ID, "goal_id": ID, "hypothesis_id": ID,
                       "spec_hash": HASH, "candidate_hash": HASH, "dirty_patch_hash": nullable(HASH),
                       "dependency_hash": HASH, "container_hash": nullable(HASH), "data_version_hash": HASH,
                       "configuration_hash": HASH, "evaluation_rule_hash": HASH,
                       "checkpoint_hash": nullable(HASH), "baseline_experiment_id": nullable(ID),
                       "parent_experiment_id": nullable(ID), "seeds": {**array(COUNT), "minItems": 1, "uniqueItems": True},
                       "attempt_ids": array(ID), "artifact_ids": array(ID),
                       "execution_status": enum(*ATTEMPT_STATES),
                       "scientific_validity": enum("UNASSESSED", "VALID", "INVALID", "INCONCLUSIVE"),
                       "hypothesis_outcome": enum("UNASSESSED", "SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE"),
                       "limitations": array(TEXT), "next_reason": TEXT}),
    "BudgetEntry": obj({"id": ID, "goal_id": ID, "dimension": ID,
                        "action": enum("reserve", "consume", "release", "adjust"),
                        "quantity": {"type": "string", "pattern": r"^-?[0-9]+(\.[0-9]+)?$"},
                        "source_id": ID, "idempotency_key": ID, "recorded_at": TIME}),
})

OBJECTS['LogBody']['allOf'] = [{
    'if':{'properties':{'summary':{'properties':{'source':{'const':'TOOL_METADATA'}}}}},
    'then':{'properties':{'tool_metadata':{'const':'BOUND_RETURN'}}},
    'else':{'properties':{'tool_metadata':{'const':'UNAVAILABLE'}}},
}]


MEASURE = nullable({'type':'number','minimum':0})
RESOURCE_PROCESS = obj({'scope':enum('SUPERVISOR_PROCESS','FIXED_WORKER_PROCESS'),'status':enum('KNOWN','UNKNOWN'),
                        'cpu_seconds':MEASURE,'rss_bytes':nullable(COUNT)})
RESOURCE_HEARTBEAT = obj({'status':enum('FRESH','STALE','UNKNOWN'),'counter':nullable(COUNT),'age_seconds':MEASURE})
OBJECTS['Telemetry'] = obj({
    'schema_version':{'const':VERSION},'sample_id':ID,'sampler_epoch':ID,'sample_seq':{'type':'integer','minimum':1},
    'observed_at':{**TIME,'pattern':'Z$'},'project_id':ID,'store_epoch':ID,'data_mode':enum('live','fixture'),
    'source_state_version':nullable(COUNT),
    'source':{'const':'CORE_OS_SAMPLE'},'observability':{'const':'PARTIAL'},'sample_age_seconds':MEASURE,
    'host':obj({
        'cpu':obj({'scope':{'const':'HOST'},'status':enum('KNOWN','UNKNOWN'),
                   'utilization_percent':nullable({'type':'number','minimum':0,'maximum':100})}),
        'memory':obj({'scope':{'const':'HOST'},'status':enum('KNOWN','UNKNOWN'),
                      'total_bytes':nullable(COUNT),'available_bytes':nullable(COUNT)}),
        'disk':obj({'scope':{'const':'STATE_FILESYSTEM'},'status':enum('KNOWN','UNKNOWN'),
                    'total_bytes':nullable(COUNT),'available_bytes':nullable(COUNT)})}),
    'gpu':obj({'scope':{'const':'GPU'},'status':{'const':'UNKNOWN'},
               'utilization_percent':{'type':'null'},'memory_used_bytes':{'type':'null'}}),
    'workers':{'type':'array','maxItems':32,'items':obj({'execution_id':OPAQUE_ID,
               'process':RESOURCE_PROCESS,'heartbeat':RESOURCE_HEARTBEAT})},'workers_truncated':{'type':'boolean'}})


@lru_cache(maxsize=1)
def schemas():
    root = Path(__file__).with_name("hybrid_schemas")
    values = {name: json.loads((root / f"{name}.schema.json").read_text())
              for name in ("event", "command", "command_v1_1", "goal", "goal_v1_1", "payloads")}
    return values


@lru_cache(maxsize=1)
def registry():
    return Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas().values())


def validate_schema(schema, value):
    try:
        Draft202012Validator(schema, registry=registry(), format_checker=FormatChecker()).validate(value)
        json.dumps(value, allow_nan=False)
    except (ValidationError, ValueError, TypeError) as exc:
        # ValidationError string embeds input values; never expose secrets in errors.
        path = ".".join(map(str, exc.absolute_path)) if isinstance(exc, ValidationError) else "value"
        raise ProtocolError(f"invalid contract field: {path or 'root'}") from exc


def validate(name, value):
    schema = OBJECTS.get(name)
    if schema is None:
        schema = schemas().get(name)
    if schema is None:
        raise ProtocolError("unknown contract", "UNSUPPORTED_CAPABILITY")
    validate_schema(schema, value)
    if name == 'Telemetry':
        if value['sample_id'] != value['sampler_epoch']+':'+str(value['sample_seq']):
            raise ProtocolError('invalid telemetry sample identity')
        measures = [(value['host']['cpu'],('utilization_percent',)),
                    (value['host']['memory'],('total_bytes','available_bytes')),
                    (value['host']['disk'],('total_bytes','available_bytes'))]
        measures += [(w['process'],('cpu_seconds','rss_bytes')) for w in value['workers']]
        measures += [(w['heartbeat'],('counter','age_seconds')) for w in value['workers']]
        for metric,keys in measures:
            if any((metric['status']=='UNKNOWN') != (metric[key] is None) for key in keys):
                raise ProtocolError('inconsistent telemetry availability')
            if 'total_bytes' in keys and metric['status']=='KNOWN' and metric['available_bytes']>metric['total_bytes']:
                raise ProtocolError('invalid telemetry availability')
        for worker in value['workers']:
            h = worker['heartbeat']
            if h['status']!='UNKNOWN' and (h['counter']<1 or (h['status']=='FRESH') != (h['age_seconds']<=15)):
                raise ProtocolError('invalid heartbeat freshness')
    if name == "Budget":
        if value["unknown_exposure"] > value["reserved"] or value["available"] != max(0, value["limit"] - value["consumed"] - value["reserved"]):
            raise ProtocolError("invalid budget conservation")
        if value["overrun"] != max(0, value["consumed"] + value["reserved"] - value["limit"]):
            raise ProtocolError("invalid budget overrun")
    if name == "Usage" and value["cached_tokens"] is not None and value["input_tokens"] is not None and value["cached_tokens"] > value["input_tokens"]:
        raise ProtocolError("cached tokens exceed total input")
    if name == "Usage" and value["status"] == "KNOWN" and any(value[k] is None for k in ("input_tokens", "output_tokens", "cached_tokens")):
        raise ProtocolError("known usage requires complete counts")
    if name == "Snapshot":
        parse_cursor(value["cursor"],value["store_epoch"])
        if not value["server_time"].endswith("Z"): raise ProtocolError("snapshot time must be UTC")
    if name == "Evidence" and value["verdict"] == "PASS" and value["reviewer_session_id"] == value["implementer_session_id"]:
        raise ProtocolError("implementer cannot be independent reviewer")
    if name == "GoalContract":
        from .store import sha
        if value["hash"] != "sha256:"+sha(value["proposal"]): raise ProtocolError("contract hash mismatch")
        if value["id"] != value["proposal"]["goal_id"] or value["version"] != value["proposal"]["contract_version"]:
            raise ProtocolError("contract identity mismatch")
        if value["state"] == "COMPLETED" and (value["approval_id"] is None or value["outcome"] is None):
            raise ProtocolError("completion requires approval and explicit outcome")
    if name == "Lease" and value["role"] != "engineer" and value["writable_paths"]:
        raise ProtocolError("only engineer lease can request write access")


def payload_registry():
    values = dict(schemas()["payloads"]["$defs"])
    values.update({
        "legacy.observed": obj({"source_event_id": ID, "source_event_type": TEXT,
                                "source_state_version": COUNT, "paused": {"type": "boolean"},
                                "enabled": {"type": "boolean"}, "upsert": array(PUBLIC_OBJECT),
                                "counters": array(COUNTER, 1000),
                                "removed": array(obj({"kind": enum(*PUBLIC_KINDS), "id": ID}))}),
        "lease.created": OBJECTS["Lease"],
        "usage.observed": OBJECTS["Usage"],
        "command.state_changed": OBJECTS["CommandReceipt"],
        "execution.state_changed": obj({"attempt_id": ID, "state": enum(*ATTEMPT_STATES), "reason": TEXT}),
        "result.submitted": obj({"attempt_id": ID, "session_id": ID, "result_hash": HASH}),
        "result.rejected": obj({"attempt_id": ID, "session_id": ID, "code": enum(*ERROR_CODES), "reason": TEXT}),
        "approval.state_changed": obj({"proposal_hash": HASH, "state": enum("PENDING", "APPROVED", "REJECTED", "REVOKED"), "principal_id": nullable(ID), "reason": TEXT}),
        "experiment.assessed": obj({"experiment_id": ID, "execution_status": enum(*ATTEMPT_STATES),
                                    "scientific_validity": enum("UNASSESSED", "VALID", "INVALID", "INCONCLUSIVE"),
                                    "hypothesis_outcome": enum("UNASSESSED", "SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE"),
                                    "evidence_ids": array(ID), "reason": TEXT}),
    })
    return values


def validate_event(event, *, data_mode=None):
    validate("event", event)
    schema = payload_registry().get(event["type"])
    if schema is None:
        raise ProtocolError("unknown critical event type", "UNSUPPORTED_CAPABILITY")
    validate_schema(schema, event["payload"])
    expected_kind = {"goal": "goal", "task": "task", "execution": "execution", "result": "execution",
                     "evidence": "evidence", "budget": "budget", "lease": "execution", "usage": "budget",
                     "command": "command", "approval": "approval", "experiment": "experiment", "legacy": "control"}[event["type"].split(".")[0]]
    if event["entity"]["kind"] != expected_kind: raise ProtocolError("event entity kind mismatch")
    if event["type"] == "usage.observed": validate("Usage",event["payload"])
    if data_mode is not None and event["data_mode"] != data_mode:
        raise ProtocolError("event data mode differs from instance")
    for field in ("occurred_at", "recorded_at"):
        if not event[field].endswith("Z"):
            raise ProtocolError("event time must be UTC")
    if event["type"] == "budget.updated":
        value = event["payload"]
        validate("Budget", {**{k: v for k, v in value.items() if k != "source_ref"},
                             "overrun": max(0, value["consumed"] + value["reserved"] - value["limit"])})


def parse_cursor(cursor, epoch):
    if not isinstance(cursor, str) or ":" not in cursor:
        raise ProtocolError("invalid event cursor", "RESYNC_REQUIRED")
    supplied, seq = cursor.rsplit(":", 1)
    if supplied != epoch or re.fullmatch(r"0|[1-9][0-9]{0,18}", seq) is None:
        raise ProtocolError("stale epoch or invalid cursor", "RESYNC_REQUIRED")
    parsed = int(seq)
    if parsed > 2**63-1: raise ProtocolError("cursor exceeds storage range", "RESYNC_REQUIRED")
    return parsed

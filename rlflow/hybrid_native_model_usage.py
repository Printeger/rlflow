"""Closed native CLI usage publication format; validation is NOT issuance.

Only the original Source's independently registered publication can enter the
live writer. Packet/usage JSON, hashes and these pure validators grant nothing.
Unknown or failed observations cannot be substituted for a complete receipt.
"""
from .hybrid_protocol import HASH,ID,obj,validate_schema
from .hybrid_goals import digest
from .hybrid_budget import zero
from .store import Conflict

COUNT={'type':'integer','minimum':0,'maximum':2**63-1}
PROCESS=obj({'pid':{**COUNT,'minimum':1},'pgid':{**COUNT,'minimum':1},
    'starttime':{'type':'string','pattern':'^[0-9]{1,20}$'},
    'boot_id':{'type':'string','pattern':'^[0-9a-f-]{36}$'}})
PUBLICATION=obj({'profile':{'const':'ORIGINAL_NATIVE_CLI_USAGE_V1'},
    'source_id':ID,'lease_id':ID,'task_id':ID,'attempt_id':ID,'grant_id':ID,
    'grant_sha256':HASH,'producer':PROCESS,'nonce':{'type':'string','pattern':'^[0-9a-f]{32}$'},
    'workspace_id':{'type':'string','pattern':'^[0-9a-f-]{36}$'},
    'packet_sha256':HASH,'output_schema_sha256':HASH,'candidate_sha256':HASH,
    'stream_sha256':HASH,'output_sha256':HASH,
    'stream_bytes':{**COUNT,'minimum':1,'maximum':1024**2},
    'ready_sha256':HASH,'started_ack_sha256':HASH,'terminal_proof_sha256':HASH,
    'producer_exit_code':{'const':0},
    'usage':obj({'input_tokens':COUNT,'output_tokens':COUNT,'cached_tokens':COUNT,
        'complete':{'const':True}})})


def validate_publication(value,runtime):
    """Historical bindings only; live Source provenance is checked separately."""
    validate_schema(PUBLICATION,value)
    origin=runtime['origin'];binding=origin['native_model']
    if (runtime['phase']!='FIXTURE_SCOPE_STOPPED' or
            not runtime['native_model_handoff_attempted'] or
            runtime['producer'] is None or runtime['started_ack_sha256'] is None or
            runtime['terminal_proof_sha256'] is None or
            any(value[key]!=origin[key] for key in ('lease_id','task_id','attempt_id','nonce')) or
            value['producer']!=runtime['producer'] or value['grant_id']!=binding['grant_id'] or
            value['grant_sha256']!=digest(binding) or
            any(value[key]!=binding[key] for key in
                ('workspace_id','packet_sha256','output_schema_sha256','candidate_sha256')) or
            value['started_ack_sha256']!=runtime['started_ack_sha256'] or
            value['terminal_proof_sha256']!=runtime['terminal_proof_sha256'] or
            value['usage']['cached_tokens']>value['usage']['input_tokens']):
        raise Conflict('original native usage publication lineage differs')
    return value


def consumption(value,runtime):
    """Complete original CLI counts, not provider request count or money cost."""
    validate_publication(value,runtime)
    return {**zero(),'model_sessions':1,
        'model_input_tokens':value['usage']['input_tokens'],
        'model_output_tokens':value['usage']['output_tokens'],
        'wall_seconds':runtime['wall_seconds']}

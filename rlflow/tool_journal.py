"""Trusted bounded tool discovery, not command authority or public ingestion.

REGISTER is durable before cpu_exec can be invoked. A registered command may
never have launched; consumers must inspect its known path without reexecution.
No directory enumeration, command/output text, or inferred start time.
"""
from __future__ import annotations
import contextlib
import fcntl
import hashlib
import json
import os
import re
import stat

NAME = 'tool-registers.jsonl'
RECORD_LIMIT = 4096
JOURNAL_LIMIT = 64 * 1024 * 1024
ZERO = '0' * 64


class JournalError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def hash_valid(value):
    return isinstance(value,str) and re.fullmatch(r'[0-9a-f]{64}',value) is not None


def integer(value):
    return type(value) is int and 0 <= value < 2**63


def context_valid(value):
    return (isinstance(value,dict) and set(value)=={'schema_version','session','generation','request_sha256','candidate_sha256'}
            and value['schema_version']=='1.0'
            and all(isinstance(value[k],str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}',value[k]) for k in ('session','generation'))
            and all(hash_valid(value[k]) for k in ('request_sha256','candidate_sha256')))


def validate(row,context):
    keys = {'schema_version','kind','epoch','ordinal','previous_sha256','command_digest','intent_sha256',
            'context','launch_witness','record_sha256'}
    if (not isinstance(row,dict) or set(row)!=keys or row['schema_version']!='1.0' or row['kind']!='CPU_REGISTER'
            or not context_valid(context) or row['context']!=context or row['epoch']!=digest(context)
            or not integer(row['ordinal']) or row['ordinal']<1
            or not all(hash_valid(row[k]) for k in ('previous_sha256','command_digest','intent_sha256','record_sha256'))):
        raise JournalError('Invalid tool registration')
    witness = row['launch_witness']
    if witness is not None and (not isinstance(witness,dict) or set(witness)!={'release_sha256','model_release_sha256','ack_sha256'}
                                or not all(hash_valid(value) for value in witness.values())):
        raise JournalError('Invalid registration launch witness')
    if row['record_sha256'] != digest({k:v for k,v in row.items() if k!='record_sha256'}):
        raise JournalError('Tool registration digest mismatch')
    return row


def _read_json(directory,name):
    fd = os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
    with os.fdopen(fd,'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size>65536:raise JournalError('Invalid launch witness storage')
        raw = stream.read(65537)
        if len(raw)>65536:raise JournalError('Launch witness exceeds bound')
        value = json.loads(raw)
        if not isinstance(value,dict):raise JournalError('Invalid launch witness')
        return value


def capture_launch(directory,context):
    """Capture existing facts NOW; missing/malformed evidence stays unverified.

    This is not full release validation. The core collector must also validate
    DB session/request/permissions and exact startup proof, including these hashes.
    A later release must never be used to upgrade a null registration witness.
    """
    if directory is None:return None
    try:
        fd = os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        with contextlib.ExitStack() as stack:
            stack.callback(os.close,fd)
            release = _read_json(fd,'release')
            model = _read_json(fd,'model-release.json')
            ack = _read_json(fd,'launch-start_ack.json')
        binding = ack.get('binding')
        if (release.get('session')!=context['session'] or release.get('generation')!=context['generation']
                or release.get('request_sha256')!=context['request_sha256'] or release.get('candidate_sha256')!=context['candidate_sha256']
                or model.get('session')!=context['session'] or model.get('generation')!=context['generation']
                or not isinstance(model.get('identity'),dict) or not isinstance(binding,dict)
                or binding!={'session':context['session'],'generation':context['generation'],'identity':model['identity']}
                or ack.get('phase')!='START_ACK' or ack.get('binding_sha256')!=digest(binding)):
            return None
        return {'release_sha256':digest(release),'model_release_sha256':digest(model),'ack_sha256':digest(ack)}
    except (OSError,ValueError,TypeError,KeyError,RecursionError):
        return None


def _regular(stream):
    info = os.fstat(stream.fileno())
    if not stat.S_ISREG(info.st_mode) or info.st_size>JOURNAL_LIMIT:
        raise JournalError('Invalid tool journal storage')
    return info


def _ending_record(stream,offset,context):
    """Only one bounded checkpoint record, not a historical prefix scan."""
    start = max(0,offset-RECORD_LIMIT-1)
    stream.seek(start)
    raw = stream.read(offset-start)
    if not raw.endswith(b'\n'):raise JournalError('Incomplete tool journal tail')
    parts = raw[:-1].split(b'\n')
    last = parts[-1]
    if len(last)+1>RECORD_LIMIT or start and len(parts)==1:
        raise JournalError('Tool journal record exceeds bound')
    return validate(json.loads(last),context)


def register(config,intent,command_digest):
    """Called after durable intent, BEFORE any command invocation.

    Complete existing records are never rewritten. An incomplete tail rejects
    new execution; repair requires a separate trusted recovery operation.
    """
    context = config.get('tool_context')
    if not context_valid(context) or not hash_valid(command_digest):raise JournalError('Invalid registration context')
    directory = os.open(os.path.dirname(config['audit']),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        fd = os.open(NAME,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600,dir_fd=directory)
        with os.fdopen(fd,'r+b') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX)
            info = _regular(stream)
            last = _ending_record(stream,info.st_size,context) if info.st_size else None
            row = {'schema_version':'1.0','kind':'CPU_REGISTER','epoch':digest(context),
                   'ordinal':last['ordinal']+1 if last else 1,'previous_sha256':last['record_sha256'] if last else ZERO,
                   'command_digest':command_digest,'intent_sha256':digest(intent),'context':context,
                   'launch_witness':capture_launch(config.get('tool_launch_directory'),context)}
            row['record_sha256'] = digest(row)
            validate(row,context)
            raw = json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n'
            if len(raw)>RECORD_LIMIT or info.st_size+len(raw)>JOURNAL_LIMIT:raise JournalError('Tool journal capacity exceeded')
            stream.seek(0,os.SEEK_END);stream.write(raw);stream.flush();os.fsync(stream.fileno())
            os.fsync(directory)
            return row
    finally:os.close(directory)


def read_page(directory,context,cursor=None,*,limit=32):
    """Anchored fd in, <=64 bounded records out, with durable offset witness.

    Caller persists cursor only with receipt/pending ingestion in its transaction.
    A partial final record leaves its offset unconsumed; never resets on damage.
    """
    if not context_valid(context) or type(limit) is not int or not 1<=limit<=64:raise JournalError('Invalid journal page request')
    fd = os.open(NAME,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
    with os.fdopen(fd,'rb') as stream:
        info = _regular(stream)
        epoch = digest(context)
        at = {'epoch':epoch,'device':info.st_dev,'inode':info.st_ino,'offset':0,'ordinal':0,'record_sha256':ZERO}
        if cursor is not None:
            if (not isinstance(cursor,dict) or set(cursor)!=set(at) or cursor['epoch']!=epoch
                    or any(not integer(cursor[k]) for k in ('device','inode','offset','ordinal'))
                    or not hash_valid(cursor['record_sha256']) or cursor['device']!=info.st_dev or cursor['inode']!=info.st_ino
                    or cursor['offset']>info.st_size):raise JournalError('Tool journal source changed')
            at = dict(cursor)
            if at['offset']:
                previous = _ending_record(stream,at['offset'],context)
                if previous['ordinal']!=at['ordinal'] or previous['record_sha256']!=at['record_sha256']:
                    raise JournalError('Tool journal checkpoint changed')
            elif at['ordinal']!=0 or at['record_sha256']!=ZERO:raise JournalError('Invalid initial journal checkpoint')
        stream.seek(at['offset']);rows = [];partial = False
        for _ in range(limit):
            raw = stream.readline(RECORD_LIMIT+1)
            if not raw:break
            if len(raw)>RECORD_LIMIT:raise JournalError('Tool journal record exceeds bound')
            if not raw.endswith(b'\n'):partial = True;break
            row = validate(json.loads(raw),context)
            if row['ordinal']!=at['ordinal']+1 or row['previous_sha256']!=at['record_sha256']:
                raise JournalError('Tool journal history gap')
            rows.append(row)
            at.update(offset=stream.tell(),ordinal=row['ordinal'],record_sha256=row['record_sha256'])
        return {'items':rows,'cursor':at,'incomplete_tail':partial,'has_more':at['offset']<info.st_size}

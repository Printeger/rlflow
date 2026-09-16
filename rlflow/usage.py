"""Append-only local usage observations. Estimates are never verified invoices."""
import hashlib
import json
from pathlib import Path
from decimal import Decimal
from .store import Conflict, sha

FIELDS={'input_tokens':'input_tokens','output_tokens':'output_tokens','cached_tokens':'cached_input_tokens'}


def empty(model=None, semantics='cumulative'):
    if semantics not in {'per_turn','cumulative'}:raise Conflict('unverified usage semantics')
    return {'input_tokens':None,'output_tokens':None,'cached_tokens':None,'model':model,
            'usage_source':'cli-jsonl/2','complete':False,'estimated_cost':None,
            'actual_cost_status':'UNKNOWN','actual_cost':None,'semantics':semantics,
            'status':'INCOMPLETE','offset':0,'event_position':0,'observations':{},'turn':0,'incomplete_turns':0,
            'generated':False,'malformed_lines':0,'failed':False,'thread_id':'unknown'}


def estimate(usage, price):
    result={'estimated_cost':None,'actual_cost_status':'UNKNOWN','actual_cost':None}
    if price is None or price.get('model')!=usage.get('model'):return result
    required={'model','date','currency','version','input_per_million','cached_per_million','output_per_million'}
    if set(price)!=required:raise Conflict('price table must bind model/date/currency/version')
    if any(not isinstance(price[k],str) or not price[k] for k in ('model','date','currency','version')):raise Conflict('invalid price identity')
    import datetime
    try:datetime.date.fromisoformat(price['date'])
    except ValueError as exc:raise Conflict('invalid price date') from exc
    if len(price['currency'])!=3 or not price['currency'].isupper():raise Conflict('invalid price currency')
    if any(usage.get(k) is None for k in FIELDS):return result
    counts={k:usage[k] for k in FIELDS}
    if counts['cached_tokens']>counts['input_tokens']:
        if not usage['complete']:return result
        raise Conflict('cached tokens exceed input')
    rates=[Decimal(str(price[k])) for k in ('input_per_million','cached_per_million','output_per_million')]
    if any(not r.is_finite() or r<0 for r in rates):raise Conflict('invalid price rate')
    cost=((counts['input_tokens']-counts['cached_tokens'])*rates[0]+counts['cached_tokens']*rates[1]+counts['output_tokens']*rates[2])/Decimal(1000000)
    result.update(estimated_cost=str(cost),price_identity=sha(price),currency=price['currency'],estimate_is_lower_bound=not usage['complete'])
    return result


def read(path, previous=None, *, model=None, semantics='cumulative', price=None):
    """Read only complete appended lines; retain an unfinished line for the next poll."""
    result=json.loads(json.dumps(previous)) if previous else empty(model,semantics)
    if result['model']!=model or result['semantics']!=semantics:raise Conflict('usage profile changed')
    path=Path(path)
    if not path.exists():return result
    with path.open('rb') as source:
        import os
        stat=os.fstat(source.fileno());identity=[stat.st_dev,stat.st_ino]
        if result.get('file_identity',identity)!=identity or stat.st_size<result['offset']:
            raise Conflict('usage log replaced or truncated; reconcile explicitly')
        if stat.st_size==result['offset'] and result.get('mtime_ns',stat.st_mtime_ns)!=stat.st_mtime_ns:
            raise Conflict('usage log changed without append')
        result['file_identity']=identity;source.seek(result['offset'])
        while True:
            start=source.tell();line=source.readline(1024*1024+1)
            if not line:break
            if len(line)>1024*1024:raise Conflict('usage JSONL line exceeds bounded parser limit')
            if not line.endswith(b'\n'):break
            result['offset']=source.tell();result['event_position']+=1
            try:event=json.loads(line)
            except ValueError:result['malformed_lines']+=1;continue
            if not isinstance(event,dict):result['malformed_lines']+=1;continue
            kind=event.get('type')
            if kind=='thread.started':result['thread_id']=event.get('thread_id','unknown')
            if kind=='turn.started':result['turn']+=1;result['incomplete_turns']+=1
            if kind=='turn.failed':result['failed']=True
            if kind=='item.completed' and isinstance(event.get('item'),dict) and event['item'].get('type') in {'agent_message','reasoning','command_execution','mcp_tool_call'}:
                result['generated']=True
            raw=event.get('usage')
            if not isinstance(raw,dict) or kind!='turn.completed':continue
            # A stable backend turn/event ID deduplicates retransmissions. Otherwise
            # event position identifies observations; equal counts can be real turns.
            event_id=result['thread_id']+':'+str(event.get('turn_id') or event.get('event_id') or 'turn:'+str(result['turn'])+':'+str(start))
            counts={field:raw.get(source_name,raw.get(field)) for field,source_name in FIELDS.items()}
            if any(v is not None and (type(v) is not int or v<0) for v in counts.values()):
                result['malformed_lines']+=1;continue
            observation={'thread_id':result['thread_id'],'counts':counts,'line_sha256':hashlib.sha256(line).hexdigest(),'offset':start,'event_position':result['event_position']}
            old=result['observations'].get(event_id)
            if old and old['counts']!=counts:raise Conflict('usage event identity changed')
            if old:continue
            result['observations'][event_id]=observation
            if kind=='turn.completed':result['incomplete_turns']=max(0,result['incomplete_turns']-1)
        result['mtime_ns']=stat.st_mtime_ns
    for field in FIELDS:
        groups={}
        for row in result['observations'].values():
            value=row['counts'][field]
            if value is not None:groups.setdefault(row['thread_id'],[]).append(value)
        result[field]=sum(sum(v) if semantics=='per_turn' else max(v) for v in groups.values()) if groups else None
    final_by_thread={}
    for row in result['observations'].values():final_by_thread[row['thread_id']]=row
    completeness_rows=final_by_thread.values() if semantics=='cumulative' else result['observations'].values()
    result['complete']=bool(result['observations']) and result['incomplete_turns']==0 and result['malformed_lines']==0 and not result['failed'] and all(all(v is not None for v in r['counts'].values()) for r in completeness_rows)
    result['status']='COMPLETE' if result['complete'] else 'INCOMPLETE'
    result.update(estimate(result,price))
    return result


def reconcile(store, session_id, *, semantics='cumulative', price=None):
    session=store.get('sessions',session_id)
    if session is None:raise Conflict('unknown usage session')
    previous=store.get('usage',session_id)
    observed=read(Path(session['directory'])/'events.jsonl',previous,
                  model=session.get('compute',{}).get('model'),semantics=semantics,price=price)
    if observed==previous:return observed
    def settle(s):
        s.setdefault('usage',{})[session_id]=observed
        return {'known_lower_bound_delta':{field:(observed[field]-previous[field] if (previous or {}).get(field) is not None else observed[field]) if observed[field] is not None else None for field in FIELDS}}
    store.transact_objects('USAGE_OBSERVED',session_id+':usage:'+sha(observed),[('usage',session_id)],settle,object_id=session_id)
    return observed


def validate_policy(policy):
    required={'token_limit','cost_limit','currency','per_call_estimate','price_table','strict_cost_cap'}
    if not isinstance(policy,dict) or set(policy)!=required:raise Conflict('invalid usage admission policy')
    if policy['strict_cost_cap'] is not False:raise Conflict('backend cannot enforce a strict session cost cap')
    if policy['token_limit'] is not None and (type(policy['token_limit']) is not int or policy['token_limit']<=0):raise Conflict('invalid token admission limit')
    if policy['cost_limit'] is not None:
        amount=Decimal(str(policy['cost_limit']))
        if not amount.is_finite() or amount<=0:raise Conflict('invalid estimated cost limit')
    expected=policy['per_call_estimate']
    if not isinstance(expected,dict) or set(expected)!=set(FIELDS) or any(type(v) is not int or v<0 for v in expected.values()):raise Conflict('complete per-call token estimate required')
    if expected['cached_tokens']>expected['input_tokens']:raise Conflict('invalid cached estimate')
    prices=policy['price_table']
    if not isinstance(prices,list):raise Conflict('versioned price records required')
    for price in prices:
        if not isinstance(price,dict):raise Conflict('invalid price record')
        estimate({**expected,'model':price.get('model'),'complete':True},price)
        if price['currency']!=policy['currency']:raise Conflict('mixed price currencies')
    return policy


def admit(state,stage,model):
    policy=stage.get('usage_policy')
    if policy is None:return None
    validate_policy(policy);tokens=0;cost=Decimal(0);unknown=[]
    for sid,session in state['sessions'].items():
        if session['stage_id']!=stage['id']:continue
        observed=state.get('usage',{}).get(sid)
        if session.get('model_accounting')=='NOT_STARTED':continue
        if observed is None or not observed['complete']:
            unknown.append(sid);continue
        tokens+=observed['input_tokens']+observed['output_tokens']
        if observed['estimated_cost'] is None and policy['cost_limit'] is not None:unknown.append(sid)
        elif observed['estimated_cost'] is not None:cost+=Decimal(observed['estimated_cost'])
    if unknown and (policy['token_limit'] is not None or policy['cost_limit'] is not None):
        raise Conflict('usage incomplete; capped admission requires reconciliation: '+','.join(unknown))
    expected={**policy['per_call_estimate'],'model':model,'complete':True}
    prices=[p for p in policy['price_table'] if p['model']==model]
    if len(prices)>1:raise Conflict('ambiguous price version for model')
    proposed=estimate(expected,prices[0] if prices else None)
    if policy['token_limit'] is not None and tokens+expected['input_tokens']+expected['output_tokens']>policy['token_limit']:
        raise Conflict('estimated token admission budget exhausted')
    if policy['cost_limit'] is not None:
        if proposed['estimated_cost'] is None:raise Conflict('unknown model price prevents cost admission')
        if cost+Decimal(proposed['estimated_cost'])>Decimal(str(policy['cost_limit'])):raise Conflict('estimated cost admission budget exhausted')
    return {'tokens':expected,'estimate':proposed,'price':prices[0] if prices else None,'hard_cost_cap':False}

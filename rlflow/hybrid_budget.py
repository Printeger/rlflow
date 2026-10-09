"""Pure cumulative budget arithmetic, never usage evidence or release authority.

The protected ledger service must supply original approved limits and actual
reservation/usage lifecycle proofs. These helpers perform no IO and cannot
turn a requested token estimate into an enforceable backend upper bound.
"""
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext

from .hybrid_protocol import ID, obj, enum, validate_schema
from .store import Conflict, sha


DIMENSIONS=('model_sessions','model_input_tokens','model_output_tokens',
            'gpu_device_seconds','experiment_starts','experiment_retries','wall_seconds')
MAXIMUM=2**63-1
SCOPE=obj({'project_id':ID,'data_mode':enum('live','fixture'),'goal_ref':ID})


def zero():
    return dict.fromkeys(DIMENSIONS,0)


def vector(value):
    if (type(value) is not dict or set(value)!=set(DIMENSIONS) or
            any(type(n) is not int or not 0<=n<=MAXIMUM for n in value.values())):
        raise Conflict('closed actual nonnegative int64 budget vector required')
    return dict(value)


def add(left,right):
    left,right=vector(left),vector(right)
    return vector({name:left[name]+right[name] for name in DIMENSIONS})


def subtract(left,right):
    left,right=vector(left),vector(right)
    return vector({name:left[name]-right[name] for name in DIMENSIONS})


def account_key(scope):
    """Stable Goal identity: revisions, epochs and adapters cannot reset it."""
    validate_schema(SCOPE,scope)
    return 'budget_goal_'+sha([scope['project_id'],scope['data_mode'],scope['goal_ref']])


def balances(limits,consumed,reserved,unknown):
    limits,consumed,reserved,unknown=map(vector,(limits,consumed,reserved,unknown))
    exposure=add(consumed,reserved)
    if any(unknown[name]>reserved[name] for name in DIMENSIONS):
        raise Conflict('unknown exposure must be a subset of reserved budget')
    return {name:{'limit':limits[name],'consumed':consumed[name],
        'reserved':reserved[name],'unknown_exposure':unknown[name],
        'available':max(0,limits[name]-consumed[name]-reserved[name]),
        'overrun':max(0,exposure[name]-limits[name])}
        for name in DIMENSIONS}


def validate_balances(value):
    fields={'limit','consumed','reserved','unknown_exposure','available','overrun'}
    if (type(value) is not dict or set(value)!=set(DIMENSIONS) or
            any(type(row) is not dict or set(row)!=fields for row in value.values())):
        raise Conflict('closed budget balances required')
    base={field:vector({name:value[name][field] for name in DIMENSIONS})
          for field in ('limit','consumed','reserved','unknown_exposure')}
    expected=balances(base['limit'],base['consumed'],base['reserved'],base['unknown_exposure'])
    if (any(type(row[n]) is not int for row in value.values() for n in fields) or
            value!=expected):raise Conflict('budget conservation differs')
    return base


def finalization_floor(limits,fraction):
    """Approved planning policy only; this floor is not money already spent."""
    limits=vector(limits)
    if type(fraction) not in (int,float):raise Conflict('actual finalization fraction required')
    try:portion=Decimal(str(fraction))
    except InvalidOperation:raise Conflict('invalid finalization fraction') from None
    if not portion.is_finite() or not Decimal(0)<=portion<=Decimal('0.8'):
        raise Conflict('invalid finalization fraction')
    with localcontext() as context:
        context.prec=80  # Exact int64 times Python's finite decimal float spelling.
        return {name:int((Decimal(limits[name])*portion).to_integral_value(rounding=ROUND_CEILING))
                for name in DIMENSIONS}


def reserve(value,amount,*,purpose,fraction):
    """Pure proposed update; caller must separately prove approved live scope."""
    base=validate_balances(value);amount=vector(amount)
    if purpose not in ('EXECUTION','FINAL_VALIDATION','RECOVERY'):
        raise Conflict('explicit approved reservation purpose required')
    if not any(amount.values()):raise Conflict('empty budget reservation refused')
    floor=finalization_floor(base['limit'],fraction)
    if any(value[name]['overrun'] for name in DIMENSIONS):
        raise Conflict('existing overrun stops new budget reservation')
    if any(amount[name]>max(0,value[name]['available']-(floor[name] if purpose=='EXECUTION' else 0))
           for name in DIMENSIONS):
        raise Conflict('budget unavailable or finalization planning reserve protected')
    return balances(base['limit'],base['consumed'],add(base['reserved'],amount),base['unknown_exposure'])


def project_exposure(accounts):
    """Observed aggregate, not an authorized project cap or host session pool."""
    total={name:zero() for name in ('consumed','reserved','unknown_exposure')}
    for account in accounts:
        base=validate_balances(account)
        for field in total:total[field]=add(total[field],base[field])
    return total


def rebase(value,limits):
    """New approved limits change policy, not prior cumulative exposure."""
    base=validate_balances(value)
    return balances(vector(limits),base['consumed'],base['reserved'],base['unknown_exposure'])


def mark_unknown(value,amount):
    """Pure HELD->UNKNOWN math; service must prove the exact prior reservation."""
    base=validate_balances(value);amount=vector(amount)
    return balances(base['limit'],base['consumed'],base['reserved'],add(base['unknown_exposure'],amount))


def cancel_held(value,amount):
    """Math only, not proof of no startup. Requires a core cancellation tombstone.

    Never use absence of a receipt/release row or caller NOT_STARTED to invoke
    this. An actual owner must prove PRE_RUNTIME HELD and atomically close every
    future register/release route for that exact reservation.
    """
    base=validate_balances(value);amount=vector(amount)
    return balances(base['limit'],base['consumed'],subtract(base['reserved'],amount),base['unknown_exposure'])


def settle_known(value,amount,usage,*,prior_status):
    """Pure complete-usage math, never a caller JSON settlement API.

    A future actual UsageOwner must prove complete scoped usage and deduplicate
    cumulative/parent-child observations. Missing usage must instead retain the
    entire unresolved reservation. Used work remains consumed even if failed.
    """
    if prior_status not in ('HELD','UNKNOWN'):raise Conflict('unsettled reservation status required')
    base=validate_balances(value);amount,usage=vector(amount),vector(usage)
    unknown=subtract(base['unknown_exposure'],amount) if prior_status=='UNKNOWN' else base['unknown_exposure']
    return balances(base['limit'],add(base['consumed'],usage),subtract(base['reserved'],amount),unknown)

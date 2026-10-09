"""Independent bounded arithmetic implementation; NOT an independent Reviewer.

Stage one receives only raw points and the frozen specification, never producer
metrics, appraisal, interpretation or a model conversation. Stage two compares
the derived values. This grants no execution/condition/Goal authority.
"""
import hashlib
import math
from pathlib import Path
from .hybrid_fixture_materials import _read_bounded

from .store import canonical,Conflict
from .hybrid_goals import digest

VERSION='FIXED_PI_RAW_COLD_CHECK_V1'
SPEC={'generator':'LCG32_TOP16_V1','seeds':[7,11,19],'samples_per_seed':128,
      'coordinate_denominator':65536,'baseline':3,'reference':'math.pi',
      'comparison':'MEAN_ABSOLUTE_ERROR','hypothesis':'estimator_error_below_baseline'}


def implementation_hash():
    return 'sha256:'+hashlib.sha256(_read_bounded(Path(__file__),16384)).hexdigest()


def derive(spec,raw):
    """Cold exact input reconstruction and arithmetic; no existing conclusions."""
    if canonical(spec)!=canonical(SPEC) or len(canonical(raw))>16384:
        raise Conflict('cold verifier fixed bounded specification required')
    if type(raw) is not list or len(raw)!=3:
        raise Conflict('cold verifier complete three-seed raw samples required')
    counts=[]
    for index,row in enumerate(raw):
        if (type(row) is not dict or set(row)!={'seed','points'} or type(row['seed']) is not int or
                row['seed']!=SPEC['seeds'][index] or type(row['points']) is not list or len(row['points'])!=128):
            raise Conflict('cold verifier original seed/sample domain differs')
        generator=row['seed'];inside=0
        for point in row['points']:
            if type(point) is not list or len(point)!=2 or any(type(n) is not int or not 0<=n<65536 for n in point):
                raise Conflict('cold verifier bounded integer coordinates required')
            # Independently spelled recurrence/modulus, not trial.inputs().
            expected=[]
            for _ in range(2):
                generator=(generator*1664525+1013904223)%(2**32)
                expected.append(generator//(2**16))
            if point!=expected:raise Conflict('cold verifier raw generator sequence differs')
            if point[0]**2+point[1]**2<65536**2:inside+=1
        counts.append(inside)
    estimates=[n/32 for n in counts]
    error=math.fsum([abs(number-math.pi) for number in estimates])/3
    baseline_error=abs(3-math.pi)
    return {'raw_sha256':digest(raw),'spec_sha256':digest(spec),'inside_counts':counts,
            'estimates':estimates,'mean_absolute_error':error,'baseline':3,
            'baseline_absolute_error':baseline_error,'hypothesis_supported':error<baseline_error}


def verify(result,*,implementation=None):
    """Derive first; compare second. Source corruption is not a negative result."""
    fingerprint=implementation_hash() if implementation is None else implementation
    if result is None:
        return {'verifier_version':VERSION,'verifier_sha256':fingerprint,
                'status':'UNAVAILABLE','derived':None,'source_sha256':None,
                'next_action':'NO_AUTOMATIC_RETRY','independent_review_status':'NOT_PERFORMED',
                'condition_coverage':[],'goal_completed':False,'dispatch_enabled':False}
    derived=derive(SPEC,result['raw_samples'])
    expected={**derived,'raw_sha256':result['input_sha256'],'spec_sha256':digest(SPEC)}
    expected.update({k:result[k] for k in ('inside_counts','estimates','mean_absolute_error',
                    'baseline','baseline_absolute_error','hypothesis_supported')})
    if canonical(derived)!=canonical(expected):raise Conflict('cold verifier derived metrics differ from original result')
    return {'verifier_version':VERSION,'verifier_sha256':fingerprint,
            'status':'MACHINE_VERIFIED','derived':derived,'source_sha256':result['source_sha256'],
            'next_action':'REQUEST_INDEPENDENT_REVIEW','independent_review_status':'NOT_PERFORMED',
            'condition_coverage':[],'goal_completed':False,'dispatch_enabled':False}

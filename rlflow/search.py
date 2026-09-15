"""Expand explicitly approved numeric parameter ranges into immutable trials."""
from copy import deepcopy
from decimal import Decimal,InvalidOperation
from itertools import product
import math
from .store import Conflict,sha


def expand(search):
    if not isinstance(search,dict) or set(search)!={'id','template','parameters'} or not isinstance(search['id'],str) or not search['id'].strip():
        raise Conflict('search needs identity, exact template and numeric parameters')
    parameters=search['parameters']
    if not isinstance(parameters,dict) or not 1<=len(parameters)<=5:raise Conflict('search needs 1..5 parameters')
    values={}
    for name,rule in sorted(parameters.items()):
        if not isinstance(name,str) or not name.isidentifier() or not isinstance(rule,dict) or set(rule)!={'minimum','maximum','step'}:
            raise Conflict('invalid numeric search range')
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in rule.values()):raise Conflict('finite numeric search range required')
        low,high,step=(Decimal(str(rule[k])) for k in ('minimum','maximum','step'))
        if step<=0 or high<low or (high-low)/step>99:raise Conflict('search range must be positive, ordered and bounded')
        values[name]=[str(low+step*i) for i in range(int((high-low)//step)+1)]
    count=math.prod(len(v) for v in values.values())
    if count>100:raise Conflict('search cross product exceeds 100 trials')
    template=search['template'];names=list(values);trials=[]
    for selection in product(*(values[n] for n in names)):
        assignment=dict(zip(names,selection));trial=deepcopy(template)
        if not isinstance(trial,dict) or not isinstance(trial.get('argv'),list):raise Conflict('invalid exact search template')
        for name in names:
            token='{{'+name+'}}'
            if not any(token in arg for arg in trial['argv']):raise Conflict('parameter not wired to approved command: '+name)
            trial['argv']=[arg.replace(token,assignment[name]) for arg in trial['argv']]
        if any('{{' in arg or '}}' in arg for arg in trial['argv']):raise Conflict('unbound search parameter')
        if 'seed' in assignment:
            seed=Decimal(assignment['seed'])
            if seed!=seed.to_integral_value():raise Conflict('seed search must use integers')
            trial['seed']=int(seed)
        trial['id']=search['id']+'-'+sha(assignment)[:16]
        trials.append((trial,assignment))
    return trials

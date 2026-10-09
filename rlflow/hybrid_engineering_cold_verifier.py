"""Fixed raw-AST machine acceptance; NOT an independent Reviewer session."""
import ast
import hashlib
from pathlib import Path
from .hybrid_fixture_materials import _read_bounded
from .hybrid_goals import digest
from .hybrid_engineering_patch import AFTER,hash_bytes
from .store import Conflict,canonical

VERSION='FIXED_ADD_RAW_AST_CHECK_V1'
SPEC={'target':'module/source.py','function':'add','arguments':['a','b'],
    'expression':'a+b','cases':[[a,b] for a in range(-3,4) for b in (-2,0,2)],
    'scope':'FIXED_ADD_FUNCTION_ONLY'}
_SPEC_RAW=canonical(SPEC)


def derive(raw):
    """Inspect raw syntax first, then independently interpret bounded integers.

    No producer metrics, old tests, implementation conversation or exec/eval.
    Only the exact AST shape has meaning; all other Python is rejected.
    """
    if type(raw) is not bytes or len(raw)>4096 or canonical(SPEC)!=_SPEC_RAW:
        raise Conflict('fixed bounded raw AST specification required')
    try:tree=ast.parse(raw.decode('utf-8'))
    except (ValueError,UnicodeError,SyntaxError,RecursionError):raise Conflict('fixed candidate AST invalid') from None
    expected=ast.Module(body=[ast.FunctionDef(name='add',args=ast.arguments(posonlyargs=[],
        args=[ast.arg(arg='a'),ast.arg(arg='b')],vararg=None,kwonlyargs=[],kw_defaults=[],kwarg=None,defaults=[]),
        body=[ast.Return(value=ast.BinOp(left=ast.Name(id='a',ctx=ast.Load()),op=ast.Add(),right=ast.Name(id='b',ctx=ast.Load())))],
        decorator_list=[],returns=None,type_comment=None,type_params=[])],type_ignores=[])
    if ast.dump(tree,include_attributes=False)!=ast.dump(expected,include_attributes=False):
        raise Conflict('fixed add raw AST shape differs')
    tests=[]
    # Do not invoke the worker function or reuse the three producer test rows.
    # Interpret only the proven Add node and its two positional variable names.
    for left,right in SPEC['cases']:
        environment={'a':left,'b':right};expression=tree.body[0].body[0].value
        actual=environment[expression.left.id]+environment[expression.right.id]
        tests.append({'left':left,'right':right,'expected':left+right,'actual':actual})
    return {'source_sha256':hash_bytes(raw),'spec_sha256':digest(SPEC),
        'syntax_sha256':hash_bytes(ast.dump(tree,include_attributes=False).encode()),
        'actual_tests':tests,'passed_cases':sum(row['expected']==row['actual'] for row in tests)}


_LOADED_SOURCE_HASH=hash_bytes(_read_bounded(Path(__file__),16384))
_LOADED_DERIVE=derive
_LOADED_DERIVE_CODE=derive.__code__


def implementation_hash():
    current=hash_bytes(_read_bounded(Path(__file__),16384))
    if (current!=_LOADED_SOURCE_HASH or derive is not _LOADED_DERIVE or derive.__code__ is not _LOADED_DERIVE_CODE or
            canonical(SPEC)!=_SPEC_RAW):raise Conflict('protected loaded AST verifier implementation changed')
    return current


def verify(raw,*,implementation):
    derived=derive(raw)
    if derived['source_sha256']!=hash_bytes(AFTER) or derived['passed_cases']!=21:
        raise Conflict('fixed actual candidate failed machine acceptance')
    return {'verifier_version':VERSION,'verifier_sha256':implementation,
        'status':'MACHINE_ACCEPTED_PENDING_REVIEW','derived':derived,
        'interpretation_scope':'FIXED_ADD_FUNCTION_ONLY','candidate_read_only':True,
        'condition_coverage':[],'independent_review_status':'NOT_PERFORMED',
        'goal_completed':False,'dispatch_enabled':False}


def validate(value):
    # Historical semantics are version-pinned; never read current source bytes.
    if canonical(value)!=canonical(verify(AFTER,implementation=value['verifier_sha256'])):
        raise Conflict('original fixed AST machine verification differs')

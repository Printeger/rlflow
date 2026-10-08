#!/usr/bin/env python3
"""Validate this requirements package offline. Never launches agents or workloads."""
from __future__ import annotations
import copy
import json
import re
import sys
from pathlib import Path
try:
    import yaml
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource
except ImportError as exc:
    raise SystemExit('Install development dependencies jsonschema and PyYAML in an isolated environment.') from exc

ROOT = Path(__file__).resolve().parent

def main() -> int:
    checks: list[str] = []
    schemas: dict[str, dict] = {}
    registry = Registry()
    for path in sorted((ROOT/'schemas').glob('*.json')):
        data = json.loads(path.read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(data)
        schemas[path.name] = data
        resource = Resource.from_contents(data)
        registry = registry.with_resource(data['$id'], resource).with_resource(path.as_uri(),resource)
        checks.append(f'JSON Schema meta-validation: {path.name}')
    def validate(name: str, instance: object) -> None:
        Draft202012Validator(schemas[name], registry=registry, format_checker=FormatChecker()).validate(instance)
    def reject(name: str, instance: object, label: str) -> None:
        if Draft202012Validator(schemas[name], registry=registry, format_checker=FormatChecker()).is_valid(instance):
            raise AssertionError(f'Invalid sample accepted: {label}')
        checks.append(f'Negative fixture rejected: {label}')
    goal=json.loads((ROOT/'examples/goal.fixture.json').read_text())
    command=json.loads((ROOT/'examples/command.fixture.json').read_text())
    validate('goal.schema.json',goal); checks.append('Goal proposal fixture valid and UNAPPROVED')
    validate('command.schema.json',command); checks.append('Pause command fixture valid')
    submit={'schema_version':'1.0','action':'submit_goal','target':{'kind':'project','id':'project_fixture'},'expected_version':0,'parameters':{'goal':goal}}
    validate('command.schema.json',submit);checks.append('Nested goal reference in submit_goal resolved offline')
    bad=copy.deepcopy(goal);bad['approval_status']='APPROVED';reject('goal.schema.json',bad,'proposal self-approval')
    bad=copy.deepcopy(command);bad['actor']='human';reject('command.schema.json',bad,'client-supplied trusted actor')
    bad=copy.deepcopy(command);bad.pop('expected_version');reject('command.schema.json',bad,'pause without expected version')
    bad=copy.deepcopy(command);bad['parameters']['shell']='rm -rf /';reject('command.schema.json',bad,'arbitrary shell parameter')
    stop={'schema_version':'1.0','action':'stop','target':{'kind':'goal','id':'goal_fixture_01'},'parameters':{'reason':'fixture emergency','grace_seconds':10}}
    validate('command.schema.json',stop);checks.append('Scoped emergency stop can omit expected_version')
    events=[json.loads(x) for x in (ROOT/'examples/events.fixture.ndjson').read_text().splitlines() if x.strip()]
    seen=set()
    for expected,e in enumerate(events,1):
        validate('event.schema.json',e)
        assert e['data_mode']=='fixture' and e['seq']==expected
        assert e['event_id'] not in seen;seen.add(e['event_id'])
        payload_schema=schemas['payloads.schema.json']['$defs'][e['type']]
        Draft202012Validator(payload_schema,format_checker=FormatChecker()).validate(e['payload'])
        if e['type']=='budget.updated':
            b=e['payload'];assert b['unknown_exposure']<=b['reserved']
            assert b['available']==max(0,b['limit']-b['consumed']-b['reserved'])
    checks.append(f'{len(events)} event fixtures: envelope, typed payload, sequence, identity, budget arithmetic')
    cfg=yaml.safe_load((ROOT/'examples/project.example.yaml').read_text())
    assert cfg['execution_enabled'] is False and cfg['runtime']['adapter']=='fixture'
    assert all(v is None for v in cfg['models'].values())
    checks.append('Configuration template cannot directly enable a real runtime')
    api=yaml.safe_load((ROOT/'openapi.yaml').read_text())
    assert api['openapi']=='3.1.0' and 'info' in api and 'paths' in api
    ops=[]
    for path,item in api['paths'].items():
        placeholders=set(re.findall(r'\{([^}]+)\}',path))
        shared=item.get('parameters',[])
        for method,spec in item.items():
            if method not in ['get','post','put','patch','delete']: continue
            supplied={p['name'] for p in shared+spec.get('parameters',[]) if p.get('in')=='path' and p.get('required')}
            assert placeholders<=supplied,(path,placeholders,supplied)
            ops.append(spec['operationId'])
    assert len(ops)==len(set(ops))
    def check_refs(node: object) -> None:
        if isinstance(node,dict):
            for key,value in node.items():
                if key=='$ref':
                    if value.startswith('#/'):
                        part=api
                        for token in value[2:].split('/'):part=part[token.replace('~1','/').replace('~0','~')]
                    elif value.startswith('schemas/'):
                        assert (ROOT/value.split('#')[0]).is_file(),value
                else:check_refs(value)
        elif isinstance(node,list):
            for value in node:check_refs(value)
    check_refs(api)
    checks.append(f'OpenAPI starter YAML: {len(ops)} unique operations, required path parameters, local references')
    text=(ROOT/'PRD.md').read_text()
    ac=set(re.findall(r'^\| (A\d{2}) \|',text,flags=re.M));assert ac=={f'A{i:02}' for i in range(1,37)}
    tasks=set(re.findall(r'^\| (T\d{2}) ',(ROOT/'IMPLEMENTATION_PLAN.md').read_text(),flags=re.M));assert tasks=={f'T{i:02}' for i in range(26)}
    sources=(ROOT/'SOURCES.md').read_text()
    for i in range(1,17):assert f'## S{i:02}' in sources
    assert not any(x in text for x in ['cite','filecite','memcite'])
    checks.append('36 acceptance cases, 26 implementation tasks, 16 source entries, no tool-citation leakage')
    lines=['# 需求包离线校验报告','', '执行日期：2026-10-07。','',f'结果：**{len(checks)} 项检查通过**。','']
    lines += [f'{i}. {name}' for i,name in enumerate(checks,1)]
    lines += ['', '## 检查边界','', '仅运行本包 schema/fixture、YAML、引用、编号和安全模板的离线检查。OpenAPI 未由真实服务器导出，也未执行完整 OpenAPI 语义一致性认证；泛型读模型及其余领域 payload 仍由 T03 固化。未启动 rlflow/Codex/GPU，未验证真实运行隔离、恢复、性能、费用或研究有效性。','']
    (ROOT/'VALIDATION_REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    print(f'PASS: {len(checks)} checks; {len(events)} events; {len(ops)} API operations; 36 acceptance cases; 26 tasks.')
    return 0

if __name__=='__main__':
    sys.exit(main())

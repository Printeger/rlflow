"""Standalone state migration. No legacy project history or entry takeover."""
from pathlib import Path
import time
from .store import atomic, canonical, sha, Conflict
from .policy import candidate, new_stage

def import_history(store):
    raise Conflict('Project history is excluded from the standalone distribution')

def activate(store, report_path):
    raise Conflict('Project entry takeover is excluded from the standalone distribution')

def rollback(store):
    from .engine import reconcile
    state = reconcile(store)
    if not state['paused']:
        raise Conflict('pause before rollback')
    if any(s['status'] in {'RUNNING','START_INTENT','RECONCILE'} for s in state['sessions'].values()):
        raise Conflict('unresolved active role; reconcile before rollback')
    if any(j['status'] not in {'SUCCEEDED','FAILED','STOPPED','HANDSHAKE_TIMEOUT'} for j in state['jobs'].values()):
        raise Conflict('unresolved job before rollback')
    return store.transact('CONTROL_WORKFLOW_DISABLED','control-rollback:'+str(time.time_ns()),
        lambda s:(s.update(enabled=False,autonomous_tasks=[]),s['migration'].update(status='ROLLED_BACK')))

def seed_demo(store):
    from .policy import git
    import subprocess
    repo = store.root / "workspaces/budget-parser-demo"
    if "CPU-DEMO" in store.view()["stages"]:
        return repo
    if repo.exists():
        raise Conflict("unregistered demo workspace exists; preserve and inspect before adopting")
    repo.mkdir(parents=True)
    atomic(repo / "task_config.py", b'''"""Parse CPU task configuration."""
def parse_task(value):
    return {"name": value["name"], "budget": value["budget"]}
''')
    atomic(repo / "test_task_config.py", b'''import unittest
from task_config import parse_task

class ParserTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(parse_task({"name": "demo", "budget": 2}), {"name": "demo", "budget": 2})

if __name__ == "__main__":
    unittest.main()
''')
    atomic(repo / "CONTRACT.md", "# CPU 示例验收契约\nparse_task 接收 dict，name 为非空 str，budget 必须为非负 int（bool 不合法）。\n合法输入返回 name/budget 两字段，其他输入以 ValueError 或 TypeError 明确拒绝。\n不得改变验收标准。补充必要 unittest。GPU/runtime/网络/包安装关闭。\n".encode())
    subprocess.run(["git", "init", "-b", "cpu-demo", str(repo)], check=True, capture_output=True)
    git(repo, "add", "task_config.py", "test_task_config.py", "CONTRACT.md")
    git(repo, "-c", "user.name=rlflow", "-c", "user.email=rlflow@localhost", "commit", "-m", "Fixture: task parser missing budget validation")
    stage = new_stage("CPU-DEMO", repo,
                      "修复 task_config.py 的 parse_task 配置解析器：合法输入保持正确，负预算、错误类型（含 bool）及无效name明确拒绝；仅CPU实现、自测和独立审核。CONTRACT.md为冻结标准，不得修改。",
                      {"role_calls": 6, "wall_seconds": 3600, "fake_starts": 6}, "test fixture: isolated demo")
    stage["protected_paths"] = ["CONTRACT.md"]
    return store.transact("DEMO_STAGE_AUTHORIZED", "demo:authorization:v1", lambda s: s["stages"].update({"CPU-DEMO": stage}), producer="user-plan")


def upgrade_control(store):
    """Append the new object projection without upgrading any old authority."""
    def change(s):
        for name in ('packages','goals','research','repairs','releases','accounting_corrections'):
            s.setdefault(name,{})
        s['migration']['control_state_version']=2
        return {'legacy_permissions':'unchanged','historical_events':'unchanged','pause_intent':'retained'}
    return store.transact('CONTROL_STATE_UPGRADED','control-state-v2',change)

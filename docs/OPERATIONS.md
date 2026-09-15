# 独立操作说明

## 安装与本地检查

需要 Python 3.12；离线控制测试依赖 Linux 的进程和隔离能力。实际模型执行还依赖代码固定版本的 Codex CLI、有效登录与隔离检查。此处描述已有接口，不承诺换机器后自动兼容。

```sh
cd /path/to/rlflow_standalone
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
./bin/rlflow --help
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests
```

`requirements.lock` 在本副本只列直接依赖的固定版本，不是传递依赖完整锁。原同名文件是包含 ROS 包的机器环境清单，未当作可移植安装要求复制。若系统缺少 ensurepip，可用另一个已安装 pip 的解释器执行 `python -m pip --python .venv/bin/python install -r requirements-dev.txt`；不需修改原环境。

## 一个目标、一次批准

1. 选择全新的独立 STATE 目录，在其 `workspaces/` 下准备独立 Git clone（`git clone --no-hardlinks`），禁止共享 worktree、symlink、hardlink。
2. 复制 `examples/goal.json`，填写实际 repo、目标、验收条件、范围和总预算。它是输入模板，不是授权。任务步骤交给 PI 动态分解。
3. 在新状态下运行 doctor，检查通过后创建并查看提案。

```sh
./bin/rlflow --state-dir /absolute/new-state doctor
./bin/rlflow --state-dir /absolute/new-state start --goal-file /absolute/goal.json
# 由用户核对完整提案后批准；approve 会创建任务并启动自动流程。
./bin/rlflow --state-dir /absolute/new-state approve P-EXACT-ID --sha256 EXACT-HASH
./bin/rlflow --state-dir /absolute/new-state package-status PACKAGE-ID
./bin/rlflow --state-dir /absolute/new-state status --watch
```

普通范围内拆分、实现、返工、复审和集成不需要用户每次派工。超范围、耗尽预算或新增保留权限才需要新决策。所有命令使用同一个新状态目录，不能指向现有开发账本。

## 暂停与恢复

```sh
./bin/rlflow --state-dir /absolute/new-state pause --package PACKAGE-ID
./bin/rlflow --state-dir /absolute/new-state reconcile
./bin/rlflow --state-dir /absolute/new-state resume --package PACKAGE-ID
```

恢复先对账；未知启动不能靠反复 resume 盲目重试。STOP 文件优先于批准。监控命令只读；`reconcile` 是显式状态变更。`restart-daemon`、`deploy-control` 属于控制维护，不是日常推进每个子任务的步骤。

本副本禁用旧项目 `init-demo` 和 `activate` 入口。使用明确目标提案开始新任务，不能继承 demo 的历史默认授权。`rollback` 仅停用本状态控制流程，不写回任何旧项目入口。

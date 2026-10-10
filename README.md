# rlflow 独立架构副本

这是从现有 rlflow 控制面工作目录提取的独立副本，用于阅读架构、离线验证和后续独立开发。复制日期：2026-09-15。它是独立快照，不代表已发布版本。

不包含 instinctRL 产品实现、训练 workload、项目任务、现有授权、预算账本、历史运行结果、凭据或 Git 历史。原目录与运行中的调度器未切换到本副本。副本不是现有工作包的第二个执行者。

## 阅读顺序

1. [架构与数据流](docs/ARCHITECTURE.md)：模块分层、六角色、工程/研究循环。
2. [主要文件索引](docs/FILE_MAP.md)：从入口追到调度、worker、账本与恢复。
3. [操作说明](docs/OPERATIONS.md)：独立安装、长期目标输入、一次批准及监控。
4. [权限和恢复](docs/RECOVERY_AND_AUTHORITY.md)：状态、预算、暂停、STOP、未知启动。
5. [项目适配边界](docs/ADAPTERS.md)：通用核心与 H1 的区别。
6. [副本变更与验证](docs/EXTRACTION.md)：来源、排除项和验证范围。
7. [验证结果](docs/VERIFICATION.md)：可发布的离线测试摘要。

```text
rlflow_standalone/
  bin/rlflow           独立 shell 入口
  bootstrap.py         校验账本与选择冻结控制版本
  rlflow/              Python 控制面模块（保持原布局）
  roles/               六角色 TOML 契约及历史 Markdown
  schemas/             输入输出与事件 JSON Schema
  model_policy.yaml    角色模型和升级策略
  tests/               通用测试及外部依赖跳过说明
  examples/goal.json   无批准权限的长期目标模板
  docs/                独立架构与操作文档
  audit/               本地提取记录（Git 忽略，不推送）
```

默认新状态路径为 `~/.local/share/rlflow-standalone/coordination/research`。建议每个独立项目显式传 `--state-dir`。本次不创建业务目标、不调用真实模型、不运行训练。

2026-09-16 已同步可靠性更新，详见 [可靠性与兼容边界](docs/RELIABILITY.md)。
独立路径与未配置项目 Runner 的默认值保持不变。

## Hybrid v1 开发中

原命令在接纳后丢失机器阶段返回的显式恢复见 [原有限执行恢复](docs/hybrid-v1/HYBRID_UNIT_RECONCILIATION.md)。安装态 CPU 单次补决策、工程原事实读回及 STOP 已验证；Dashboard 已接入同 body/key 的人工恢复和 UNKNOWN 展示，不自动重启执行或清除曝露。预算余额尚未接入，界面明确显示未读取。

执行关闭后的原结果消费见 [安装态只读宿主](docs/hybrid-v1/HYBRID_COLD_RESULT_HOST.md)。新进程读取原机器结果和验收缺口，不恢复运行能力或注册写入口。

安装后的 model-free 固定工程/实验与原 STOP 验证见 [安装态固定执行](docs/hybrid-v1/HYBRID_INSTALLED_FIXTURE.md)。入口为 `python -m rlflow.isolated_finite_example`，仅创建全新私有 fixture，并逐项目确认原 scope；不等于通用项目、独立产品 Review、冷重启执行或完整发布验收。

完整需求见 [PRD](docs/hybrid-v1/PRD.md)，实施状态见 [PROGRESS](docs/hybrid-v1/PROGRESS.md)，验收证据见 [系统验证记录](docs/hybrid-v1/IMPLEMENTATION_VALIDATION.md)。当前已有严格 v1 协议、同事务只读观测桥、有界快照/SSE、实际只读 Dashboard、CORE_STATUS 日志与绑定CPU工具返回；资源遥测、完整 Dashboard/Hybrid 工程科研闭环及发布验收尚未完成。工具返回不表示模型启动或任务成功，未知历史和费用不显示为0。

本地服务的登录、启动、只读API、工具覆盖与浏览器验证说明见 [LOCAL_WEB](docs/hybrid-v1/LOCAL_WEB.md)。服务只监听loopback，不创建调度器、模型调用或HTTP写权限；Fixture必须明确标识，不能作为真实模型/GPU闭环证据。

无模型调用的本机能力检查：

```bash
.venv/bin/python -m rlflow.capabilities
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

能力探测不会读取账号凭据或启动模型。未配置精确版本和协议 SHA256 时 `compatible` 为 false；即使匹配，仍不代表真实模型访问、硬 token 上限或原生子代理隔离已经通过验收。执行隔离目前固定 Codex `0.161.0`，升级必须重新验证工具注册与内核边界。

程序读模型使用 `rlflow.observation.ObservationReader`，仅打开已存在数据库的只读连接。观测初始化必须通过受信控制代码显式调用 `enable(store, project_id, data_mode=...)`；API 不得自行创建、迁移或调度状态。不要将演示状态连接到真实项目的 live endpoint。

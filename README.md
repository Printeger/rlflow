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

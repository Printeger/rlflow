# 主要文件索引

所有路径相对副本根目录。

| 功能 | 文件 | 阅读重点 |
| --- | --- | --- |
| 用户入口 | `bin/rlflow`, `bootstrap.py`, `rlflow/cli.py` | 命令解析、状态目录、冻结版本选择 |
| 核心调度 | `rlflow/engine.py` | dispatch_one、accept_result、reconcile、daemon |
| 工作包 | `rlflow/packages.py`, `rlflow/decomposition.py` | 批准绑定、可运行任务、动态分解、父子接续 |
| 状态存储 | `rlflow/store.py` | 事务、追加事件、完整性、投影 |
| 权限 | `rlflow/policy.py`, `authorizations.py`, `contracts.py` | 精确提案、STOP、范围、输出校验 |
| 模型会话 | `rlflow/worker.py`, `model_policy.py`, `role_config.py` | 启动放行、使用证据、模型及角色冻结 |
| 执行隔离 | `rlflow/isolation.py` | CPU 工具、读写权限、网络/进程边界、检查点 |
| 进程恢复 | `rlflow/jobs.py`, `lifeguard.py`, `validation_job.py` | 持久身份、独立监督、未知执行、测试恢复 |
| 预算与故障 | `rlflow/accounting.py`, `failures.py`, `repairs.py` | 预留、消费、启动前失败、受限控制修复 |
| 研究与进展 | `rlflow/research.py`, `progress.py`, `search.py` | 假设、证据、停滞、参数搜索 |
| 决策扩展 | `rlflow/adoption.py`, `escalations.py`, `literature.py` | 采用批准、模型升级、受控咨询 |
| 上下文证据 | `rlflow/context.py`, `evidence.py` | 有界材料、来源与反证 |
| 实验接口 | `rlflow/experiments.py`, `h1.py` | submit/reconcile/cancel/collect；H1 专用可选桥接 |
| 发布和迁移 | `rlflow/releases.py`, `verification.py`, `migration.py` | 内容寻址发布、检查证据、追加状态升级 |
| 角色与协议 | `roles/*.toml`, `schemas/*.json`, `model_policy.yaml` | 六角色身份、机器可读契约、模型策略 |

先读 cli → engine → packages/decomposition → worker/store，再按需深入隔离、实验和研究模块。

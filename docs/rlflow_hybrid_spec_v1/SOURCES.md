# 来源与核验范围

核验日期：2026-10-07。本文列的是外部依据，不是本产品已经实现的功能清单。规格中的新增架构、阈值、界面和测试目标均为本次设计建议。

## S01｜rlflow 基线提交

默认分支最新返回提交：`90fd977f0ebcd3d00a5ce50c64f7ecb9a5009dae`；提交时间 `2026-09-15T11:22:49Z`，消息为 Initial standalone rlflow architecture。

```text
https://github.com/Printeger/rlflow/commit/90fd977f0ebcd3d00a5ce50c64f7ecb9a5009dae
```

## S02｜rlflow 架构

直接读取 `docs/ARCHITECTURE.md`，blob SHA `a77d3f78da9b34168bf04e6db758450caddc7cd5`。依据为确定性调度、角色短会话、证据账本及当前限制。

```text
https://github.com/Printeger/rlflow/blob/90fd977f0ebcd3d00a5ce50c64f7ecb9a5009dae/docs/ARCHITECTURE.md
```

## S03｜rlflow 文件映射

直接读取 `docs/FILE_MAP.md`，blob SHA `9059e003155c887be103d1960cdda0acc7e5f003`。用于迁移章节的现有模块职责，而非宣称已完成全面代码审计。

```text
https://github.com/Printeger/rlflow/blob/90fd977f0ebcd3d00a5ce50c64f7ecb9a5009dae/docs/FILE_MAP.md
```

## S04｜rlflow 权限与恢复

直接读取 `docs/RECOVERY_AND_AUTHORITY.md`，blob SHA `db12778e6a6b67adcc574721dd749c6e8302f599`。保留批准绑定、预算 unknown、完整进程身份及冻结控制版本的约束。

```text
https://github.com/Printeger/rlflow/blob/90fd977f0ebcd3d00a5ce50c64f7ecb9a5009dae/docs/RECOVERY_AND_AUTHORITY.md
```

## S05｜Codex App Server 官方文档

官方入口本次重定向到 ChatGPT Learn。文档说明 JSON-RPC 风格协议、stdio、线程与轮次、usage/审批通知及实验性边界。需求不把这些能力在任意版本中的可用性视为已实测。

```text
https://developers.openai.com/codex/app-server
https://learn.chatgpt.com/docs/app-server
```

## S06｜Codex 非交互模式官方文档

JSONL、结构化最终输出、认证与恢复机制的依据。复用本地授权不等于新运行自动获批。

```text
https://developers.openai.com/codex/non-interactive-mode
https://learn.chatgpt.com/docs/non-interactive-mode
```

## S07｜Codex 子代理官方文档

自定义角色与并发配置的依据。配置名称和权限效果应由具体版本探测确认。

```text
https://developers.openai.com/codex/multi-agent
https://learn.chatgpt.com/docs/agent-configuration/subagents
```

## S08｜Codex Skills 官方文档

单一自然语言 skill 入口与按需读取资料的依据。

```text
https://developers.openai.com/codex/skills
https://learn.chatgpt.com/docs/build-skills
```

## S09｜live-panel 原作者仓库说明

直接读取 README，blob SHA `ade7a933909f074476720b48331b48b3e8d40e09`。说明时间函数、seek、rAF、原创出处与代码/示例视觉的许可区分。本文件未对原 X 视频源码技术栈作出断言。

```text
https://github.com/ythx-101/live-panel-skill/blob/main/README.md
```

## S10｜MDN：Server-Sent Events

单向推送、EventSource、消息字段、连接与重连机制的依据。

```text
https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events
```

## S11｜MDN：requestAnimationFrame

浏览器帧驱动接口依据。业务数据更新频率与动画帧率的分离是本次设计决策。

```text
https://developer.mozilla.org/en-US/docs/Web/API/Window/requestAnimationFrame
```

## S12｜SQLite：Write-Ahead Logging

SQLite WAL、读取与写入及部署限制的官方依据。事件+投影同事务、快照和恢复策略是本次架构要求。

```text
https://www.sqlite.org/wal.html
```

## S13｜Linux Kernel：Control Group v2

进程树 CPU、memory、pids 等资源控制接口的官方依据。Docker 内实际可用性必须现场检查。

```text
https://docs.kernel.org/admin-guide/cgroup-v2.html
```

## S14｜FastAPI 官方文档

Python API 服务建议技术栈；具体依赖版本在开发验证后锁定。

```text
https://fastapi.tiangolo.com/
```

## S15｜React / Vite 官方文档

前端技术选型依据，不要求未经检查地追随最新版本。

```text
https://react.dev/
https://vite.dev/guide/
```

## S16｜MDN：prefers-reduced-motion

减少非必要动态效果的客户端偏好机制依据。

```text
https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@media/prefers-reduced-motion
```

## 本次未执行的验证

未运行用户真实 rlflow 状态库，未测试本机 Codex 账号/版本，未调用真实模型或 GPU，未做端到端性能压测，未修改 GitHub 仓库。本包 schema/fixture 可进行离线结构校验；其通过不等于运行时授权、隔离或科学有效性通过。

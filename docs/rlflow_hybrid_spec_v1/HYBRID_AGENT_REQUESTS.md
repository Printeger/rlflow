# Agent 目标请求与人类转交

Checkpoint71 交付结构化目标请求闭环，是 T15 的部分实现，不是完整自然语言入口、执行或 STOP 闭环。原 M0–M5 Goal 保持 active；Checkpoint70 基线提交为 `019e3a3`。

## 已交付行为

目标项目中的单一 `rlflow client` 入口，以短期 request-only Agent 凭据提交显式 Hybrid 1.1 proposal。请求只进入独立有界 inbox，不写 Core、批准、调度、预算或启动 worker。Dashboard 人类 operator 查看完整 proposal/hash，显式同意转交后，调用原 DraftService；客户端仅在原 Core 合同、事件和命令回执来源一致时报告 ADOPTED。结果仍为未批准、不可执行的 DRAFT。

实际 HTTP、CLI 和 Chromium 证据覆盖这条行为链：初始 Core version 0，转交后恰好 version 1、一个 DRAFT，tasks/sessions/jobs 均为空。浏览器丢失已提交的转交响应后只读原请求恢复 ADOPTED，不再 POST。项目切换、过期和注销清除私有 proposal DOM，viewer 无转交权限。

## 使用与权限边界

产品 skill 随 wheel 打包，`rlflow client skill-path` 返回其路径；未安装到用户全局 Codex skill 目录。可信启动器须预置 `RLFLOW_CONTROL_ORIGIN` 和 `RLFLOW_REQUEST_TOKEN`，token 不能进入 argv、项目配置或输出。发行 request-only token 仅有可信 SDK，无 HTTP 自助提权端点，旧 bearer 不能升级。Agent 只能读自己的请求；人类转交仍需原 operator 会话、同源与 CSRF。

当前目标目录 `.rlflow/project.yaml` 使用闭合的最小 client profile，恰好包含以下三个字段。这不是完整 PRD 项目配置兼容性已验收的声明。

```yaml
schema_version: "1.0"
project_id: project_fixture
control_origin: http://127.0.0.1:8765
```

可信环境 origin 必须与项目配置完全相同。目前仅明确端口的本地 loopback HTTP；禁止环境代理、重定向、远端 URL、符号链接或特殊输入文件。proposal JSON 有界且拒绝重复键和非有限数。

```bash
rlflow client submit-goal --proposal proposal.json --key original-key
rlflow client status --request request_<id>
rlflow client report --request request_<id>
```

source checkout 对应入口为 `python -m rlflow.cli`；最终 wheel 的真实 console script 已独立安装验证，不能以不存在的 `python -m rlflow` 替代。

## 持久化与恢复

inbox 固定于原 Store 下的 `agent-requests.sqlite3`，32 行容量、固定 4096 页上限；页限制不是文件系统硬配额。新建独占私有普通文件，旧库须通过精确 DDL/index、元数据、项目/mode/epoch 和页范围验证，缺表或异构库拒绝，不隐式 DDL/reset。读取在 SQL fetch 前限制字段大小，严格 JSON 与共享 ReadBudget 继续限制展开成本。

服务绑定原实例/进程/Store/DraftService，fork 或复制实例在触碰继承锁之前拒绝。事务提交前再次检查权限有效期。转交冻结原人类 actor、proposal、Core expected_version、命令 key，inbox 锁外调用原 DraftService，不建立第二套 Core 权威。

AWAITING_HUMAN 表示未转交；UNKNOWN 表示来源尚不能证明结果，不能当成功；STALE 表示冻结版本已被越过且没有原接受来源，不能自动 rebase；ADOPTED 只证明原 DRAFT 接受。丢回执读取相同 request；人工显式重试只沿原 actor/body/key/version，不重建命令。原 Core 来源损坏返回 503，不伪造接受。

## 验收证据与剩余缺口

R2 八模块必要回归 228 passed；实际 Chromium 1 passed。最后独立 High 提出的精确旧库 DDL 闭合与返回 request ID 绑定两项修正，仅改变两个 Python 模块及其测试；R3 两模块 48 passed，另 608/612 冻结路径不变，因此复用未受影响的 R2 浏览器及旧模块证据，而非宣称最终候选重新跑过全库。七组审查 MUST 已关闭；审查未另跑重复测试。

最终 wheel SHA256：`698055c9c3a3ebd4ca9843a15ee41a1f46b4d65a2414c061591e80c5991b3326`。实际安装包来源位于 checkout 外，console/status/report/skill resource 验证通过。证据命令、失败诊断、原日志与输入 manifest 见 [checkpoint-71-tests.txt](evidence/checkpoint-71-tests.txt)。这不是完整 T23 新安装/B1 证明。

下一切片72：Agent 请求 STOP，由人类显式转交至原有限执行体的原 STOP coordinator，并以真实取消、reap、FD 关闭、Pool 释放及原回执完成可靠闭环；客户端不得自己批准或 kill。

尚未验收：A01 自然语言自动触发/全局安装、完整项目配置与 schema/catalog discovery、client STOP、native 模型执行及产品独立 Reviewer、完整条件完成门、严格 OS 任意树/配额、invoice、B1/T21/T22/T23、24h/8h 与完整 M5。未调用付费模型/GPU，未迁移生产状态。原模型/Reviewer 预算和 cgroup delegation 决策缺口保持，不因此扩大本切片权限。

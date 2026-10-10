# Agent 目标请求与人类转交

Checkpoint74 更新：原有限工程/科研结果可通过 request-only `client execution-report --kind … --source …` 读取来源绑定的机器结果和条件缺口，不接受PASS或派发。实际双项目、最终安装console与原STOP通过，详 [HYBRID_CLIENT_EXECUTION_REPORT.md](HYBRID_CLIENT_EXECUTION_REPORT.md)。73完整静态配置/目录已交付；T15仍不是完整自然语言自动调用。

Checkpoint73 更新：客户端也接受原完整 `project.example.yaml` 静态profile，新增 `rlflow client describe` 从原注册权威读取schema/catalog供显式提案消费，不接执行配置/预算。完整配置→发现→建议→human原DRAFT→report已通过实际安装console。详 [HYBRID_CONTRACT_DISCOVERY.md](HYBRID_CONTRACT_DISCOVERY.md)；下方三字段限制和“下一72/配置discovery未验收”是71–72历史阶段，不再是73当前缺口。完整A01、全GoalSTOP及原native/OS/Reviewer/长期缺口保持。

Checkpoint71 已交付结构化目标请求闭环。Checkpoint72 已验收显式原有限全集 STOP 建议的实际客户端、人类 Dashboard 转交与物理清理链，必要回归和最终发行检查通过，归档后提交。两者均为 T15 的部分实现，不是完整自然语言入口或整个 Goal STOP。原 M0–M5 Goal 保持 active；Checkpoint71 提交为 `3836e7b`。

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

### 72 实施中的范围和验收

71 已提交 `3836e7b`。72 采用显式原有限全集请求，不把当前项目默认 STOP 扩大到其他项目，也不是 Goal STOP。项目仅作为 inbox 存储锚点；新 body 必须列明原 coordinator 捕获的全部 project/mode/epoch/task/action 和 scope hash。Agent 提交及自己的 status/report、人类 list/detail/forward 都须核全部目标权限，并在返回或提交前复核实际会话。旧 Goal body/claim、数据库 DDL 和同 key 冲突规则保持不变。

转交先持久化冻结原人类主体、原 key、完整 scope 和派生 batch ID；释放 inbox/Auth 锁后立即原 coordinator.prepare/latch，再进入原独立 STOP 执行队列。该建议转交入口不能承诺任何 inbox I/O 前锁存：inbox 不可写即尚未转交，原 Dashboard 直接紧急 STOP 仍保持独立可用。普通重试只读原来源/缓存；仅人类显式 resume 未完全确认项，跳过已完整确认项。

当前新增的真实行为是原全集 GET 回执逐 scope 核验原 Core STOP 来源，读池独立于 STOP 执行池。缓存接受项缺来源或不一致返回 503；UNKNOWN 缓存遇到合法原 receipt 仍不提升 cleanup/整体状态。读门在锁内验证实际 issued batch/raw/action/task/key/hash，复制 body 快照后才锁外读源，不调用 prepare/cancel 或新 worker。真实两原 scope STOP→GET、异主体不可读、SDK body 突变拒绝、读源期间原 body 改变不污染快照、源损坏 503/no second cleanup/Pool0 的定向测试已通过。UNKNOWN 分支测试使用人工注入的 UNKNOWN 缓存配合已真实接受的合法 Core receipt，不冒充自然丢回执时序。

同时修复71新增嵌套 skill 暴露的封存安装目录问题：原 parents=True 仅给叶目录0700，中间目录可能按默认 umask 创建。现逐层私有创建，保留原 closed_inventory 检查；skill manifest hash 与三层目录权限断言通过，受影响其余25项封存回归通过。未改变校验标准或迁移生产状态。

当前客户端、typed inbox 和 Dashboard 已接通。目标目录 `rlflow client request-finite-stop --scope scope.json --key original-key` 只保存显式范围建议；完整范围必须由可信启动配置提供，不能由当前项目自行推导。Dashboard 展示全部目标及 hash，human 明确勾选后才转交；另设显式继续原未知 scope 收尾按钮，不自动恢复。前端在显示前验证 scope 与派生全集/子命令 ID、原 body hash，项目或认证票据改变会丢弃晚返回。

真实 Chromium 已通过原两 scope STOP、实际 CPU pre-G 禁止、producer reap、所有 FD 关闭和 Pool0；丢成功响应后只读原请求恢复，恰好一次 POST。后端定向验证权限不足和重算合法 hash 后的 epoch/task/action 漂移零 latch、inbox 故障尚未转交、原清理丢返回的来源恢复、普通重试零清理、部分 UNKNOWN 显式恢复跳过已确认项。冷读仅持久 claim 为 UNKNOWN，不能证明 physical STOP。关闭 owner 不提供新物理成功证明；仍未证明任意进程树或整个 Goal 停止。

转交用最多2个保留编排任务，寿命不随 HTTP waiter 取消；原 prepare 完成后仍负责一次原 STOP 提交。最终来源读取用独立有限读池，不能阻塞 ASGI loop或占原 STOP 清理槽。实际 route coroutine 在全 latch 后取消，随后原任务仍完成；末读取阻塞时同事件循环 profile 可响应。该测试不是浏览器 TCP 断连证明。最终增加原普通 inbox/list 队列饱和的组合检查，正在必要回归中。

唯一必要受影响回归原61915自然终态通过15项、327.32秒，329输入结束及发行检查后全部匹配；最终普通inbox/list队列阻塞组合也通过。最终独立 High 窄差量无剩余 MUST，不另跑重复测试。离线构建 wheel SHA256 `b5ec07bfa0f03e29b2e21548e2df2d4079bd828ab020eef117f10246257ca860`；实际隔离安装后的 console 从目标 cwd 提交有限建议、status、人类原SDK STOP后report和packaged skill通过。安装探针不启动worker；实际运行CPU清理证明来自上述Chrome和后端测试，不能混用为产品Reviewer或新全库证明。所有测试终态，无live进程，证据归档后提交72。此前来源读/封存失败和证明见 [checkpoint-72-wip-tests.txt](evidence/checkpoint-72-wip-tests.txt)，本轮真实请求证据与失败诊断见 [checkpoint-72-request-turn-tests.txt](evidence/checkpoint-72-request-turn-tests.txt)。

尚未验收：A01 自然语言自动触发/全局安装、完整项目配置与 schema/catalog discovery、完整 client STOP（整个 Goal/任意树）、native 模型执行及产品独立 Reviewer、完整条件完成门、严格 OS 任意树/配额、invoice、B1/T21/T22/T23、24h/8h 与完整 M5。未调用付费模型/GPU，未迁移生产状态。原模型/Reviewer 预算和 cgroup delegation 决策缺口保持，不因此扩大本切片权限。

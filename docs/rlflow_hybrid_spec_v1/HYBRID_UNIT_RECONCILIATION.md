# 原有限执行命令的显式恢复

Checkpoint78 已完成本切片的安装验收。原命令已持久接纳但后续机器阶段未返回时，同一人类操作者可以显式恢复该命令。恢复只消费原进程保留的可信能力与事实，不重新启动 worker，不采纳历史 PID，也不扩大批准范围。

## 调用条件

向 `/api/v1/projects/{project_id}/{cpu-unit|engineering-unit}/commands/{command_id}/reconcile` 发送原 START 的完整 JSON body。使用原操作者的有效 session、同源 Origin、CSRF 和原 Idempotency-Key；`expected_state_version` 必须仍是原 START 接纳时的值，不能换成当前版本。

原普通 START 重试仍只读回旧接纳回执，不自动恢复后续阶段。恢复入口不接受 CANCEL，非法 CANCEL 不锁存取消。新命令、不同 key、不同原 body、缺失或损坏的来源都不能变成新执行。

## 恢复行为

恢复首先核验原 HANDOFF 来源、命令完整内容和原接纳回执，然后调用原 Unit 的 `resume()`。CPU 可在原结果仍保留、原权限仍有效且未取消时，通过原写保护器补齐缺失的机器决策。工程任务仅核验已进入过原写入的结果，不自动再次写候选文件。

成功响应的 `original_acceptance` 是原命令回执，`result` 是原有限 Unit 状态。存在结果事实时，`result_fact` 包含由原读器核验的 fact ID、source ID、摘要及记录版本。`new_dispatch_enabled`、`automatic_effect_retry_enabled` 和 Goal 完成状态均为 false；机器通过仍需独立产品评审。

原子进程启动结果不明且没有原结果能力时，恢复返回 `UNKNOWN_RESULT_UNAVAILABLE`，不能从实验室观察到子进程死亡推导 FREE 或退还预算。需要安全关闭父进程持有 FD 时，使用原 `shutdown_safety()`；它不清除持久 UNKNOWN 曝露。

## 权限和停止

来源准备、恢复和结果证明均在独立有界池内执行。取消 HTTP 等待者不释放尚未结束的真实工作容量；退出等待真实工作终态。STOP 使用原独立通道，不与阻塞的恢复读取争用这两份容量。

任何新机器事实仍受原 session、原批准、原 Controller、原能力与末次 STOP 保护。来源损坏返回 503，非法外部请求返回 400；原身份或权限不符不能通过来源失败掩盖。关闭、复制或冷启动后的对象不能接管原执行能力。

## 验收状态和剩余工作

六项新增用例分轮通过，覆盖实际丢失机器返回、缺失 CPU 决策的单次补写、损坏来源 503、末次 session 过期和 STOP 写门、UNKNOWN 曝露及阻塞恢复；另有四项受影响的旧控制与清理回归通过。它们是分轮证据，不是新全库或浏览器验收。失败根因和完整安装终态见 [验收索引](evidence/checkpoint-78-tests.txt)。

最终安装消费者完整退出为 0：CPU 的 384 点原结果补写一次机器决策；工程的 3 项原输出和 21 项机器 AST 检查仅读回原已提交接纳事实。两个项目各启动一次 worker，工程写入一次，恢复期间禁止新启动、G、采集和文件写入。原 console 报告、HTTP 全集 STOP、进程 reap、所有原 FD 关闭和 Pool 占用归零均通过。UNKNOWN 的真实子进程丢返回用例独立保留预算曝露和一槽占用，没有混作成功 STOP。

安装到隔离目录后，可在 checkout 外使用现有普通依赖运行：

```bash
python -m rlflow.isolated_finite_example --parent /existing/private/disposable-parent --approve-isolated-fixed-fixture --verify-original-reconciliation
```

该选项只向新 fixture 注入有界的机器阶段失败；每个完整原提案仍须单独输入其 `APPROVE sha256:...`。它不会更新现有项目、续期旧授权或迁移原状态。

## Dashboard 显式恢复（Checkpoint79）

CPU 和工程面板收到严格 HTTP 202 的原 START 回执后，保留本会话原 body/key。只有当前原 human operator、相同项目/epoch/任务和仍可用的原 owner 才能点“显式核对或恢复原命令”。它使用原 command ID、原 body/key 和当前 CSRF；普通 START 重试仍不恢复机器阶段。

面板通过原固定 ASCII 合同的 SHA256 验证 command ID、body 摘要及 CPU/工程事实 ID 派生链。恢复只接受 HTTP 200 的封闭 DTO，显示原结果、事实摘要和记录版本，保留 Goal 未完成、独立 Review 未执行的缺口。丢返回或矛盾来源会清除本次恢复结果并显示 UNKNOWN；只允许再次人工核对同一命令，不自动重试。项目、身份、epoch 或任务变化以及退出登录会清除本地原命令上下文，迟到的网络或加密结果不能补回 DOM。

恢复读取等待时，原 STOP 按钮仍独立可用。当前原接口没有预算余额字段，面板明确显示“预算未读取”，不推导 FREE、退款或余额；结果 JSON 也不证明当前执行或当前资源状态。

真实 Chrome 故障链及前端负例的分轮证据见 [Checkpoint79 验收索引](evidence/checkpoint-79-tests.txt)。浏览器装配使用隔离的原测试 fixture，不冒称安装态、真实 UTC 或通用生产恢复；Checkpoint78 的安装证据独立保留。

下一切片将可信原预算账本和共享池占用接入只读消费，验收是 UNKNOWN 曝露与真实 STOP 后占用变化可观察、跨项目不混用、未观测不显示零；不把历史结果升级为当前资源证明或供应商实际费用。

该切片不构成控制宿主崩溃后执行接管、原生模型任务恢复或完整 M0–M5 验收。原独立产品 Reviewer、严格 OS 限额、供应商费用来源、B1 和长期运行验收仍保持原缺口；不调用付费模型、GPU 或生产状态迁移。

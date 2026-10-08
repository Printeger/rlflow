# 持久未批准合同草案（T09 首切片）

Checkpoint24。这是完整 T09 的增量基础，不是可信审批、调度、工程/科研闭环或 M1–M5 完成声明。T01/T03 前置已经具备；完整 M1/B1 与长期证据缺口继续保留。没有启动真实模型/GPU，也没有把开发 Goal 交给 rlflow。

## 存储与可信边界

`rlflow.hybrid_goals.propose` 使用既有单写 Store 和同一 SQLite 事务写入三个 optional private-hot 集合：

- `hybrid_goal_contracts`：不可变版本，proposal、规范 SHA256、前版本 hash、服务端计算的 JSON-pointer 差异、提交主体与 UTC 时间。
- `hybrid_goal_heads`：匹配 expected_revision 的 CAS head，合同版本必须连续增加。
- `hybrid_goal_commands`：不可变内容绑定回执，保存原 request/hash、合同 key/hash 与原 accepted_state_version。

不修改 `initial()`，不自动迁移或复用 legacy `goals`、stage、批准、预算或任务；旧 `goals` 属于 package ACTIVE/DONE 流程。三个新集合不会被 legacy scheduler 的 `view()` 枚举，但完整 snapshot/audit/recover 保留它们。没有新增公共 kind 或 HTTP 写路由；只读 Dashboard 不被视为可信批准渠道已经交付。

所有记录强制 `DRAFT`、proposal `UNAPPROVED`、approval_id/outcome=null。调用者必须传服务端已认证的 `Principal`，具有对应项目 operator 角色；JSON 中的 principal/approved_by、APPROVED/READY 均不能代替它。草案可以由受范围限制的 agent operator 提交，不因此获得 approver 或执行权限。Python 函数调用处属于受保护控制代码边界，不能将请求 JSON 转成任意 Principal。

当前 M1 `AuthStore.issue_bearer` 仍只发 viewer token；本模块没有新增 agent operator 凭据或宿主认证桥。上述 agent operator 是可信内部集成的输入类型，不表示现有只读 bearer 已能提交目标，更不表示它能批准。

project_id/data_mode 来自可信配置，必须与 proposal 和同事务读取的 observation_meta 登记一致；无登记拒绝。fixture/live 分域。先行 head 读取仅预检，commit 及重试回执读取另在实际事务核对登记。

## 幂等与恢复不变量

event key 使用 action、actor id/kind、项目、模式、client 幂等键的完整规范哈希；event object_id 使用包括 expected_revision 与完整 proposal 的 request hash。Store 原子 `_existing` 检查因此能拒绝同 namespace/key 异内容，包括并发竞争；不同可信主体/项目/模式的同名 client key 是不同 namespace，不是共享授权。合法重试可以晚于 head 变化，返回原 receipt 的版本和合同，不使用重复分支返回的当前全局 Store version。原 event/receipt 缺失或 eventtype/producer/requesthash/原版本不一致时拒绝，不补造事实。

每次 draft 转换只允许恰好一个合同、head、receipt，不允许夹带 legacy 控制/批准变化。commit 和历史 replay 使用同一转换校验：旧 revision/receipt 不可改删，前版本/hash/diff 一致，已有集合不可重复写 `{}` marker。marker 存在判断包括“marker 缺失但还有对象”的损坏投影，避免 live SQL 保留旧行而 replay 清空集合的分歧。通用 scoped 写入口不能绕过这些转换规则。

手动 snapshot、恢复初始快照/最终状态、完整 audit 和周期 maintenance 均验证合同链/head/receipt 闭合。回执按核心事件的 UNIQUE 幂等键索引检查原事实 tuple，不扫描全部历史。周期 builder 在一致只读事务保存 registration/source event witness，锁外完整校验，并在短 publish 事务再次核对 registration；校验失败不发布新快照、不清 due、不覆盖旧证据。原 bytes/rows/nodes 与协作 deadline 保留，不宣称硬 deadline/RSS 上限。

请求最大 256KiB，持久记录最大 1MiB（包含前后差异），容量检查贯穿便利入口、generic validator、commit/replay/恢复。条件 ID 唯一且至少一个 required；条件、scope 集合、规则/路径字符串和整数有界。路径只做声明语法检查（拒绝 traversal、glob、控制字符等），不把它当作已经完成 OS 路径/符号链接隔离或资源可执行性批准。

## 当前接口

```python
result = propose(
    store, proposal,
    principal=server_authenticated_principal,
    project_id=registered_project_id, data_mode=registered_data_mode,
    idempotency_key=client_key, expected_revision=0,
)
# result: contract (DRAFT), accepted_state_version (original), duplicate
```

expected_revision=0 创建版本1，后续修订必须匹配当前合同 revision；它不是全局 Store version。返回不是命令已经执行、目标 READY 或用户已批准。HTTP/skill 接入将在后续可信命令层完成，不能把上面的示例变成模型可自行构造 human principal 的批准桥。

原 proposal schema1.0 缺完整 allowed-tools 与 evaluation-data 边界；只允许保存为未批准草案，不默认补权限。后续批准门必须补齐版本化合同、精确 scope/hash/diff、真实 human approver、有效期/撤销、可靠 STOP 与执行前 gate，缺任何必需边界拒绝执行。局部条件/global evidence 与完成门控亦仍待 T10/T13 等，不从 DRAFT 数量推算进展。

## 验证记录

Root 首批23passed；相关7模块 r2/r3/r4/r5 分别148/155/157/160passed。High静态指出并关闭：入口外容量绕过、周期snapshot漏closure、错原receipt版本恢复、重复marker造成SQL/replay差异。统一重试 producer tuple 的最终增量：root新模块 **36passed/2.79s**，独立同7模块 **161passed/9.91s**，当前范围无剩余MUST_FIX；冻结全回归 **663passed/32既有外部/H1skips/1既有Starlette warning/234.49s**。各原handle已terminal exit0，不把旧160结果当最终版证据。未新增browser/性能负载结果，旧性能证据仍绑定旧源码。

测试包含真实 Store 原子事务/并发争用、幂等与回执损坏、伪批准、项目/模式/角色隔离、输入有界/错误不回显秘密、generic不可变拒绝、手动与周期snapshot/recover/audit、rollback、故障marker与错原版本。为故障注入移除 append-only trigger 的操作只发生在 disposable pytest clone，生产实现不放宽触发器。最终源码/测试 SHA 和终态日志见 `evidence/checkpoint-24-final-tests.txt`。

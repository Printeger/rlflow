# 固定 CPU Runtime：Checkpoint 44

本切片实际执行一个受保护的固定 CPU 程序，打通原来源、登记、真实进程、原 ACK、STOP、回收与资源释放。它不是 Codex/native WorkingPlan 执行器，也不证明任意执行树、模型计费、工程任务或科研闭环完成。完整 Goal 的验收合同不变。

## 交付行为

`FixtureRuntimeOwner` 由保护 startup 绑定同一应用的原 HostPoolOwner、项目 membership 和原 WorkingPlanService；不允许调用者指定程序、命令、目录或重建历史能力。固定 profile 为 `PROTOCOL_CONFORMANCE / LOCAL_PROTOCOL_ONLY`；model、candidate write、delegation 都为 false。程序实际使用原只读 program FD、`python -B -I -S`、精简环境和独立 session，只有固定 CPU 协议行为，无网络/模型调用/后代创建。

原 READY/INTENT、Workspace claim/持有 FD、当前批准/Registry、Budget HELD 与 Pool 原 claim 共同约束登记。Task/Attempt/FixtureLease 的实际身份由原 owner 派生并写入 Budget 事件，不能由 JSON 字符串补齐执行许可；这仍不是通用 Task 调度器或 Dashboard 派发接线。

顺序为：REGISTER_NO_HANDOFF → HANDOFF_UNKNOWN（项目和 Pool 两库 matching）→ gated Popen → PROCESS_REGISTERED + RELEASE_INTENT（两原事件/CAS、同一实际 COMMIT）→ 原 stdin G → 原 nonce/PID/program ACK → STARTED_AS_OBSERVED。G 成功不是 STARTED。两库不冒充原子事务；跨库或提交未知保留原尝试和曝光，不自动补偿、重开 Popen 或接管旧 PID。

身份/release 的原子批次保留两个版本和原事实，逐事件经过 Store 纯转移与原 guard。rollback 保留原 raw；丢 COMMIT 返回后在同一个读事务核两原事件与最终 ReservationHEAD，不用 PROCESS 单项成功推断 RELEASE。放 G 仍在实际 durable 后使用新的权限/来源检查。固定三秒未放行 gate 没有延长。

效应边界和 COMMIT 末尾重核实际 owner/STOP、Controller/Working/Preparation 双钟、consent、bootstrap/plan witness 和 Pool claim 期限。每次实际 mutable HEAD 和原 point/event 重读；仅同一个持有写事务内部复用已证明的历史闭包，不跨事务缓存许可。Pool 的 current/full/cold 检查核实际项目原 BudgetEVENT、whole fact、phase 与 claim/lease/member/pool/epoch scope，合法格式的 hash 字符串本身不是来源证明。

## STOP 与 UNKNOWN

STOP_REQUESTED 在中断和关闭之前写入项目与 Pool，禁止新放行。原 pidfd TERM、有界等待、KILL/reap fallback 和全部原 Source FD/pipe 关闭完成后，才能生成 `FIXTURE_SCOPE_STOPPED / FIXED_CPU_SINGLE_PARTICIPANT` 原 scope 证明；项目真实 wall-only 结算后，Pool tombstone→全部原 slot FD 关闭→FREE。部分关闭保持占额并允许原对象有限重试；旧终态重试不能关闭新 claim 的 slot。

清理权限与新工作权限分离，原安全清理允许在 Controller/批准期限过期后进行。PID 消失、EOF、过期、重启和历史 DTO 不退款。HANDOFF_UNKNOWN 即使没有 PID，也不能从缺数据推断 NO_HANDOFF。`shutdown_safety()` 仅永久冻结并关闭可证的原物理资源，返回 PHYSICAL_CLOSED_EXPOSURE_UNKNOWN，不写终态/FREE、不退款。未知 Popen 身份不接管，不能凭保护程序 watchdog 推断完整终态。

程序不创建后代，因此本次可靠 STOP 仅覆盖固定单参与者 scope；`arbitrary_tree_stop=false`。严格 cgroup/整树 empty、native delegation、模型/data/network/任意候选写的安全门仍待，现有 WorkingPlan.start、CodexExecAdapter.start 与 BOUND legacy 拒绝不变。

## 用量与验收

实际直接 stdout FD 的来源绑定原 Runtime/producer/lease；nonce ACK 不是调用者声明。有限 JSONL 读取、原 prefix/hash、去重与 seal 复用 Checkpoint43。示例 token 数为 synthetic/source-only：缺 usage、错误 ACK、费用均 UNKNOWN，不据此结算模型 token 或 invoice。只有原 owner 的真实 monotonic wall duration 在完整固定 scope 终止后结算；已知超额不裁剪成预算内成功。

新增27个本地用例已逐项执行：真实 gated child/原 ACK/重复 start、REGISTER-CANCEL 互斥、STOP 前禁止 Popen、过期清理、最终效应/COMMIT期限、两事件 rollback/实际 COMMIT丢返回、错误ACK/缺usage、原事件篡改拒绝、snapshot/replay/recover/cold join、Source/slot部分关闭、真实 fork 拒绝继承能力且关闭原FD、STOP 后源文件不再增长。开发失败与定向修复完整保留于 `evidence/checkpoint-44-development-tests.txt`。唯一最终全量实际2160pass/32既有外部skip/1既有warning1751.73s，214冻结输入SHA匹配、compileall/pipcheck/diff通过，详见 `evidence/checkpoint-44-final-tests.txt`；这是上述固定scope验收，不是完整Goal完成。

下一交付应把实际 Runtime 状态和受权 Start/Stop 接入端到端服务/读接口，保留明确 fixture 标签；通用调度、native 执行、工程/科研闭环和长期/UI验收不能由本切片替代。

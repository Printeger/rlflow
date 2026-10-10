# 同认证应用的原共享池纵向切片

## Checkpoint80：原预算与共享池可信消费

`GET /api/v1/projects/{project_id}/finite-accounting` 使用已有认证及原捕获对象，闭合查询，不接受调用者来源路径。原 Goal head、索引 tip、原事件派生余额及任务预留链均须一致；余额为七维六字段的 int64 十进制字符串，前端 BigInt 校验守恒，不使用浮点舍入。响应保留原 entry ID/hash、任务/预留/Goal、epoch、独立版本与读取时间。

池占用来自原持久 claim，不是活跃 PID/GPU 采样；UNKNOWN、死亡或过期未释放 claim 仍占槽。完整核验至多64个原 REGISTER 成员，包括 FREE 历史成员；当前读者允许全部成员项目时才返回全池占用和版本，否则两者均 null，仅显示自身占用。身份/root/文件 inode/注册绑定变化拒绝读取，损坏源返回503而非零。

业务只读不代表文件系统零写入：原 Pool 连接器使用 writer lock、BEGIN IMMEDIATE 和 COMMIT，但不追加事件、不 claim/free；预算事务先退出再读池。两库不构成原子快照。独立双槽读取 executor 包含取消 HTTP 后仍未结束的真实 future，STOP 原控制槽及 latch 不依赖它；物理 STOP 仍可能等待原 Pool 锁，不保证零锁等待。

Dashboard 提供手动读取和当前项目 SSE 高水位的一秒有界合并刷新；其他项目改变池需重新读取，不把历史 as-of 冒充连续实时。坏源清空当前数值为 UNKNOWN、私有版本/身份锚保留；项目/Auth/epoch/logout 清除私有数据，迟到 HTTP 不回填。无新增执行 POST、自动恢复、退款或付费资源动作。费用 UNKNOWN、进程 NOT_OBSERVED、Goal false。

验收：三个后台独立用例分轮通过，Node六项通过；真实 Chrome CPU 消耗/工程执行与正常 Pool 释放、丢启动返回的 UNKNOWN STOP 保留预留和占槽两项通过，必要旧 Dashboard 回归一项通过。隐私差量只复验自身用例，不重跑已通过实际 worker。详 evidence/checkpoint-80-tests.txt。浏览器仍为原固定测试批准/时钟 fixture，不新增安装态或真实独立产品 Reviewer 资格；人工 STOP 的正常案例发生在原 worker 完成后，不证明活跃 worker 竞争停止。下一项真实 Reviewer 需独立隔离/额度合同；不得将本代码审查或机器核验当作 ConditionEvidence。

Checkpoint63，基线62 `816eef3`。关联 T11/T14/T16/T17/T20 的有限固定执行范围；不关闭完整 M2–M5。

交付行为：`create_finite_host_app(host, controls, auth, origin=..., observers=...)` 将 1–3 个已经分别批准、绑定到同原 HostPool 的原 CPU/工程 Unit 控制服务组成一个私有应用。两次批准之前预配置同一个 Auth；不迁移或替换既有 Auth、创建新 grant/lease、调度器或 OS 采样循环。GET/SSE 仅读原证据与显式 SDK 采样的内存 slot。

全部有限捕获、原对象/copy/fork、同 Host/Auth、唯一项目/root/Unit、原 control reader scope/snapshot、cold evidence reader scope/snapshot、observer 原 Unit 身份核对在 app/ControlPool 装配之前。mutable tuple/list 最多捕获四项后校验 1–3；异常集合不部分装配。默认 disabled 的旧 `create_app` 路径不变。

实际验收：同一次 Auth 下，CPU HTTP Run 后 G 前 STOP 使原子进程退出、FD 关闭；另一工程项目 Store/version/latch/spawn 不变、池保留该项目占位 1，它随后实际完成单次候选写入及 AST21，池归零。另一独立运行证明两个原任务都完成、原 body/key 回执重试不再启动/写入、project-scoped bearer 无跨项目读权限和任何写权限。Chrome 同登录两项目切换，CPU384 原数据、工程21 原机器结果、项目切换和注销私有 DOM 清除、CPU STOP 不影响工程均实际通过。

工程详情的 `cpu_ns`、`worker_wall_ns`、`cpu_measurement_scope` 只来自已完整验证的原 terminal `engineering_patch_result.patch`；只读 worker 内核测量至 emit，不包含启动/ACK、候选写入、父进程 AST、回收、整树或账单。原协议允许整数 0..3e9；此次极短工程 worker 确测 CPU 0，保留原值，不制造正数。`actual_cost_status=UNKNOWN`、Review=NOT_PERFORMED、Goal=false、历史资源 NOT_OBSERVED 不变。UI 兼容旧证据三字段全缺，新证据必须三字段齐全且严格类型/范围/scope。

开发失败与修复：首轮 STOP helper 写错原 action（400 而非目标作用域403），更正为原 `CANCEL_FIXED_CPU_TRIAL`；首轮 CPU 测量大于零的测试断言超出原合同，更正为原 0..3e9。r2 STOP 实际通过，双结果最后 bearer 返回值未解包导致 TypeError；修正并只重跑失败用例。失败日志全部保留，不静默跳过。独立 High 对错误 action、装配后才检查控制 reader、无界 mutable capture 三 MUST 静态关闭，未启动重复测试；这是开发审查，不是产品独立 Reviewer。

测试证据见 [checkpoint-63-final-tests.txt](evidence/checkpoint-63-final-tests.txt)。仅受影响冷读/API 回归13项通过，Node12项、Chrome1项通过；不声称本轮全库回归，61/62已通过且未受改动影响的审查和测试不重复。320输入全部匹配，编译/依赖/语法/diff通过。

下一切片：同一有限应用多项目紧急 STOP 的实际闭环，先全范围授权/目标预检、先对全部原 Unit 锁存取消、再逐 scope 原意图/收尾；验证单个阻塞或失败不延迟其他原 scope 的取消，不把部分结果冒充整体成功。不是全产品任意任务树 STOP。

剩余原缺口：可用 native 通用工程/科研 adapter、独立产品 Reviewer 与条件—证据最终门控、严格 OS/任意树、真实 invoice、B1/24h fixture/8h UI、T23干净安装/迁移及后续M5仍未证明。本私有 finite fixture 不是付费模型调用、GPU、生产迁移或发布验收；没有新增权限，USER package-lock 未改未暂存。

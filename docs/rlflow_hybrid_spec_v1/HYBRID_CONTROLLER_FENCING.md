# 持久 controller fencing：仅 Hybrid 核心事实域

Checkpoint35 增量，基于 checkpoint34 `de06848`。这是内部实际 SQLite 组件，不是 HTTP 开关、workspace writer lease、执行准入或 T12 完成声明。

## 实际实现

`hybrid_controller.py` 定义 closed request、不可变 controller fact 和唯一派生 head；`hybrid_controller_service.py` 固定实际 Store、Registry、project/mode/observation epoch、服务 UUID 与 `/proc` PID/PGID/starttime/boot 身份。调用方只传幂等键、预期全局版本与 1–60 秒 TTL，不能传 owner、epoch 或 lease JSON 作为权限。

acquire/renew 在实际 Store writer lock 和 `BEGIN IMMEDIATE` 后读当前原始 source proof、核全局 CAS，再采样时钟并产生事实。一次事务追加 fact、更新 head，初始化时附两项 collection marker；fact 不可修改或删除。renew 保持 controller epoch，成功后旧 head revision 的 token 失效；同 observation epoch 接管必须 UTC 和同 boot 的 monotonic deadline 均过期，controller epoch 增一。UTC 前跳不能跳过真实 elapsed deadline，时钟回退拒绝。新的 observation epoch 只创建新控制 fence，不宣称旧 runtime 已停止。

Store 在新写入、重复回执和最终 `_commit` 前要求实际绑定 service/active guard。原 process/Registry/STOP/epoch/版本在 writer 内核查，renew 的原 predecessor 两种期限在提交前再次核查。未授权调用不能用换 event name 绕过 controller mutation gate。所有 fact 的 `prior_runtime_recovery=UNVERIFIED`、`candidate_write_enabled=false`、`execution_enabled=false`，request 的 authority domain 固定 `HYBRID_CORE_FACTS_ONLY`。

## 原事实与恢复

每个 fact 的原 events 行必须有精确 event type/producer/object hash/version，以及原 fact + 派生原 head 的两对象摘要。source helper 有 raw 256KiB、单对象 64KiB 与共享 ReadBudget 界；拒绝额外 mutation、delete、重复 descriptor、非法 marker、非空 details、浮点 format、错 head、错 hash。只有 INITIAL 允许并要求两个初始化 marker；renew 原事件夹带空 marker 仍被拒绝，不能在 source proof 中丢掉该差异。

当前 head 另核 indexed 原 controller event tip，防止把合法旧 head 重新放回 projection 后生成分叉。`events_type_tip(event_type,seq DESC)` 支持固定 LIMIT 1 查询，不按整个 event ledger 扫描发现 latest。

audit、manual snapshot、periodic snapshot 和 recover 完整 closure 必须核 **at/before state.version** 的原 controller tip。即使快照 hash 重算，删除或清空整个 controller 域仍被拒绝；合法旧 V 快照之后存在新 renew 时，仍按 V 的 tip 验证并正常 replay tail。历史验证不依赖当前 TTL、STOP 或内核 PID 存活。

ControllerToken 是实际签发、由固定 service 的 weak-reference cache 识别的对象；复制、JSON、另一服务实例以及从磁盘 fact 重建的 token 不可用。同键重试只返回原 fact，`token=None`，不续租、不重建 token。调用方必须保有实际 token；丢弃的旧 revision 不被 owner 永久持有。

## 验证与边界

定向测试包含实际双 Store/双 owner 并发 acquire 一胜一拒、renew/expired takeover、两种 clock、PID reuse/boot/config/STOP、实际 token 身份、提交前 predecessor 过期、observation epoch、重启不 adopt、同键差异、原事件 corruption、rehashed snapshot、periodic due 保留及历史 tip seam。全部使用 disposable fixture database；原事件故障注入临时保存/移除 append-only trigger，注入后在调用产品前恢复原 trigger；生产 trigger 未放宽。没有启动 worker、供应商会话、模型、GPU、HTTP 或 browser。

当前 current proof 仍遍历 controller predecessor lineage，单次 reader 有 4MiB/4096 facts 界，超界保守拒绝；它不是常数时间控制 loop 或 NFR06 证明。最多保留 128 个仍由调用方持有的 actual token，丢弃者自动释放；不承诺任意大控制历史长期可用。

尚未接入其它自主核心写入者的统一 AdmissionService，也未排除 legacy dispatcher/experiment/job 路径。Controller 的 acquire/renew 不是工作区独占；不能据此关闭 ARC-01/04，不能把 SQL fencing 当 STOP、writer 清理或 execution release。candidate writer、跨项目资源池、预算 reservation/settlement、真实 OS/model/data capability、可靠 STOP、restart material adoption 和实际工程/科研闭环仍待交付。完整 M0–M5 Goal 保持 active。

最终实际终态：root controller99/5.83s、中央full1296/32既有skip/1warning359.97s、独立High四modules ONCE166/1warning38.34s；11SHA不变、范围MUST闭合、compileall/pipcheck/diff0。source/log hashes 已归档在 `evidence/checkpoint-35-final-tests.txt`；早期失败与修复日志保留，不重标为最终冻结版本。无 live 测试。

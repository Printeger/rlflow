# 累计预算账本：checkpoint37 实际保护端

基于 checkpoint36 `2199f3c`，已新增纯算术、closed ledger、实际Store原字节证明及BudgetService同writer占额/恢复接线。最终root/独立High exact九modules各383项通过（158.84s/159.97s）；中央全量原87325终态exit0 **1513passed/32既有外部H1skip/1既有warning488.35s**，18source/test/schema SHA一致、范围无MUST、compileall/pipcheck/diff0，当前无live测试。详见evidence/checkpoint-37-final-tests.txt。旧36/早期37测试不重标为最终新源码结果。所有执行门仍拒绝；HELD只证明请求估计实际占额，尚无可信AttemptOwner证明完整workload足额，softtokens不是硬上界。

## 账户与原来源

稳定账户使用 project/data_mode/goal_ref，不含合同 revision、adapter、controller epoch 或 observation epoch。七维使用原批准合同字段：model_sessions、model_input_tokens、model_output_tokens、gpu_device_seconds、experiment_starts、experiment_retries、wall_seconds，actual int64 checked 运算。unknown_exposure 是 reserved 子集，available 不再减一次 unknown；降限保留累计曝光，超额显示 overrun，拒绝新预留。

项目派生对象仅累计 consumed/reserved/unknown；当前没有可信 project 总限额来源，不把各 Goal limit 相加当项目授权，也不称主机会话池完成。token 数额是 soft estimate，不是当前 native adapter 可强制的上界；hard_required 的既有能力拒绝不能绕过。

## 实际闭合域

四个 private collections：immutable entries、derived goal heads、derived reservation heads、derived project exposure。一个 closed original事件写 entry 及三个精确派生对象，首事件只附合法 collection markers。entry 保存 prior goal/project/reservation heads 的原引用；派生 head 的 last_entry_key/hash 指向该 entry，entry 不嵌入自身 hash。

event.object_id 使用 stable goal account key，配 event_type/object_id/seq 索引支持 per-goal latest；这不绑定请求内容。input_versions 固定 canonical 三字段 budget_entry_hash、budget_goal_account_key、budget_reservation_id，分别锚定原 entry 摘要与两种 indexed scope，避免只有 scope metadata 而没有原 entry hash 锚点。服务幂等读取必须核原事件精确多对象证明、完整 request/request_hash、原依赖，不能借 generic Store._existing 省略这些检查。只读 attach 不创建新索引；启用 BudgetService 需核新索引 DDL，缺失/变更要求显式升级。

实际 BudgetService 固定同 Store/Registry/Controller/Preparation，沿 owned writer→controller→BEGIN，当前 source/global CAS 及最终 guard 保留到 COMMIT。RESERVE 核实际原准备及当前 Goal/approval；无需以文件 witness 或 BLOCKED Admission 作为执行许可。热路径由先前 projecthead 和本 Goal delta 更新项目曝光，不每次全扫所有 Goal；全审计从 entries 重建所有账户/reservation/project heads，并核 state.version 历史 tip/count、原 sources，拒绝整域、非latest遗漏、多余孤立 head 和非法 marker。历史不依赖今天的批准 TTL。

## 真实占额但不执行

内部保护端接口为 `BudgetService(store, registry, controller, preparation).record(request, actual_token)`，并非HTTP/agent JSON dispatch入口。返回 `{entry, duplicate, execution_enabled:false}`；duplicate是历史回执，即使原HELD已随后取消/UNKNOWN也不重授当前lease。三种closed action使用原global expected_state_version；RESERVE只允许EXECUTION，cleanup指定原reservation_id。Store普通全状态及对象写入不能借事件改名、原幂等键或duck guard绕过actualowner。

Owned COMMIT最终顺序：所有source/head proofs → Controller实际owner/Kernel/config/STOP → 最后UTC/mono sample → 内部无DB/source/filetree IO期限比较 → COMMIT。Budget使用同一最终UTC核人类consent，避免source读取或后续registry hash耗时让早于controller的批准先过期；cleanup不核旧consent当前有效。Admission复用此出口核consent/material UTC及轻量actualWitness mono，不把新预算账本改成执行许可。

首次实际 API 只提供 EXECUTION purpose。FINAL_VALIDATION/RECOVERY 待真实可信任务来源，不允许 caller 任意选桶绕过原批准 finalization fraction。规划 floor 使用该原合同的明确比例，精确 ceil；不是实际已花费，不能默补20%。

RESERVE 足额写 HELD 并实际增加 reserved；不足额写 DENIED 终态 reservation，保存当前批准限额/规划来源但 exposure 完全不变，便于降限 overrun 可追溯。HELD→UNKNOWN 只把该 reservation amount 加到 unknown 子集，不二次扣，不退款。DENIED/CANCELLED 不可复用。

取消仅限实际核心证明 PRE_RUNTIME HELD 且 runtime_registration=NOT_AUTHORIZED，原子不可逆 CANCELLED tombstone，未来 register/release 必须共用该 reservationhead CAS。“没有release行”、缺receipt或 caller NOT_STARTED 不是证据；UNKNOWN 本轮不取消。后续外部 handoff 前须原子记 registration/intent 并进入 UNKNOWN，跨 intent→外部启动→receipt 崩溃窗口不得自动释放。

尚无实际 UsageOwner，因此不开放 caller JSON USED、NOT_STARTED、refund 或 adjustment。纯 settle_known helper 不是服务权限；未来只接受保护端完整 scope/source 证明，累计事件与父子包含关系去重，已使用后失败仍消费，超预留记 overrun，缺 usage 继续保留。correction 必须 append 且幂等，不覆盖历史。

## 验证与未完成项

实际测试覆盖最后额度竞争一胜一拒、原键不同payload拒绝、真实批准revision降限保留曝光/overrun、multiGoal项目delta、controller/observation epoch不归零、DENIED曝光不变、UNKNOWN占额、取消永久性、perReservation最新tip拒旧HELD退款、原metadata损坏/历史遗漏/多余head、最后proof与owner工作后期限/STOP改变全rollback。180000合法literal role_schema（decoded<4MiB、真实blob>16MiB）的reserve/duplicate/UNKNOWN/audit/replay/manual及显式64MiB周期snapshot/recover容量正例通过；不宣称默认32MiB周期维护必满足该病理编码fixture，也不声称硬RSS/IO超时保证。root与独立High定向、中央full均串行且同冻结源码；未调用付费模型/GPU、未写保护项目或线上发布。真实runtime register-v-cancel共享CAS/handoff竞争仍待未来注册入口实现，不把上述preRuntime取消当完整执行生命周期证明。

这不是完整 RES-01/T14、workspace writer/legacy 排除、共享3session池、STOP 或 runtime release。完成实际 ledger 后继续这些门与工程/科研闭环，完整 M0–M5 Goal 保持 active。

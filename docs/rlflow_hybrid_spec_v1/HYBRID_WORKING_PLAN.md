# WorkingExecutionPlan：checkpoint41 非执行实现与设计记录

Checkpoint41 收尾：实际非执行 WorkingPlan 物料→原INTENT→native no-replace物理发布/原成功receipt→真实COMMIT后确认→READY第二CAS及审计/回放/快照恢复已实现，执行权限仍false。冻结59输入的root/High同28模块各886pass/8既有外部H1skip/1既有warning（990.87s/999.93s）；唯一full原86772实际2048pass/2fail/32既有外部H1skip/1warning1312.45s。两处已定位并局部修复：只读MCP写范围旧断言对齐[]；legacy control/scratch嵌套恢复并保护control/checkpoint/journal/transport物料。修复后四模块原75264实际96pass/1warning12.22s，普通/18万literal READY完整closure原51517实际2pass93deselected100.70s，61SHA一致；compileall/pipcheck/diffcheck均exit0。High只做新增安全修复复核，无剩余局部MUST；未重复已通过的28模块审查/复验，未重跑整套full，不虚称修复后全量全绿。所有原失败/日志/SHA保留，见evidence/checkpoint-41-final-tests.txt。无live测试，正在提交；下方LIVE/未实现是保留历史。下一实际共享资源池→可信用量来源→最小E2E执行与可靠STOP，41收尾不扩功能。无paidmodel/GPU/生产迁移/保护workspace写入，USERpackage-lock不stage。Runtime/Task-Attempt-Lease/UsageOwner/共享pool/整树STOP/OS-model-data门及M1/B1/NFR06/24hfixture/8hUI/完整Goal仍未验收，Goal继续。

当前验证覆盖：root/High同28模块各886pass/8既有外部H1skip/1既有Starlette warning（990.87s/999.93s），59SHA一致，独立真实终态exit0。当前副本物料、原INTENT、native成功receipt、原双图物理发布/COMMIT确认、READY第二CAS和各closure均已实际接线；大型18万literal两phase及确认失败/并发原请求包含在冻结测试中。中央FULL原86772当前LIVE，最终full/compileall/pipcheck/提交仍待。下方“未实现/待实际大型终态/旧LIVE”均为历史，不能覆盖此段；仍不授Runtime/执行/预算结算权限，不是完整Goal验收。

最新覆盖补充：实际原owner publication/READY第二CAS现已初接，所有运行权限仍false。原native成功receipt区分已知失败与helper丢返回，原双图仅owner授权rename后重定位rootctime，最终heavy source/fact/graph与时钟覆盖真实COMMIT。发布确认由固定memory-only成功hook在原全部锁内更新单一canonical _published map；异常不ACK，原receipt/attempt保留。大型18万literal schema两phase actual case原29550实际1pass94.89s含全部closure/恢复及READY查重；普通READY原74113实际12pass55.19s。当前16case确认/并发/预算终态回归原16923 LIVE，无41final/full/独立/commit，仍不是Runtime或Goal验收。下方未实现/未接Store及旧LIVE是保留历史设计。

## 当前保护内部 API（不是 HTTP 执行入口）

固定startup先有实际FixtureInstallationService原published material、同Store/epoch的WorkspaceService及其原ControllerToken/WorkingObservation，才能构造WorkingPlanService。以下调用只准备与封存非执行计划：

```python
owner = WorkingPlanService(workspace, installation, original_material)
bundle = owner.prepare_plan(original_token, original_observation, "working-plan-1")
intent = owner.persist_intent(bundle, original_token, original_observation,
                              expected_version=owner.store.version())
ready = owner.publish(bundle, original_token, original_observation,
                      expected_version=owner.store.version())
assert ready["state"] == "PLAN_READY_NONEXECUTING"
assert not ready["execution_enabled"] and not ready["release_enabled"]
```

调用前读取version仅提供明确CAS，不避免竞争；来源、原能力、预算、当前heads或期限变化仍会拒绝。unknown返回保留原bundle/request/raw及known native成功receipt，显式sameowner重试不能换expected版本或刷新原request；该接口不创建进程、消耗模型/训练预算或授lease。私有物理publication使用readonly guard，允许无关core事件推进但必须保持entry captured当前version和全部当前heads；该guard明确不能append任何fact。READY使用调用者明确expected→accepted+1，完整原INTENT仍记录其原accepted版本。

Store audit/replay/manual/periodic snapshots与recover验证两个immutable域的完整原事件形状、元数据、canonical wholefact inputs、first marker和true at-version tip/count，空域也核count。attach_existing只能恢复非执行记录，不能重建进程内owner/material/native成功cap；尚无进程重启后的READY运行许可恢复。普通native模型能力仍由原Registry/受保护census约束；测试中的fake local catalogue/version stub明确不是模型可用或执行验收证据。

最新状态补充：实际INTENT-only已实现；原Working/Controller/Bootstrap短期双FD图、actual sameDB/current HEADs/claims/HELD budget/consent/pending/Kernel及最终COMMIT期限守卫先于原idempotency查重。Store私有双immutable域、原indexed full event/inputs/marker/tipCOUNT与audit/replay/manual/periodic恢复闭合已接，READY仍仅纯域。18万literal schema实际INTENT维护恢复与真实COMMIT后lost-return重复原request在r2通过；该轮37pass1fixturefail，不能称整套全绿。maintenance共享ONE ReadBudget仅在同RO BEGIN内缓存相同(digest,literal)语义，raw descriptor仍逐次计费、每alias expanded bytes/nodes仍累计计费，输出/行数/限额/原deadline保留；SQL projection预取单row cap仍是原max_bytes，累计raw parse拒超额。publication/READY owner未实现，builder.publish/start仍拒绝，不授执行权。当前r3回归LIVE，见开发证据；下方“尚未接Store”等为历史设计。

最新WIP：纯renderer、实际原BootstrapWitness、owned currentWorkspace来源context、独立未发布WorkingExecutionPlan/Bundle和双原FD图witness已经初接并获组件测试证据（见evidence/checkpoint-41-development-tests.txt），不是本设计已整体验收。纯不可变INTENT/READY域正在回归；尚未接Store活写guard、持久两CAS/实际发布/完整audit及恢复。以下“没有41代码”等仅保留40冻结阶段原设计，不表示当前无实现；任何source/material见证仍不是运行或Store写权限。

40冻结回归期间的独立High只读设计；没有41代码、测试或执行许可。40新fixture非执行安装是前置，不是完整T12/Runtime/M1/M0–M5完成。完整Goal持续推进。

## 最小实现切片

新增独立WorkingExecutionPlan、WorkingPlanBundle及固定WorkingPlanService。旧PreparationPlan/Library SnapshotPlan保持原path/hash，不改路径冒充实际working copy，也不给legacy codex_command加skip_guard布尔开关。

从现有native政策渲染逻辑抽出内部纯renderer：固定role/profile/catalogSubset、明确candidate/scratch/control及写集合，输出未执行argv/MCP/native-disable配置字节；不mkdir、读HOME/env、执行version、Popen或网络。旧codex_command保留现有legacy gate和实际version/catalog前置，再调用renderer，不能放宽冷拒绝。Engineer写集合只能由原批准proposal.scope.writable_paths映射到实际Working path，核protected_paths、控制/安装/snapshot隔离及NOFOLLOW inode；禁止空集合默认授权整copy。其他role写集合为空。allowed_tools/command_templates/network仍须原Registry约束，旧任意command CPU MCP不能证明模板执行权限，不把缺口标为VERIFIED。

## 实际能力与当前来源

FixtureInstallationService补原READY point/短期actualBootstrapWitness：当前V>=2仍核原INTENT/READY及tip-count，writer外核原issued物料、原published身份、固定Store/fixture/epoch/DB/release/catalog字节/hash/链，writer内核原core refs/held inventory/最终期限。历史READY DTO不能重建该能力，现有仅fresh两phase Guard不能冒充后续准入。

WorkspaceService补保护内部plan_context：同Controller.token_transaction及writer→Controller→Workspace→Working顺序，实际原slot、双层canonical pending renewal均为空；当前perReservation HEAD为最新ACQUIRED/HELD_PRE_RUNTIME，claim等于原ACQUIRE，observation raw/epoch与当前actual对象相等，Kernel hold核真实持锁。Budget同txn current HEAD必须HELD且NOT_AUTHORIZED、原reservation/entry/head完整point；不信空jobs或历史HELD。完整原Prep历史与fresh MaterialWitness、当前Goal/approval/Registry同scope/config/epoch、Controller原token/fence/STOP均重核。

## 物料与两phase

writer外对实际working候选作有界当前hash观察并构造sealed provisional物料；base snapshot与initial_copy_hash不是今天的working hash。第一次CAS追加immutable WORKING_PLAN_INTENT，保存expectedseal、bootstrap/source/prep/budget/workspace/claim/controller原refs、原Working observation epoch/kernel、实际当前候选hash和映射权限。fixed builder只接受原actual context，不从自由JSON取得namespace/角色。

按原durable INTENT seal用descriptor-relative no-replace发布、fsync；第二次CAS追加PLAN_READY_NONEXECUTING。两次均重核上述当前来源/HEAD/能力/双UTCmono/STOP与无pending，在所有重型proof后由最终sample纯deadline callback紧接COMMIT。失败保留原物料/FD，不改HELD预算或WorkspaceHEAD、不注册runtime、不自动延寿。新private域接Store guards、bounded original full events/markers/tip-count、audit/replay/manual与周期snapshot闭合。

## 必须验证的风险

实际原对象与复制/foreign对象、旧snapshot路径手改、跨Store/epoch/project/Registry；renew/close/新fence/pending未ACK、Budget CANCEL/UNKNOWN、批准撤销/过期或Goal改版使两次CAS拒且原FD保留；物料hash期间实际nonblocking writer可获取；root/mode/symlink/physical alias/批准模板scope越界；失锁/fork/boot改变、最终sourcepoint之后UTC/mono/STOP失效；rename/fsync/COMMIT前后未知返回、原seal篡改与自行move不能直接READY。实际从guarded fixture导入纯renderer构造物料，原冷worker继续拒，绝不调用模型。

旧plan的workspace HEAD/observation epoch变化后只能作为历史非执行物料展示，不能自动复用或延寿；更新应新immutable INTENT。真正model/data/OS资源、全部legacy迁移、host共享≤3 pool、UsageOwner、REGISTER_UNKNOWN-beforehandoff及同ReservationHEAD CAS、实际process-tree STOP和执行lease仍是后续缺口；41所有execution/release维持false，不建第二长期Supervisor。

## 官方资料核验（只读，不代替本机能力证据）

按OpenAI Docs技能核查官方CLI/config/MCP文档：`enabled_tools`是MCP工具allowlist，`disabled_tools`随后应用；`required`使必需server初始化失败时整体启动失败；这些配置不是预算、批准scope或命令模板执行证明。[MCP reference](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)

`codex exec`支持配置override、schema/result输出与隔离模式，`--ignore-user-config`只忽略配置，仍可通过CODEX_HOME认证；不能把这个flag当凭据隔离。`--ephemeral`避免保存session rollout，并不取消运行权限门。[CLI reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli)

本仓库仍绑定实际已核验的CLI版本/原role profile/model/catalog与native census。官方当前文档不证明本机模型可用、所有native tools已禁或运行资源可授；41纯renderer抽取须保留本机确定性parity/registry证据，不升级CLI、不变更已批准模型、不调用provider。当前仅资料/设计变更，40冻结源码未改。

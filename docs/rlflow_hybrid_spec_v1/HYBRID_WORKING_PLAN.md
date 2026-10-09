# WorkingExecutionPlan：checkpoint41 待实施设计，非验收证据

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

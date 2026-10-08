# 开发决策记录

## Checkpoint33：内部 exec 准备不能恢复或启动执行

复用实际 isolation.codex_command 生成受保护的 packet/schema/argv/MCP/masking 物料，不造第二份 native policy。Registry profile闭合、版本锁、明确model/effort、CPU禁网/no delegation；paths/role/config输入及目录身份入plan，签发对象+原内存seal防止篡改后重算manifest。未知/重启物料拒绝，而不是仅凭本地文件恢复。无Store/HTTP/worker/预算/ACK/release；start无条件拒绝，source_authority及所有执行门UNVERIFIED。阶段选择把有限物料机制先确定性验证，再加source-bound持久intent和统一admission；不是用准备状态代替完整T11/T12/T14/T17。16MiB仅最终物料/读取上界，非临时磁盘硬配额；seal不证明候选内容或OS资源。OpenAI Docs用于区分exec和AppServer官方接口形态；不把官方通用说明当本地固定CLI/账号运行证明。见HYBRID_EXEC_PREPARATION.md。

## Checkpoint32：浏览器确认是精确事实同意，不是执行授权

新增独立有界GoalPanel控制状态，公共最后快照与私有合同/nonce/pending分离。auth/observation双generation保护全局401副作用，避免旧请求注销新身份；private ticket拒迟到body。原 server view完整显示后才明确approve，编辑/刷新/较新coreversion使nonce失效，不靠heartbeat续期。条件批准只记录LEASE_VALIDATION_PENDING，lease/OS/实际输入验证另行实现。

不能将JS JSON.parse/stringify当无损人类意图：decoded重复键、unsafe整数及nonfinite先拒绝，合法原proposal字节入包络；incoming proposal/diff若JS不能精确表示则拒绝人类确认。Python canonical/hash保留服务器定义，不伪造兼容编码。一个只读key/body内存意图绑定身份/项目/epoch，response丢失只手动原键重试；CAS409停止，不自动换expected重放。截图测试改每run独占目录，早期旧PNG覆写事实披露但原日志不改。Sites按local-only实现，不注册/上传/托管。见HYBRID_CONTROL_UI.md。

## Checkpoint31：有界原记录证明与部分覆盖不可混淆

新 GoalRecord 的私有 source_command_key 绑定完整原 record/receipt/原 revision head；不改 proposal/request/hash，不回填旧记录。完整 snapshot/recover 对旧新记录都核原对象摘要，避免删除可选指针降级安全闭合。网页旧无指针记录明确 PARTIAL_NO_SOURCE_POINTER，列表明确 HEAD_ONLY；不扫描所有历史获取假“完整来源”。

共享 blob 缓存只减少原始 I/O，不免除展开逻辑字节/节点收费；prepare 与 private review 共用预算。实际 head 必须匹配 proposal，stored ProtocolError 归源503。human operator 或 approver 才可完整 review；viewer/Bearer 仅 head summary。记录批准、期限、新合同适用性分别显示且 execution_enabled=false；逐次读取不宣称完整链审计或 lease 资格。见 HYBRID_GOAL_READS.md。

## Checkpoint30：配置启用不能隐式初始化或升级权限

旧 `load_config` 三元组与prepare viewer-only保持；单独 `load_server_config` 识别closed1.1/明确controls，角色不自动继承写入或批准。全局2MiB读取、旧64KiB接受、每catalog256KiB及项目/credential数上界各自说明，不把新的读取cap说成完全不变。NONBLOCK在fstat前防FIFO阻塞，严格JSON duplicate/nonfinite/depth门同样适用。

不能用初始化型Store(root)兑现无迁移启动；existing-only attach不执行DDL/audit/rebuild/enable，并要求受保护既有文件及WAL/注册/版本一致。列顺序、类型、NULL与INTEGER rowid主键均校验，避免等名TEXT或DESC PK空库通过后首次事件seq失效；逻辑快照与SQL trace证明无业务写，不以main文件hash冒充WAL一致性或绝对零文件变化。数据库/锁inode重绑拒绝，但不宣称同UID OS攻击沙箱。

配置加载后的ASGI HTTP闭环、CLI mock选项、29的真实socket与旧UI/browser/性能证据分开记录。此次不开放执行、不伪造实际用户批准，不完成确认UI、完整安装恢复/B1/长期或整个Hybrid Goal。

## Checkpoint17：测量调用与assert分离

验收驱动不能在优化模式静默省略真实工作。任务no-work调用先执行，再核对结果；history/tasks入口拒绝optimized Python，真实-O负例在任何输出创建前失败。保留r1并重新完整运行任务r2，实际profile与归档业务语义分开。短块CPU分布不替代5min idle，顺序累计RSS不冒充独立control+API RSS。归档10k/真实单轴100k均有证据，后续必须组合并引入活跃工作/实际API与浏览器负载，不以可通过的窄probe缩减完整B1。

## Checkpoint16：历史轴与投影轴分开验收

不把静态“普通写无全history replay”当性能通过。实际Store→observer逐次提交100k公共/控制事件，预定尾200窗口（普通199+一个千次边界）与全100边界分列，不挑快样本或造历史；锁body时长与总耗时分开，direct Reader和维护另测。结果ratio1.041488/完整性通过但限定warm单usage固定cardinality、宽宿主、无并发；原始JSONL随Git保存、DB本地保留、SHA绑定。生产未改，不重复声明新全量/browser执行；下一项依然真实10k任务和活跃工作轴及完整B1。M1_ACCEPTANCE_REPORT明确未过gate，不能用本probe缩减M0–M5。

## ADR-001：保持完整目标和用户授权

附件明确批准 M0–M5，覆盖 CODEX_START 仅批准 M0/M1 的初始建议。遵循完整实施依赖和 PRD 安全条件，不改低验收标准。上级工作区的旧 instinctRL 双角色 Order 不用于本独立项目；用户本次明确授权为任务范围。

## ADR-002：单一需求来源

保留用户未提交的 `docs/rlflow_hybrid_spec_v1`，以相对链接 `docs/hybrid-v1` 提供要求的路径。实施状态新增在该目录，原需求内容不覆盖。系统验证记录另列，避免把需求包验证冒充实现验收。长期可在打包阶段物化链接，但原需求内容必须保持一致。

## ADR-003：增量存储与观测桥

复用已有 SQLite WAL、追加事件、blob 和 projection。Dashboard 不使用完整 `Store.view` / `summaries` 作为热查询；增加有界读模型。新事件 envelope 与旧控制事件 object_version 语义分开，不把角色报告接受当成目标完成，不把 release 前的旧 RUNNING 当作供应商启动事实。观测桥必须在原事务内保存，不建立第二个长期 scheduler。

## ADR-004：能力声明与执行能力分开

本机 Codex 0.161.0，旧隔离实现固定 0.153.4，基线两个 doctor 测试因此失败。先保持 fail closed；不能只修改版本字符串使其通过。新增无凭据、无生成的协议探测；版本/schema pin 仅证明协议声明匹配，不证明 runtime 可以执行。子代理隔离、模型权限、interrupt、usage scope 必须进一步核验。

官方依据：[App Server](https://learn.chatgpt.com/docs/app-server)、[非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode)，核查日期 2026-10-08。OpenAI Docs 技能用于确认接口源；实际准入仍以本机探测和隔离测试为准。

复杂恢复/事件架构使用用户指定 `gpt-6.1-sol`、High effort 的只读独立子任务。主会话统一代码写入；当前主会话的模型/推理设置不能由项目代码修改，不伪称已切换。

0.161.0 修复结果：独立空 HOME census 的实际注册表仍只有三个空 MCP resource 入口与 `mcp__rlflow_cpu.cpu_exec`。更新精确 pin，同时将 census 依赖改成固定非生成模型 catalog，不读取真实账号 cache，清除代理/凭据。`use_responses_lite=true` 是注册表 metadata 的必要配置；配置和注册表哈希随 doctor 保存。原 native tools 禁用、Landlock/seccomp、模块范围、只读 Reviewer 均保留；真实模型不使用 fixture catalog 回退。

## ADR-005：观察对象 ID 与预算可信度

公共对象 ID 统一使用 source ID 的 SHA256 引用，防止语法正确的凭据泄露与 `ref_` 碰撞。公共正文白名单输出且有界，quoted secret（含空格、转义、截断）完整脱敏；源码原值仍在受控旧投影中。缺少或不一致的 usage 不宣称 KNOWN，费用始终 unknown，直到有独立账单依据。

## ADR-006：有界读模型与断裂拒绝

公共对象采用索引 tuple keyset 分页，snapshot 仅返回 30 个对象和增量 counters，其余分页查询。旧日志不嵌入事件。观察事件按不超过 200 个对象拆批、不丢已提交变化；同事务 counters 包括本次归零记录。计数状态正规化成有限集合以避免无界增长。只读 reader 校验源投影版本、outbox MAX(seq)、序号连续与 envelope 序号；不一致要求 resync，不用静默空状态冒充 LIVE。
# 2026-10-08：T06 本地只读服务基础

冻结回归揭示既有 command guard 默认使用子进程 TMPDIR=scratch，角色可伪造控制标记。修正为 trusted caller 的外部私有 artifact 目录；不削弱 Landlock/seccomp，禁止额外 scope 覆盖控制目录。自动临时清理必须等待 supervisor+guardian 两种绑定身份 quiescence；未知状态保留诊断目录，不能以临时文件整洁为由删除活动恢复证据。owner-death 测试强化等待可信 writer，而非固定 sleep 或忽略 rmtree 错误。

沿用 Python 控制核心，新增 FastAPI/uvicorn，仅通过 ObservationReader 查询已经显式启用的同库观测投影。Web 请求不能实例化 Store/迁移/启动 scheduler；provision 是独立 trusted CLI 的显式动作。M1 暂不提供写命令或 artifact API。

使用纯 ASGI 同源 middleware，避免 BaseHTTPMiddleware 内部流队列截断真实 socket-send deadline。默认 session 15 分钟、viewer Bearer 至多 5 分钟；cookie 和 Bearer 不可互换；Agent 不能收到 approver role。每个 BEGIN 内校验项目身份与模式，而不是仅在路由入口先读 head。

SSE 单事件预取、32 帧/4MiB queue、8 流；heartbeat 不写 durable id。健康历史补齐不因批次大于 queue 被错误断开。slow client resync+close；socket 已阻塞时直接 timeout close，由 Last-Event-ID 恢复。没有为得到“实时运行”而将 ROLE_IDENTITY 或 heartbeat 当作业务 RUNNING 证据。
# 2026-10-08：启动观测的证据语义

START_ACK 写于 exec 前，故仅公开 CLI_RELEASE_ACK/startup_released_at，不能填实际 execution.started/started_at 或升 RUNNING。observer 在 trusted core 中采集，不在 Web GET 中读取私有启动文件或写 Store；短命事实在 receipt acceptance 前再次采集。完整绑定与事务再检查，不因当前 PID 已终止、批准已变化或 STOP 已发生而抹掉合法历史事实。无效 optional proof 仅显示观察不足，不阻断核心事务。

## 2026-10-08：本地只读 UI 与认证生命周期

沿用 Python 服务和无构建 ESM，不增加外部部署、云存储或第二个写入服务。Sites 技能用于 local-only 预览与 browser QA；本机 portable Chrome 在 sandbox=true/disable-gpu 下运行，Fixture 明确标识。纯 reducer 不读取时钟或权限，业务变化仅来自已提交 domain，heartbeat 只更新连接/同步时间。公共分页增加事务内 cursor/project/mode，拒绝迟到页复活已删除对象。

静态 shell 匿名可读但无业务内容；认证 identity 重新确认时清空全部旧 DOM/缓存/details，而非只设置 state=null。认证 ticket+AbortController 与项目 generation 分开，注销时先失效迟到响应。口令原生 fallback POST，CSP form-action self；全部业务文本 textContent。每个详情读取同事务绑定 project/epoch/seq/eventID/digest。对象总缓存 200，保留最近至多 30 execution/10 stage 防止无关任务洪流隐藏执行，紧凑事件摘要 200，不缓存 200 份最大 envelope。未接入的费用、授权条件、日志、资源明确 UNKNOWN/未提供，不能以 Fixture UI 通过宣称 M1 完成。

## 2026-10-08：虚拟化与日志公开边界

事件DOM采用固定64px虚拟窗口，阅读ID/偏移与真实事实分开，geometry不能推进cursor/计数。后台/静止不运行空闲动画；scroll/resize仅按需显示。原始模型JSONL含reasoning/MCP args/results，不能用正则脱敏后整体公开；公共日志下一步先接入明确CORE_STATUS模板并同事务绑定domain lineage，之后工具metadata需单独trusted request/release绑定，私有stdout/stderr不绕过公开策略。具体尚未实现边界见PUBLIC_LOG_IMPLEMENTATION_NOTES.md；不是缩减完整日志验收。

## 2026-10-08：公共日志实现与恢复拒绝

CORE_STATUS日志同原public event事务提交，不新增调度器或模型调用；正文仅opaque ID/对象版本/有限状态/固定模板，不复制任何自由文本。不从core数据库状态推出generation/request/执行活动，工具日志以后独立绑定。日志游标固定high-water与filter hash，独立于SSE消费位置。普通列表信任同事务compact witness并验证其hash/元数据/source digest；lazy正文再验证实际source bytes和重构模板。过滤命中逐个public envelope核验membership/severity，避免不受限批量最大事件加载。

append-only refs增加INSERT成员/severity guard；只读路径仍防御异常索引与缺log/source。初始化和reader检查三日志表闭合，all absent才允许显式旧库启用；部分缺表拒绝，不自动创造空refs使历史覆盖假完整。未过滤keyset仅对本次窗口验证连续性与floor，不扫描全部历史。真实资源/工具metadata/日志UI与M1长期gate继续保留，不以该status log切片取代。

## 2026-10-08：日志显示与业务消费隔离

公共日志页固定high-water，单页50条替换而非无界累计，虚拟DOM与SSE消费位置独立。SSE新增仅显示可能不匹配筛选的提交数；改变过滤必须读首页，不借日志滚动修改domain cursor。正文只在用户选择后读取，list/detail serial处理乱序，身份/项目/epoch清理隐藏dialog的内容而非仅close。同项目刷新失败保留已验证页，明确OFFLINE；不为资源/工具未知提供模拟数据。

## 2026-10-08：工具provenance与执行authority分离

先在现有可信CPU工具链增加闭合request/generation指针及private return fact，不将原始events.jsonl/命令输出公开。PREPARE context只绑定身份，不声称已release；返回state不声称STARTED/RUNNING或成功。result先提交、fact可幂等补齐且无伪造的绝对发生时间，intent-only不重执行。后续collector必须独立对照DB release/session、request与startup proof、实际permissions；逐工具STOP/授权marker另属受控runtime安全门槛，不由provenance替代。

## 2026-10-08：REGISTER优先于工具副作用

只在返回后append journal会漏掉result已提交而通知前崩溃的命令。因此以执行前durable REGISTER建立后续pending发现key，返回通知非正确性依赖；未来core bounded indexed pending轮转，不glob目录。目录入口与journal均fsync后才执行。fd reader保存source identity+offset/checkpoint链，partial/替换/破损不能静默归零；登记当时缺launch witness不能事后补release授权。private发现协议见TOOL_DISCOVERY_PROTOCOL.md。

## 2026-10-08：工具ledger沿用core事务与恢复

不建立第二个DB/控制writer：optional closed tool_sources/receipts/scan走Store对象事务、projection_status索引、append-only event与replay。热view必须排除ledger全keys，完整audit比较replay；legacy callback不改private集合。完成状态与证据验证分开，UNKNOWN pending不能因null witness提前移出索引；fair游标要有revision/round，防止位置循环复用旧幂等key。验证绑定被冻结request/当时release而非当前授权或PID活性；正常历史不因撤权失真。容量上界对齐producer Unicode字节，超限unsupported不是corruption。公开投影在下一切片显式闭合，不自动把私有事实塞进CORE_STATUS body。

## 2026-10-08：冻结工具返回的任务关联

公开工具筛选不能从当前session追认历史task。首次VERIFIED返回在原collector事务保存request.task_id，request对照DB且提交CAS覆盖task_id；旧COLLECTED缺字段保持未知、UNVERIFIED不添加。ToolLedger字段optional兼容旧事件/replay。公共转换必须独立闭合，不把private receipts直接加入通用观察allowlist。该前置不启用公共metadata或新authority。

## 2026-10-08：工具返回公共转换与覆盖

专用closed promotion只取已提交可信receipt；PublicObject通用/工具变体互斥闭合，SHA是trusted core内部一致校验而非抵抗同权限恶意DB writer的签名。新validation_version=2绑定task，旧v1不追认。只读API/UI同步新kind与TOOL_METADATA模板，工具返回不表示模型启动/成功/authority。

工具feature公开起点与event retention floor分开。优先live-only，不隐式回填旧COLLECTED；public_tool_meta缺失/损坏却已有旧公共工具状态拒绝重新初始化。工具日志与CORE_STATUS分同事务观察batch，原模板/count状态解释逐字段保持不变，共享refs验证task/execution筛选。资源telemetry以后必须独立sample ID/时间，不占durable业务seq。
# Checkpoint13：资源观测旁路与freshness

## 后续28：批准事实的live信任与历史真实性分开

最终28：root/独立各207定向及冻结full795passed/32既有skips/1warning/255.47s已终态，四项范围MUST_FIX关闭；见HYBRID_APPROVAL_FACTS.md及证据。以下候选/最初设计状态保留为过程，不是当前仍待实现事实服务或仍live声明；下一HTTP/UI桥与lease/执行尚未实现。

候选实现补充：live 已接 Store 固定 owner、实际 issuedguard 与服务本次 staged request/fact 摘要，不能单凭真正 AuthGuard 编造 future consent；nonce 容量/读写共锁，绑定 token/session 而非 human ID。历史 witness 必须核原核心 payload 中 fact/receipt/原 head 三摘要，单核 request hash 不能防日期平移和重算快照自 hash。周期来源读取复用既有预算。root r5 原93936终态207passed12.82s；独立复验/新全量尚待，不把旧762重新归于新源。详见 HYBRID_APPROVAL_FACTS.md；下段保留最初设计时状态，不覆盖候选最新事实。

live必须由Store启动绑定的AuthStore核实际签发guard identity及主体，generic human JSON/producer/check不能伪造；当前已实现issuer membership helper，尚未接入事实写入。ApprovalService固定Store/Auth/Origin/Registry/project，由server确认精确revision/hash/diff、完整scope/config、Store epoch、全局expectedversion和有限期限；私有nonce绑定真实session，仅成功commit后记消费，持久confirmation_id防同nonce换idem再批准。合法retry查原receipt/原事实且新鲜认证，不依赖重启前noncecache，不续期。批准不改DRAFT或自动READY，撤销另追加；历史恢复核原registry witness和coreevent，不能因当前expiry/session/config变化否定过去事实，也不自动恢复执行许可。已知不能保证hard_required按RES-04拒绝；UNKNOWN仅允许清楚标条件性同意且不可执行，lease前实际preflight不能跳过。该设计不是已经完成批准事实/路由/执行。

## Checkpoint27：Store→Auth顺序解决等待期间撤销，不复用先行Access

可信服务guard factory只在writer+BEGIN后进入，Auth锁覆盖实际commit，紧邻提交再次验clock；等待writer期间不持Auth锁，避免阻塞撤销。实际token/session锁内查human/approver/project/CSRF，不接caller Principal/Access为凭据；duplicate仍fresh check并关闭只读txn后退出，不重写或续期旧fact。异常rollback包含core/public表；同进程单Auth owner明确，不冒充多进程一致性。Origin/精确确认与批准事实另由下一固定服务完成，此primitive不授予执行。root+High112相关回归通过，中央Store full62752已终态762passed/32既有skips/1warning/247.08s。后续guard内不得调用非重入Auth方法或反向获取Store锁。

## Checkpoint26：先冻结可信注册内容，不将内容匹配解释为执行准入

新增独立纯Registry，不接写路由/执行器，protected-startup配置canonical bounded copy至immutable bytes。五binding域隔离含project/mode，dataset域含评价rules；scope_hash绑定整proposal+整config及policy，使只变policy也使旧确认失效。参数schema仅check_schema，不加载远程ref/运行argv；network三层subset、dataset access精确匹配，protected不可降为READ_ONLY。OPAQUE profile/policy configuration只绑定内容，不将未知能力当允许；数据版本仍须后续adapter核验实际来源。下一ApprovalService须服务自持catalogfresh resolve+真实human session，不接caller attestation或Principal当批准。root/High130回归，无剩余MUST_FIX，旧全量/性能不重标；完整T09与M1–M5保留。

Checkpoint22在新独占同档案保留旧失败，真实300s daemon CPU0.849998%且显式baseline精确独立复算。只评价三项view-elision合计观察，不个别归因/不主张显著性，不由CPU子阈值解除全仓库轮询/API+B1/长期及完整目标；源未改不重跑已绑定614回归。见IDLE_PERFORMANCE.md/evidence。

Checkpoint21保留generation原首行，仅无候选closed hint否决时跳过inner完整view；实际候选必须重新正式读，不使用早门对象或改变权限/预算。四种实际状态变更拒绝验证，独立High关闭范围问题。三项视图优化只在新一次实际测量评估合计效果，不据614绿推断CPU。见CHECKPOINT_21.md。

Checkpoint20选择closed标量/list早门，同BEGIN解blob+strict type与owned reader close；非授权、不增enabledgate，仅替换outer原view，pending/release/inner/generation全保留。独立审查发现inotify不能覆盖mmap/远程/挂载覆盖，所以未直接用事件缓存代替原监控；后续必须解决真实工作边界的完整验证。见CHECKPOINT_20.md。

Checkpoint19采用显式兼容return_view选项，仅daemon丢弃尾view；不重构ObjectMap/legacy交易语义、不删任何reconcile步骤。实际observer验证采样推进但业务不变，baseline修复仅未来日志。见CHECKPOINT_19.md；剩余dispatch/control watcher独立实施，不能由600全量绿替代CPU/B1验收。

保留唯一控制权威：资源采样采用独立latest-only SQLite slot、不入业务events/outbox；同writer lock非阻塞+SQLite timeout=0，竞争丢样，不等待业务30秒锁。indexed active keyset每批32、公平轮转；per-session heartbeat witness独立索引持久化且有界GC，不用易淘汰的单批RAM/map冒充完整高水位。首次/丢witness须实际counter+clock前进才confirm；latest读取累加age并核验当前session binding，修正采样停止或generation变化后的错误freshness。HOST、STATE_FILESYSTEM、SUPERVISOR_PROCESS明确分域，GPU来源未实现为UNKNOWN/null；FRESH不是model STARTED。SSE/UI随后集成，后端切片不作为M1完成门槛。接口、边界及High修复见RESOURCE_TELEMETRY.md/CHECKPOINT_13.md。

## Checkpoint14：可丢弃遥测与因果 freshness

critical domain/control保持原FIFO；optional source独立task和单latest payload槽，共享byte cap，不让可丢弃来源失败/序列化失败中断durable追平。增龄基准在query前，选送时补偿query/queue elapsed；网络时间不能精确观测不承诺零延迟。原采样source_state_version是因果下界，不是领域seq，也不能事后读取新head贴版本；旧槽缺witness时null/workerUNKNOWN，保留原body/digest。UI使用snapshot/domain全局O(1) execution barrier，宁可短暂全批UNKNOWN，不维护无界ID版本表、也不让较新sample_seq解除旧generation屏障。资源更新只渲染独立面板，不产生业务动画/计数/历史曲线。见CHECKPOINT_14.md。

## Checkpoint18：有限daemon测量保留未达标证据

Checkpoint18补充：严格allowlist只读备份100k fixture历史，再事务增加10k归档task，不由label暗授调度权限。使用独立Python wrapper的PDEATHSIG与完整父身份前后检查，不用多线程父中的preexec_fn；所有启动后打印/测量均在直接child cleanup finally。源码冻结单次300s真实daemon结果1.773328%单核CPU，未达目标，不改阈值或混用API/B1证据。全仓库watch仍违反NFR06独立条件；下一优化保留同read事务/授权/STOP/prepare前后generation。first基线未序列化明确披露，raw rows独立计算亦未达标，下一driver修复不篡改本次证据。见IDLE_PERFORMANCE.md。

## Checkpoint25：新增显式1.1，不把研究类型替换成数据集假设

新增独立urn/schema_version的proposal1.1，保留1.0原字节/hash/验证；工具（空为none）、5个registry/profile hash、dataset ID/version/purpose/access与冻结rule ID/hash必须明确声明，仍是不可执行DRAFT。High基于CTL-02/CTL-07/§5.2/EXP-02指出PRD并不强制每research拥有注册dataset，因此删除初始跨字段收窄，任意Goal可明确NONE并不伪造数据引用；REGISTERED模式仍非空。实际方法确需数据但声明NONE时，后续approval/adapter必须拒绝，T19不能拿NONE作metrics证据。声明hash不是可信注册表核验、路径不是dataset引用；旧draft必须新建版本补齐，不能静默回填默认权限。command/HTTP/skill入口尚未升级，不拿内部DRAFT测试代替可信交互。

## Checkpoint24：按显式前置推进私有合同基础，不提前开放执行

T09的前置是T01/T03，不是完整M1退出门槛；IMPLEMENTATION_PLAN§3亦说明顺序不要求全部串行。选同一Store三optional私有集合，不复用legacy package goals或approval，不新增initial marker或第二Store；只实现不可执行DRAFT/内容绑定幂等/不可变revision+原receipt/CAS head。新增事务、回放与完整snapshot（含周期maint）转换/closure校验，避免只在便利函数验证。原schema1.0的tool/evaluation缺口明确保留，不能默认补权；下一schema修订与可信human批准必须精确确认且执行层仍等待STOP/lease/隔离。M1/B1/长期和M2–M5完整Goal不因此变为通过。见HYBRID_GOAL_DRAFTS.md。

## Checkpoint23：先闭合 HTTP 测量证据，不修改性能合同

新增独占fixture单writer/父-owned readonly loopback API有限驱动，默认生产SSE配置，双独立consumer各真实重连，并发bounded snapshot/page。绝对发行计划保存完整分母与lag；逐计划write/连续核心version/非duplicate/至少一个outbox来源覆盖，允许一对多，不用客户端与现存outbox相等掩盖bridge遗漏。异常保存有界public帧/原因并立即传播，正常cleanup之前核对API存活，异常/强制KILL拒绝成功；父死亡SIGKILL防uvicorn graceful延存，正常TERM-reap。异步finally先回收API再等待executor，不宣称取消线程写回滚或硬deadline。提交调用→HTTP帧上界与DOM可见/真实commit区分；实际单档案32s数据不代替完整B1/NFR/M1/长期。见HTTP_PERFORMANCE.md。

## Checkpoint15：移出周期性全状态构造

选择兼容完整快照的两阶段维护：core 第1000次写同事务只标记 due；单个可选线程从一致只读事务构造/validate/hash，非阻塞 writer 事务核对 immutable tip 后原子发布快照与 acknowledgement。新版 due 不被旧构造清除，不新增业务事件或第二个控制 writer。增加 marker 部分索引，不据此声称 ObjectMap 全 key 枚举已经解决。首次缺表迁移与已有槽损坏严格区分，实际 BLOB 正文核验，不信摘要列独自证明完整。保留显式手动 snapshot 与原恢复格式。暂不直接引入 chunk 格式，减少对既有恢复合同的同时改动；full-state RSS/WAL/协作 deadline 非硬时限的限制明确保留，B1 必须另测。见 SNAPSHOT_MAINTENANCE.md。

## Checkpoint29：可信写桥不复用先行Principal或旧命令权限

最终29补充：root/High289定向与冻结full原10082exit0/867passed32既有skips1warning267.24s终态，source/log SHA及确切证据见evidence/checkpoint-29-final-tests.txt。下段“full运行”保留为过程，当前无live测试；仍非执行授权、完整T16/M1或Goal完成。

operator和approver使用独立issuedguard type/membership，不为提交DRAFT临时加批准role。protected startup固定服务/Store/Auth/项目/模式/epoch，writer等待后实际session重新核验并锁覆盖commit；bound旧whole-state入口先于_existing拒绝Hybrid服务事件，普通/幂等与改名写集合都不能绕过。legacy未bound内部DRAFT仍兼容，oldreceipt/request/hash不回填。

command1.1单独URN/closed仅submit_goal、approve、revoke；HTTP sharedcontrolkey绑定actor/project/mode/clientidem，三个action共用核心unique event key而非另建影子账本，客户端JSON不得指定actor、root、Registry或service。Core Store必须实核global expectedversion与goal/authority revision，server precheck不能代替CAS。默认create_app/control_services=None及旧CLI1.0仍RO，不因工具更新自动开放user批准。

同源session/CSRF+角色、bounded JSON与actualfuture容量保护真实POST；client断连不是rollback，不提前释放；命令DTO只显示原fact as-of/version且执行false，不公开raw witness或误判现时批准。旧同源middleware仅对opt-in控制错误输出统一Error，旧RO合同保留。合法Registry50k结构读取容量错配已修，有限4MiB读取包络涵盖原literal编码约6x与重复读取；合法literal组合是保守容量回归，不虚称已复现旧2MiB失败。CAS摘要只返回授权的一致current_version，前后scope复查并拒绝corrupt类型；source失败sanitized503而非client验证或版本冲突。

root/High289目标回归通过，actualsocket断连及正常owned回收是证据，不声称writer仍阻塞时下线/UI/安装/lease/真实工程科研/M1完整证据；新中央全量原10082运行。后续直接推进可信配置安装、proposal/authority公共桥与确认UI，再STOP/fencing/runtime/实验，不把首切片当完整T16或Goal。

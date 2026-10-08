# 开发决策记录

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

保留唯一控制权威：资源采样采用独立latest-only SQLite slot、不入业务events/outbox；同writer lock非阻塞+SQLite timeout=0，竞争丢样，不等待业务30秒锁。indexed active keyset每批32、公平轮转；per-session heartbeat witness独立索引持久化且有界GC，不用易淘汰的单批RAM/map冒充完整高水位。首次/丢witness须实际counter+clock前进才confirm；latest读取累加age并核验当前session binding，修正采样停止或generation变化后的错误freshness。HOST、STATE_FILESYSTEM、SUPERVISOR_PROCESS明确分域，GPU来源未实现为UNKNOWN/null；FRESH不是model STARTED。SSE/UI随后集成，后端切片不作为M1完成门槛。接口、边界及High修复见RESOURCE_TELEMETRY.md/CHECKPOINT_13.md。

## Checkpoint14：可丢弃遥测与因果 freshness

critical domain/control保持原FIFO；optional source独立task和单latest payload槽，共享byte cap，不让可丢弃来源失败/序列化失败中断durable追平。增龄基准在query前，选送时补偿query/queue elapsed；网络时间不能精确观测不承诺零延迟。原采样source_state_version是因果下界，不是领域seq，也不能事后读取新head贴版本；旧槽缺witness时null/workerUNKNOWN，保留原body/digest。UI使用snapshot/domain全局O(1) execution barrier，宁可短暂全批UNKNOWN，不维护无界ID版本表、也不让较新sample_seq解除旧generation屏障。资源更新只渲染独立面板，不产生业务动画/计数/历史曲线。见CHECKPOINT_14.md。

## Checkpoint15：移出周期性全状态构造

选择兼容完整快照的两阶段维护：core 第1000次写同事务只标记 due；单个可选线程从一致只读事务构造/validate/hash，非阻塞 writer 事务核对 immutable tip 后原子发布快照与 acknowledgement。新版 due 不被旧构造清除，不新增业务事件或第二个控制 writer。增加 marker 部分索引，不据此声称 ObjectMap 全 key 枚举已经解决。首次缺表迁移与已有槽损坏严格区分，实际 BLOB 正文核验，不信摘要列独自证明完整。保留显式手动 snapshot 与原恢复格式。暂不直接引入 chunk 格式，减少对既有恢复合同的同时改动；full-state RSS/WAL/协作 deadline 非硬时限的限制明确保留，B1 必须另测。见 SNAPSHOT_MAINTENANCE.md。

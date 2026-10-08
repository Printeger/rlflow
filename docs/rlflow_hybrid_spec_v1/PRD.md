# rlflow Hybrid 与实时 Dashboard：需求与开发规格

**版本：1.0 · 状态：建议开发基线 · 日期：2026-10-07 · 默认显示时区：Asia/Taipei**

**一句话定义：在 Codex 中表达目标，由 rlflow 持久控制授权、预算、证据与恢复，借助受约束的 Codex 执行能力自动推进，并用真实事件驱动的网页控制台展示全过程。**

本文件规定目标产品，不代表这些功能已经存在。文件中的性能数字是拟议验收目标，不是现有系统实测结果；配置示例与事件样例是测试夹具，不构成真实运行授权。本文不批准调用付费模型、运行 GPU 训练、修改生产状态或扩大任何既有权限。

## 0. 文档约定与依据

### 0.1 规范级别

“必须 / 禁止”是发布门槛；“应”是默认设计，偏离需要 ADR（架构决策记录）；“可”是非强制扩展。P0 是首次可用版本的必要条件；P1 是后续增强；P2 是明确延后。M0—M5 表示开发里程碑，不是对用户暴露的产品模式。

需求编号按领域划分：UX（交互）、ARC（架构）、CTL（控制）、RUN（执行）、RES（资源）、DAT（数据）、EXP（实验）、UI（界面）、SEC（安全）、OPS（部署）。验收用例编号为 A01—A36，见第 20 节。开发任务与依赖见 `IMPLEMENTATION_PLAN.md`。

### 0.2 已核验的事实与本次设计决策分离

| 项目 | 核验结果 | 对本需求的影响 |
|---|---|---|
| rlflow 基线 | 读取的默认分支最新提交为 `90fd977f0ebcd3d00a5ce50c64f7ecb9a5009dae`，提交日期 2026-09-15；架构是确定性调度、短会话、事件账本及独立进程监督。[S01–S04] | 增量迁移，不另建第二套长期调度系统。开发开始时重新确认本地 HEAD。 |
| Codex 接入 | 官方文档提供非交互 JSONL、结构化输出，以及 App Server 的线程、轮次、通知和审批接口。[S05–S07] | 将供应商接口隔离在版本化 adapter 中，不假设 CLI 文本是稳定协议。 |
| 原生子代理 | 官方文档提供自定义角色与并发配置；具体运行环境能否强制权限、观测全部子代理，仍需集成验证。[S07] | 能力探测通过才启用；不能以提示词冒充权限隔离。 |
| live-panel | README 说明其动画机器是时间函数，可通过 `seek(t)` 重放，正常浏览器由 `requestAnimationFrame` 驱动。[S09] | 只借鉴视觉语法；业务状态和计数必须来自真实事件。 |
| 视觉许可 | 项目声明代码为 MIT，但复刻示例的视觉设计不在同一授权范围内。[S09] | 自行设计 rlflow 布局、图标和品牌，不直接复制示例整体设计；复用代码时保留声明。 |

来源详情与读取日期见 `SOURCES.md`。不把此前对帖子、模型代号、Jev 或 Codex Goal 的讨论当成已验证的接口合同。本版不依赖 Jev、不硬编码 Sol/Luna/Astra、不以 Goal 模式可用为前提。

## 1. 产品目标与非目标

### 1.1 必须解决的问题

用户长期开发同一个项目时，能够提供目标、验收标准和资源范围，系统在授权内自主完成“计划—实现—验证—独立评审—执行—分析—决定下一步”。切换项目不需要重新设计工作流；关闭聊天或浏览器不应丢失任务；训练结束后不需要用户手工提醒“现在分析结果”。

用户应能迅速回答：现在做什么、为什么这样做、谁在执行、依据是什么、还剩什么条件、资源用了多少、是否需要我介入。系统必须允许明确停止，且不能把“请求已收到”冒充“进程已停止”。

### 1.2 产品成功指标

| 指标 | 定义与采集方式 |
|---|---|
| 无人工干预完成率 | 在初始授权后，无额外人为修复的验收通过目标数 / 已开始目标数；按工程、研究任务分层。 |
| 每目标人工介入次数 | 产品决策、权限扩大、故障救援分别计数；例行查看不算。 |
| 验收通过目标成本 | 实测模型 usage、可核算费用、CPU/GPU 时间、人工介入；未知费用单独列出。 |
| 无信息重复率 | 未增加证据、重复相同错误指纹或同一实验身份的尝试占比；有意多种子重复不计。 |
| 恢复正确率 | 故障注入后不重复昂贵执行、不漏结算、不接收过期结果的比例。 |
| 界面可信度 | 抽查界面状态、计数、事件与权威记录一致；无来源的进度或费用为零容忍缺陷。 |

不把“Agent 数量更多”“运行时间更长”“动画更活跃”作为成功指标。成本改进必须在独立验收通过率不下降的前提下比较。

### 1.3 非目标

本版不建设通用多租户 SaaS、分布式训练平台、多人协同 IDE、浏览器内完整终端或第三套 Agent 框架。不重做 Codex 模型工具循环、通用代码搜索、通用会话压缩或原生子代理实现。不承诺研究一定收敛，也不把预算耗尽、负结果或证据不足包装为成功。

## 2. 用户体验与交互入口

**UX-01｜单一自然语言入口，P0。** 在 Codex 中提供一个 `rlflow` skill，通过 `$rlflow` 或自然语言触发。示例：“在现有项目中改善训练稳定性，先给出范围和预算提案，批准后自动推进。”`$rlflow` 是待实现的 skill 名称，不是现有内置命令。Codex skill 的入口机制有官方依据。[S08]

**UX-02｜不暴露双模式，P0。** 用户不选择 Managed/Native 或新旧 executor；底层执行适配器由安装配置、兼容性与能力探测确定。管理 CLI 仅用于初始化、诊断、迁移和恢复。自然语言客户端、CLI 和 Dashboard 必须访问同一服务与状态。

**UX-03｜一次批准、范围内持续推进，P0。** 首次呈现目标、不可改验收条件、可写范围、保护路径、允许命令模板、资源上限、停止规则及敏感动作。范围内普通开发自动继续；范围外变更生成差异明确的新提案。不得在未批准时先启动工作再补审批。

**UX-04｜用户介入最小化，P0。** 仅在无法由现有事实解决的产品选择、权限扩大、不可逆动作、资源扩容、身份不明或证据冲突等情形询问。环境可恢复的非敏感故障，在既定重试政策内自动处理，不要求用户逐步派工。

**UX-05｜多项目复用，P0/P1。** P0 支持一个服务管理多个本地项目、切换查看、逐项目账本和权限；主机资源池跨项目统一计量。跨项目高并发与多主机调度为 P1/P2。配置切换不能归零总预算。

**UX-06｜手机可用，P0 基础 / P1 完整控制。** P0 响应式查看、清晰的离线状态；P1 在可信远程接入上提供批准、暂停、恢复、停止。保留现有 Ubuntu 主机与 Docker 开发环境，不要求迁移工作区。手机直接暴露任意 shell 不在范围内。

## 3. 总体架构与不可破坏的不变量

### 3.1 职责划分

```text
Codex 交互会话 / Dashboard / 管理 CLI
                │ 同一查询与命令合同
                ▼
        rlflow 服务与确定性控制核心
        ├─ Goal / Contract / Authorization
        ├─ Policy / Budget / Evidence / Progress
        ├─ Task DAG / Execution lease / Recovery
        └─ Durable events / Read projections
                │ 已授权的有限任务
                ▼
        Runtime adapter → Codex 执行会话
        ├─ 按需 Explorer / Researcher（只读）
        ├─ Engineer（唯一写入者）
        └─ 独立 Reviewer / Critic / Designer
                │ 结构化建议与结果，不是最终授权
                ▼
        核心校验 → 实验 Runner / 下一任务 / 完成门控

权威事件 → 投影与 SSE → Dashboard reducer → DOM/SVG 动画
```

图中的层是逻辑边界，不要求每层一个独立部署服务。推荐初版仅“控制进程 + API/静态页面进程 + 按需 worker/实验进程”。

### 3.2 关键架构决策

| 编号 | 必须成立的规则 |
|---|---|
| ARC-01 | 每个工作区在任何时刻只有一个有效控制权持有者；lease epoch/fencing token 防止旧控制器继续派发。 |
| ARC-02 | 模型只建议；核心决定授权、状态转换、预算预留、真实作业启动与最终完成。 |
| ARC-03 | Codex 只负责一个有限工作单元内部的推理和执行，不负责永续管理整个目标。不存在层层嵌套的长期 Commander。 |
| ARC-04 | 同一候选工作区最多一个有效写入 lease；读者与评审者访问固定快照。 |
| ARC-05 | 独立评审必须使用独立会话和只读输入；不得让实现者自评后直接成为最终验收依据。 |
| ARC-06 | Dashboard 是投影与命令客户端，不直接写数据库、不发起 shell、不持有模型或 GPU 凭据。 |
| ARC-07 | 角色是能力，不是六个常驻 Agent；没有工作时不调用模型。 |
| ARC-08 | 预算、批准、实验身份在重启、子任务、适配器切换后保持连续。 |
| ARC-09 | UNKNOWN 不是失败或成功；未确认是否执行的昂贵任务不得自动重跑。 |
| ARC-10 | 同一逻辑动作允许至少一次传输，但必须幂等接收；不宣称跨进程副作用天然 exactly-once。 |
| ARC-11 | 所有界面“事实”可追溯到事件、采样或证据；估计、未知、回放明确标注。 |
| ARC-12 | 控制代码、批准、预算、验收数据不在 Agent 可写范围内；自更新仅在安全边界发布。 |

### 3.3 技术选择

后端沿用 Python；API 建议 FastAPI；存储沿用 SQLite 并增加事务化投影、快照与增量事件；前端建议 React + TypeScript + Vite，布局用 CSS Grid，拓扑用 DOM/SVG。首版使用 HTTP 查询/命令 + SSE 推送，不需要 Redis、Kafka、Celery 或新的工作流引擎。相关技术依据见 [S10–S15]，选择本身是本次设计建议。

WebSocket 不作为首版必要依赖；只有后续双向终端或高频双向交互需求证明必要时再引入。SQLite 数据库使用本机持久磁盘，不将 WAL 数据库放到网络文件系统。[S12]

## 4. 能力、模型策略与事件触发

### 4.1 角色映射

| 能力 | 现有职责映射 | 默认权限 | 触发条件 | 输出 |
|---|---|---|---|---|
| Planner | PI | 只读 | 新目标、重要证据改变方向、需重新拆分 | TaskProposal、局部完成条件、依赖 |
| Engineer | Engineer | 候选区单写 | 已批准且依赖满足的实现任务 | Patch、命令结果、证据引用 |
| Explorer | 新增轻量代码阅读能力 | 固定快照只读 | 不清楚代码位置或依赖 | 文件定位、调用关系、引用 |
| Researcher | Scout | 只读、按授权联网 | 缺资料或需比较方案 | 来源、结论、适用边界 |
| Reviewer | Evaluator | 固定快照只读 | 里程碑交付、最终验收、高风险变更 | 条件—证据映射、问题清单 |
| Architect | PI/Critic 的高级审查能力 | 只读 | 重大架构分叉、反复失败、重要最终门控 | 建议与取舍，不直接改代码 |
| Critic | Critic | 只读 | 无信息停滞、结果矛盾、替代解释 | 可区分假设，默认最多 3 个 |
| Designer | Designer | 只读 | 已选假设需要新实验 | 实验规格、预算估计、判别规则 |

Architect 不是新增常驻上司；与 Critic 重叠时复用一次合适的会话，禁止为了名称完整而重复调用。Engineer 可以自身作为任务级主 Agent，并调用获准的只读助手，不要求再增加一个只读主 Agent 监督它。

### 4.2 模型不绑定角色名称

**RUN-01，P0。** 使用 `fast_reader`、`standard_worker`、`deep_reviewer` 等配置别名。安装时根据账户可用模型解析；记录实际模型 ID、推理级别、配置哈希与供应商版本。模型不可用时不得悄悄换到更贵或数据边界不同的提供者；只允许授权范围内的替代策略。

**CTL-01，P0。** 每个路由决定记录 `trigger_type`、规则版本、输入证据、选定能力、升级原因、预算检查及冷却状态。确定性可判断的事项不调用模型；缺上下文先检索已有证据，不直接升级最高成本模型。

### 4.3 默认触发表

| 事件 | 默认响应 | 防止浪费的约束 |
|---|---|---|
| 新目标已批准 | Planner 一次，形成初始 DAG | 已有仍有效计划不重新规划 |
| 小型且边界明确的修复 | Engineer → 确定性测试 | 独立评审可合并到里程碑，但交付前不能省略 |
| 缺文件或接口定位 | Explorer | 可复用相同快照上的有效索引 |
| 缺外部资料 | Researcher | 有具体问题、来源限制与调用预算 |
| 同一错误指纹两次且无新证据 | Critic 或 Architect | 每任务默认最多一次同类升级；有冷却和总预算 |
| 高风险设计或公共协议变化 | Architect 预审 | 冻结版本已有有效审查可复用 |
| 实验成功退出 | 收集原始产物 → Reviewer/Evaluator | 不自动认定研究成功 |
| 实验结果改变下一步选择 | Planner 或 Critic | 只有实质证据变化才启动 |
| 准备完成目标 | 确定性门控 + 独立 Reviewer | 高风险或证据冲突才追加 Architect |
| 心跳、界面刷新、训练等待 | 程序化采样与状态更新 | 零模型调用 |
| 429、模型容量不足 | 有界退避、暂停新派发 | 基础设施故障不触发科研 Critic |

“两次失败”是可配置初值，不是机械规则：错误指纹至少包含测试/命令类别、主要错误位置、代码快照、环境和输入规格；不同根因不能粗暴合并。同一代码上的同一失败若已有 Critic 结论，不应再付费获得相同诊断。

### 4.4 可选轻量决策模型

Jev 或同类服务属于 P2 可替换优化点，默认禁用。先证明某项路由确实占用大量模型成本，再进行有标注样本的离线对比与影子测试。轻量模型不得授权预算、解锁保护路径、决定真实训练启动或改变完成条件；失效时退回确定性安全策略。

## 5. 目标、合同、任务与进展

**CTL-02｜目标合同，P0。** GoalContract 包含自然语言目标、目标类型、全局验收条件、可写与保护范围、允许工具/命令模板、资源上限、停止规则、评价数据边界、风险等级、批准人及版本哈希。已批准合同不可原地修改；变更生成新版本和明确差异。

**CTL-03｜局部完成与全局验收分离，P0。** 子任务可产生局部完成条件，并通过 `contributes_to` 关联全局条件。实现“数据加载器”可以局部完成，但不能因此标记“模型达到目标效果”。子任务全部完成后，父任务必须执行集成验证。

**CTL-04｜预算感知拆分，P0。** 每次拆分计算最低执行、验证、独立评审和故障恢复预留；剩余预算不足时缩小本阶段工作量或显式阻塞，不拆出无法验证的大量任务。拆分只在既有批准范围内进行。

**CTL-05｜进展基于证据，P0。** 必须展示“已满足 3/5 条全局条件”，而非从聊天字数、时间或完成子任务比例推算科学进度。任务完成比例可以另列，明确不等于目标达成率。没有可度量分母时显示阶段与证据，不显示伪百分比。

**CTL-06｜停滞检测，P0。** 使用错误指纹、候选变化、有效实验数、指标区间和新证据数量判定停滞。更改报告措辞、增加日志或重复同一实验不算进展。触发后必须做出“判别性检查、换假设、请求决策、预算耗尽停止”之一。

**CTL-07｜独立完成门控，P0。** 完成要求全部强制条件有匹配候选、配置、数据和评价规则的证据；无未收敛的 UNKNOWN 执行；评审角色不是对应实现会话；需批准的偏离已解决；成本已结算或明确披露未结算。研究得到有效负结果可以完成研究问题，但不能标记性能目标成功。

### 5.1 工程闭环

批准 → 可执行局部任务 → Engineer → 确定性测试 → 按风险独立评审 → 接受候选或受限返工 → 下一任务 → 父任务集成验证 → 最终门控。审查发现验收本身错误时，创建合同修订提案，不能直接修改验收以使结果通过。

### 5.2 研究闭环

基线与评价规则冻结 → 最小可判别实验 → Runner → 原始指标和产物 → 有效性检查 → 假设支持/反驳/不确定 → 更新研究状态 → 决定下一次实验。基础设施失败和方法无效分开；负结果永久保留在可审计记录中。

### 5.3 审批的精确粒度

“初始批准一次”不意味着允许任何未来实验。初始 envelope 可以批准一个有界实验族：允许修改的参数、脚本/产物准入方式、数据版本、最大启动次数、单次与总资源、评价规则和禁止项均明确。每次实验仍由程序基于精确候选与配置派生一份不可变执行授权；超出实验族必须重新征求用户批准。

## 6. 执行状态机、控制权与恢复

### 6.1 状态分层

| 对象 | 状态集合 | 说明 |
|---|---|---|
| Goal | DRAFT、AWAITING_APPROVAL、READY、RUNNING、WAITING_EXTERNAL、BLOCKED、PAUSE_REQUESTED、PAUSED、STOP_REQUESTED、STOPPED、COMPLETED、BUDGET_EXHAUSTED、FAILED | COMPLETED 另带结果 SUCCESS / NOT_SUPPORTED / INCONCLUSIVE，不与线程结束混同。 |
| Task | PROPOSED、READY、RUNNING、AWAITING_REVIEW、SUCCEEDED、FAILED、BLOCKED、CANCELLED | 局部 SUCCEEDED 不直接提升 Goal。 |
| ExecutionAttempt | CREATED、RESERVED、STARTING、RUNNING、FINISHING、SUCCEEDED、FAILED、CANCEL_REQUESTED、CANCELLED、UNKNOWN | 唯一 attempt ID；重试新建 attempt，引用原 attempt。 |
| Experiment validity | UNASSESSED、VALID、INVALID、INCONCLUSIVE | 与进程退出状态正交。 |
| Client connection | CONNECTING、LIVE、RECONNECTING、STALE、OFFLINE、REPLAY | 只描述客户端连接，不能覆盖后台任务状态。 |

所有转换必须有事件、前置版本、操作者或规则、原因与关联对象。未知状态/未知枚举不得由客户端当成成功。

### 6.2 Execution lease

**RUN-02，P0。** 开始执行前必须产生 ExecutionLease：项目、任务、attempt、合同与候选哈希、runtime/profile、角色、写入范围、只读快照、父子会话上限、资源预留、有效期、controller epoch、幂等键。授权、epoch 或启动基准候选改变时，旧 lease 不再可用于启动。Engineer 的获准修改会产生新的输出候选，因此必须区分 `base_snapshot_hash` 与 `output_snapshot_hash`；结果接收验证补丁来源与允许范围，再将输出候选绑定后续测试/评审，不能要求合法修改后哈希仍等于输入哈希。

**RUN-03，P0。** 分阶段启动：`prepare → reserve → register identity → authorize release → acknowledge started`。准备期限、放行期限和执行期限分别计时。放行前重新校验 STOP、批准、预算和候选。网络发送成功不等于执行启动成功。

**RUN-04，P0。** 外部作业的提交身份必须持久化，并支持按 idempotency key 查询。收到超时但不知是否提交成功时进入 UNKNOWN；先 reconcile，再决定是否重试。做不到幂等查询的 adapter 不允许无人值守重试昂贵任务。

**RUN-05，P0。** 接收结果必须校验 project/task/attempt/session/thread/turn、lease epoch、合同版本、代码与输入指纹。旧会话迟到结果保留为审计材料，不接受为当前任务证据。

### 6.3 暂停、停止与恢复语义

| 操作 | API 接收后的立即行为 | 真正完成的判据 |
|---|---|---|
| Pause | 设置 PAUSE_REQUESTED，禁止新派发 | 所有受管活跃工作到达声明的安全边界；默认让现有实验在预算内完成，不静默杀训练 |
| Stop | 设置 STOP_REQUESTED，禁止派发及新工具副作用，开始撤销受管执行 | 所有目标范围内进程已确认停止或退出；不确定时保留 STOP_REQUESTED/UNKNOWN 警告 |
| Resume | 验证授权、状态、预算、进程身份和候选 | reconcile 完成后回 READY/RUNNING；不等于无条件重新执行 |
| Reconcile | 只核对运行、回执、资源及产物 | 产生一致的事实；没有自动扩权能力 |

Stop 默认先请求协作中断，再按批准的宽限期终止进程树。checkpoint 只有在已批准、可执行且不突破硬资源边界时才允许保存；不能为了“优雅停止”无限延长。进程身份包含主机、boot ID、PID、starttime、cgroup/进程组，禁止只按 PID 杀进程。

**RUN-06，P0。** Dashboard 断开不得影响任务继续；控制进程崩溃由独立监督者执行已批准的故障策略。初版保留现有偏保守的回收策略；允许实验在控制进程失联时继续运行属于 adapter 通过监督与独立预算测试后的可选能力，不能默认承诺。

## 7. Codex 适配合同

### 7.1 一个产品入口，有限工作单元

交互式 Codex 会话是用户客户端：提交目标、查看状态、读取报告。后台由 rlflow 的 runtime adapter 启动已授权的有限工作单元。后台会话不被包装成另一个永久 Commander。初版不承诺把现有交互线程无缝接管为后台线程，也不同时从两个客户端修改同一 Codex thread。

### 7.2 接口（rlflow 自定义合同，不是官方 API 名称）

| 方法 | 要求 |
|---|---|
| `probe_capabilities()` | 返回版本、协议指纹、模型可用性、结构化输出、usage、interrupt、恢复、原生子代理和权限可强制性。 |
| `prepare(lease, packet)` | 创建隔离环境，验证输入；不得启动模型或实验。 |
| `start(prepared_id, idempotency_key)` | 只使用已预留资源，返回外部执行身份。 |
| `events(execution_ref, cursor)` | 提供真实增量通知；说明能否重放及哪些可缺失。 |
| `inspect(execution_ref)` | 区分运行、终态、未知；不能用进程不存在推断成功。 |
| `interrupt(execution_ref)` | 请求中断，返回请求回执而非虚构终态。 |
| `collect(execution_ref)` | 取结构化结果、usage、证据指针与来源范围。 |

官方 App Server 提供 thread/turn 与 item 通知，CLI 也提供 JSONL；本合同负责转换与兼容。[S05–S06] 不把所有供应商原始事件直接作为 rlflow 的状态机事件。

### 7.3 默认实施路径

M0 对已有 `codex exec --json` 路径和 App Server 本机 stdio 路径做兼容性验证。M1/M2 不强迫一次性替换已验证的 executor。App Server 仅在版本化契约测试、审批拦截、恢复与 usage 对齐通过后成为默认 adapter；否则继续使用已验证路径并清晰报告缺失能力。

官方文档把部分 App Server/传输能力标为实验性，尤其不应直接远程暴露其监听端口。[S05] Dashboard 的远程入口必须是 rlflow 自己的认证服务，而不是模型运行端口。

### 7.4 原生子代理的准入门槛

**RUN-07，P0。** 原生子代理必须证明：能限制并发和深度；只读身份确实不能写入；全部后代计入资源与会话限额；能观察生命周期或安全报告 unknown；能中断/回收；不能绕过核心启动昂贵实验。初值为主机最多 3 个模型会话（包括父会话和全部后代），单工作区一个写入者，原生委派深度最多 1。

父会话默认是唯一 Engineer 写入者，助手均只读。若切换为父只读、Worker 子代理写入，必须明确转移写入 lease，绝不能同时保留两个写入者。读者访问固定候选快照，而非持续变化的工作目录。

若当前 Codex 版本无法强制其中任一关键边界，则禁用该类原生委派，以 rlflow 显式派发独立受控会话完成必要任务。**这不是向用户增加一个模式，而是安全能力降级。** 不为了原生体验而删除现有隔离。

### 7.5 无法观测的内部活动

缺少真实子代理事件时，显示“内部委派不可观测”，不画假 Agent 节点。usage 仅包含父或整个线程时，明确 `usage_scope`，不得虚构每个子角色的成本。不以模型文字“已启动 Worker”作为真实进程或会话事件。

## 8. 数据、事件与可恢复存储

### 8.1 核心对象

| 对象 | 必需字段组 |
|---|---|
| Project | ID、工作区根、状态目录、项目适配配置版本、保护范围、主机资源池 |
| GoalContract | ID/version/hash、目标、全局条件、允许范围、预算、停止规则 |
| Task | ID/parent/dependencies、局部完成条件、contributes_to、风险、状态、版本 |
| Proposal / Approval | 精确提案哈希、旧新差异、有效期、可信批准主体、范围 |
| ExecutionLease / Attempt | 授权、候选、runtime 身份、epoch、预算预留、状态 |
| Evidence | 条件 ID、原始产物、代码/配置/数据指纹、验证器版本、结论与限制 |
| Experiment | hypothesis、spec、seeds、预算、attempts、原始指标、有效性与结论 |
| BudgetEntry | dimension、reserve/consume/release/adjust、数量、来源、幂等键 |
| Event | schema_version、project、store epoch、seq、event_id、type、对象与因果引用、时间、payload |
| Command | 幂等键、命令类型、目标、预期版本、参数、可信主体、状态与拒绝原因 |

时间存储为 UTC RFC3339，显示可选用户时区。持续时间用单调时钟测量；不依赖客户端时钟决定事件先后。金额使用整数最小记账单位或 decimal 字符串，不使用二进制浮点累计账款。

### 8.2 存储方式

**DAT-01，P0。** 保留追加审计记录；小事件与当前投影在同一数据库事务内更新，提交后再通知外部消费者。常规查询直接读取投影；不得每次状态查询重放全部历史，也不得每次变更重写完整 JSONL。

**DAT-02，P0。** 每个项目的 durable event sequence 在事务内递增，回滚不留下已发布事件。唯一约束覆盖 event_id、幂等键与相关执行身份。异步分发使用事务 outbox 或等价的提交后补发机制，允许重复但不能丢掉已提交的关键事实。

**DAT-03，P0。** 定期投影快照和数据库备份；恢复从快照与尾部事件重建。旧数据库恢复产生新 `store_epoch`，让旧浏览器游标失效。重放只计算状态，不执行 shell、不启动模型、不重新结算副作用。

**DAT-04，P0。** 将领域事件、遥测和大日志分开：授权/状态/账本/证据为 durable；CPU/GPU 采样可降采样存储；原始 stdout/token delta 为分段日志或有界缓冲。关键事件不因 UI 背压被丢弃。原始模型私密推理不作为界面必需数据；只展示允许公开的摘要、工具动作和证据。

### 8.3 Durable event envelope

事件 envelope 的机器可读合同见 `schemas/event.schema.json`；若干已类型化 payload 起稿见 `schemas/payloads.schema.json`。T03 必须补齐全部生产事件的 payload 注册表，未知关键类型不得驱动状态转换。必填语义如下：

```json
{
  "schema_version": "1.0",
  "store_epoch": "store_fixture_01",
  "project_id": "project_fixture",
  "seq": 12,
  "event_id": "evt_fixture_12",
  "type": "execution.started",
  "occurred_at": "2026-10-07T14:30:00Z",
  "recorded_at": "2026-10-07T14:30:00.120Z",
  "entity": {"kind": "execution", "id": "attempt_fixture_01", "version": 3},
  "correlation_id": "goal_fixture_01",
  "causation_id": "evt_fixture_11",
  "source": {"kind": "core", "id": "controller_fixture"},
  "data_mode": "fixture",
  "payload": {"task_id": "task_fixture_01", "runtime_ref": "runtime_fixture_01"}
}
```

`data_mode=fixture` 只能出现在明确标识的演示/测试实例中；生产流必须为 live。查看历史真实事件由 UI 的 REPLAY 状态表达，不改写源事件。

### 8.4 接收与投影规则

内部模型输出先作为 `result.submitted` 事实接收，校验通过后才形成 `evidence.accepted` 等权威事件。结果的语法正确不代表内容可靠。事件 reducer 必须可测试且无副作用；新旧 schema 通过显式 upcaster 或迁移处理，不容许客户端猜测不认识的字段语义。

## 9. 预算与系统资源

### 9.1 预算维度

**RES-01，P0。** 至少记录模型请求/会话数、input/output/cached tokens（可取得时）、估计费用、实际费用状态、CPU 时间、GPU 设备秒、wall time、作业启动/重试次数、内存和磁盘上限。GPU 设备秒定义为实际分配设备数 × 分配持续秒数，不冒充设备实际计算利用率。

每一维包含 `limit / consumed / reserved / available / unknown_exposure`。本版定义 unknown_exposure 为 reserved 中尚未核实的子集，不能重复扣除；`available = max(0, limit - consumed - reserved)`，超额另列 overrun。若未知暴露无法用已预留上界覆盖，严格预算停止新准入，不能把不确定剩余显示为可用。模型提供者返回 usage 缺失时保留 unknown，而不是零。订阅访问下显示 usage 与可观测配额，不把 API 单价估算标成用户实际账单。

### 9.2 预留、结算与硬/软上限

**RES-02，P0。** 启动前原子预留，确定未启动才能释放；已使用后失败仍消费；未知保留预留；纠正使用追加 adjustment 且有幂等键。多项目必须检查同一主机的共享限额，不能各自占满 GPU。

**RES-03，P0。** 将预算保留区分为执行、最终验证/评审和恢复。初值建议把模型/计算可分配预算的 20% 作为收尾保留，项目可覆盖；这是一项规划政策，不是实际提前花费。不能为了继续迭代侵占所有最终验收预算。

**RES-04，P0。** 接口能强制 token 上限时使用；不能强制时只能承诺可观测的软 token/费用上限，并用会话数、输出限制、wall time 和中断控制额外约束。硬预算无法被当前 adapter 保证时，必须拒绝该配置或显式要求批准软上限，不能虚报保证。

usage 按供应商事件语义区分增量与累计，记录 source ID 与 scope；重放累计 usage 不能重复加总。cached tokens 通常属于输入范围的细分，必须按对应计价表语义处理；父线程已含后代的总量不得再与子代理总量相加。

### 9.3 进程树与文件资源

**RES-05，P0。** 对 worker/测试/实验进程树实施 cgroup 级内存、CPU、进程数约束；控制进程单独保留资源。cgroup v2 可提供相应层级限制。[S13] Docker 环境无委派能力时标识 `resource_enforcement=partial`，严格任务禁止运行，不通过特权容器或挂 Docker socket 来绕过限制。

**RES-06，P0。** 源码、只读数据、实验产物分离；源文件通过受批准 manifest 标识，禁止把 checkpoint/log/video 放进反复计算的源码指纹。大文件流式哈希，摘要可按不可变版本复用。`.gitignore` 不是权限或证据边界。

**RES-07，P0。** 高开销哈希、归档和指标分析在有界后台工作进程执行，不阻塞调度心跳。磁盘满时先停止新派发；确保有预留审计空间，关键事实无法写入则 fail closed。禁止自动删除原始实验依据或仍被引用的证据。

### 9.4 建议初始限制

默认值用于安全起步，项目批准后可调整：主机模型会话总数 3（含父子）、工作区 writer 1、GPU 实验并发 1、重复昂贵实验自动重试 0、同任务相同失败升级 1 次、界面动画最多 30 FPS。最终具体资源量必须基于用户项目填写，不把这些初值等同于已获授权。

## 10. 上下文与科研证据

**DAT-05｜有界上下文，P0。** 每次会话输入由目标摘要、相关合同、局部任务、固定候选摘要、最近关键证据、反证、未解决问题组成。按能力设置 packet 上限；大文件按需读取。提示词上限与整个会话 token 上限分别展示。

**DAT-06｜固定快照与评审独立，P0。** Reviewer 读取固定候选、原始证据和验收规则，不能继承实现者完整聊天作为唯一材料。Cold Review 先读原始证据后读既有解释。使用同一模型品牌不自动破坏独立性，但必须是独立会话、只读权限和独立结论。

**EXP-01｜通用实验适配，P0 最小闭环。** 定义 `validate_spec / submit / inspect / cancel / collect`，项目只需提供实验命令模板与产物协议；不把 H1 或 instinctRL 固定在通用核心。首版至少完成一个真实本地实验 adapter 和一个不耗 GPU 的确定性 fixture adapter。

**EXP-02｜可追溯身份，P0。** 每次实验记录代码快照、脏补丁摘要、容器/依赖版本、数据版本、配置、种子、设备资源、评价规则、checkpoint 来源、父实验和 attempt。相同配置的有意多种子实验与意外重复提交必须区分。

**EXP-03｜有效性与结论分离，P0。** 明确 `execution_status`、`scientific_validity`、`hypothesis_outcome`。退出码 0、训练奖励上升或 Agent 声称改善，均不能直接成为科学成功。数据缺失、评价配置偏离、种子不足或输出与规格不一致时，必须标注限制。

**EXP-04｜RL 适配验收，P1。** 训练和评估配置分开、评估数据与训练数据边界明确、baseline 固定、种子集合与统计汇总规则明确、训练预算可比、失败和删失试验不隐匿。选择“最佳 checkpoint”及停止标准必须可追溯；不强制所有任务使用统计显著性，也不虚构预注册。

**EXP-05｜证据保留，P0。** 负结果、失败原因、原始日志摘要和关键产物引用必须可检索。引用关系阻止误删；重分析产生新版本，不覆盖旧结论。实验产物路径只作为服务端引用，不直接暴露主机任意文件。

## 11. Dashboard 信息架构

### 11.1 页面与优先级

| 页面 | 首版内容 | 后续增强 |
|---|---|---|
| 项目总览 | 项目、目标、状态、待批准数、关键预算、最近更新 | 跨项目成本比较与资源调度分析 |
| Live 运行台 | 目标头部、实际执行拓扑、下一步/阻塞原因、事件带、预算条 | 自定义面板布局 |
| 任务与条件 | Task DAG、局部完成、全局条件证据矩阵 | 大规模依赖折叠与条件变化对比 |
| 会话详情 | 角色、模型、状态、权限、触发原因、工具动作、usage 来源 | 跨会话诊断对比 |
| 实验与证据 | 基线、当前实验、指标、产物、有效性、反证 | 多种子统计、曲线叠加与筛选 |
| 审批与控制 | 精确提案、差异、预算影响、批准/拒绝；暂停/停止状态 | 移动端完整审批体验 |
| 资源与健康 | 模型 usage、CPU/GPU、内存/磁盘、队列、执行能力与未知项 | 性能趋势与预算预测 |
| 历史与回放 | 事件查询、历史快照；明确历史标识 | 时间轴 seek、倍速、分享脱敏回放 |

P0 必须完成总览、Live、任务/条件、会话、审批、基础证据和健康信息；实验高级图表及完整动画回放为 P1。不得先做复杂图表再补真实数据链路。

### 11.2 Live 页布局

桌面采用稳定的三区结构：顶部是目标与控制条；中部左侧约 2/3 为运行拓扑，右侧为“现在/原因/下一步”与详情；底部为有界事件列表。资源可放在右侧下方，不占用拓扑连线。

显示顺序：Goal/Policy → 当前有限执行单元 → 实际助手 → 验证/实验 → Evidence → 决策。高阶角色的未激活入口以“可用能力”小标签显示，不能伪装成正在运行的节点。初版不强制把所有历史任务画到同一张图中。

### 11.3 页面最小字段

**UI-01｜目标头部，P0。** 项目、目标摘要、合同版本、当前阶段、全局条件满足数、活跃尝试数、待批准/未知数、预算余量、连接状态、最后服务端同步时间。最终状态必须可点击查看证据门控结果。

**UI-02｜运行节点，P0。** `session/attempt ID`、角色、实际模型、状态、开始时间、已观测时长、触发原因、只读/写入标识、当前动作摘要、usage 可用性。可以折叠长 ID，详情可复制完整值。

**UI-03｜连线，P0。** 必须对应实际关系，如 parent_session、dispatch、result、evidence、escalation；每次强调效果关联 event_id。连线不能暗示不存在的数据交换或真实网络包。

**UI-04｜原因与下一步，P0。** 展示规则与证据，例如“同一单测两次失败；已安排独立诊断”“GPU 正忙；等待 resource_pool”。文字优先来自结构化字段和确定性模板，不额外调用 LLM 生成每条实时说明。

**UI-05｜任务/条件矩阵，P0。** 每条全局条件展示 PASS/FAIL/UNASSESSED/INCONCLUSIVE、有效证据、候选版本和评审；子任务另列局部状态。完成 9/10 个子任务不能显示目标已达成 90%。

**UI-06｜日志与事件，P0。** 支持按 task、session、experiment、severity 筛选；日志正文懒加载。用户向上阅读时停止自动滚动，展示“新增 N 条”按钮。列表虚拟化，DOM 不无限增长；批量事件可以折叠，但原始事件可追溯。

**UI-07｜实验面板，P0/P1。** 展示规格、执行状态、有效性、当前指标与测量时间、baseline、候选结果和原始产物。未知训练总步数不显示百分比；ETA 必须标注估计及数据窗口。曲线缺数据时断线，不插值出未发生的训练结果。

**UI-08｜资源面板，P0。** 将 consumed、reserved、unknown exposure 与 available 区分。费用分“实测账单可得”“usage×价表估计”“未知”。实际模型无 usage 时显示“未提供”，不能显示 0 tokens。

**UI-09｜详情抽屉，P0。** 点击节点或事件展示输入摘要、关联合同、精确候选、资源授权、可公开工具动作、输出摘要、证据和状态转换链。不要求展示或推断模型私密思维过程。

### 11.4 空、慢、错、离线状态

空项目显示如何从 Codex 创建目标；只读观察者没有启动按钮。数据加载失败保留最后快照并标记过期，不能清空为“全部闲置”。服务器活着而 worker 心跳丢失时分别显示“连接正常 / 执行状态未知”。浏览器离线不宣称后台任务停止。

超过 15 秒没有任何有效服务端消息，默认显示 STALE；确认断线显示 OFFLINE/RECONNECTING；阈值可配置。只收到服务端心跳只能证明连接活着，不证明 GPU 或 Agent 在工作。服务端和 worker freshness 分开计算。

## 12. live-panel 视觉语言与真实动画规范

### 12.1 可借鉴与禁止照搬

可借鉴：深色、等宽终端感、稳定方框、正交连线、短促信息流、稀疏强调、滚动事件、触发器提示。自行设计 rlflow 的整体布局、比例、文案和图标；不整页复刻原视频或商用示例，不把复刻项目的模拟计数带入生产。[S09]

推荐设计 token 为项目自己的默认值：背景 `#0B1017`、面板 `#111B26`、正文 `#E6EDF5`、次级文字 `#93A4B8`、执行强调 `#52C7EA`、等待 `#E8BC61`、完成 `#77CFA3`、失败 `#EE8181`、未知 `#B2A2E6`。上线前检查对比度；状态必须同时用文字/形状编码，不能只靠颜色。

正文 14–16 px；辅助信息至少 12 px；移动端触控区域至少 44×44 CSS px。字体用系统等宽栈并提供 CJK 回退，不依赖运行时远程字体请求。

### 12.2 三套时钟

**UI-10，P0。** 业务时钟由后端真实事件/采样决定；展示时钟只平滑动画和测量“距上次更新”；回放时钟只移动已记录历史。三者隔离。改变浏览器时间、FPS 或 seek 不能改变业务指标与状态。

### 12.3 动效映射表

| 真实输入 | 允许的动效 | 禁止的推断 |
|---|---|---|
| task/lease 已持久派发 | 沿真实关系发送一次短脉冲 | 脉冲等于模型已开始消费 |
| execution.started | 节点边框短亮，状态 RUNNING | 任务已经成功 |
| 工具调用开始/结束 | 图标/局部连线强调 | 未观测的内部调用 |
| evidence.accepted | 指向证据节点的一次强调 | 证据支持所有目标条件 |
| escalation.requested | 对应触发器点亮并显示原因 | 最高模型已经启动 |
| 实测 usage 更新 | 更新最终计数；可短暂高亮变化 | 按时间匀速增加 token |
| GPU 样本 | 更新数值与采样时刻 | 用占位波形假装真实利用率 |
| 没有事件但工作仍确认运行 | 可显示轻量 spinner/静态活动标记 | 持续流动的假通信包 |
| 客户端失联或 worker 未知 | 停止“业务活动”脉冲，标过期 | 静默继续演示动画 |
| confirmed success/failure | 一次状态变化，随后静止 | 永久庆祝或闪烁 |

脉冲代表“事件发生”，不代表网络包数量、token 速度或真实数据传输速率。tooltip 可显示关联事件与含义。事件过密时合并为“本边 12 次事件”，保留计数和详情，不把丢弃动画等同丢失业务事件。

### 12.4 渲染与性能

推荐 DOM/SVG 表达节点与路径；React 管理离散状态，不在每一帧 setState 更新整个图。动画使用单个受控 requestAnimationFrame 循环或局部 Web Animations；拓扑改变才重新计算布局。rAF 的浏览器机制参考 [S11]。

前台活动时上限 30 FPS，静止时不保留空转动画循环；后台标签页停止动效；`prefers-reduced-motion` 或用户“减少动画”开启后保留所有事实与操作，仅去掉非必要移动。[S16] 不让动画决定后端轮询频率。

**UI-11，P0。** 页面首次打开或断线追平时，默认直接呈现当前状态，不高速播放几千条旧脉冲。全局保留最多 200 个正在显示的短时动画实例；过量合并并显示聚合说明。拓扑默认展示当前层次不超过 30 个节点，超出按角色/任务组折叠。

### 12.5 可访问性与移动端

**UI-12，P0。** 所有图节点可键盘聚焦，状态带可读文字，连线含替代描述；不能依赖 hover 获取关键授权信息。移动端改为阶段卡片和纵向执行列表，图仅作为辅助，不把桌面画布缩到无法阅读。主目标、预算、阻塞、批准和停止状态始终优先。

## 13. 实时协议、断线追平与 API

### 13.1 API 分层

浏览器通过同源 HTTPS/本地 HTTP 查询和提交命令；读取实时状态使用 SSE。SSE 是服务端到客户端的单向连接，命令通过 HTTP POST 完成。[S10] 前端不直接连 Codex、不直读 SQLite、不解析终端 ANSI 来决定业务状态。

接口原型见 `openapi.yaml`，字段约束以 JSON Schema 和本节语义共同为准。OpenAPI 是开发合同起点，不是现有服务器的自动导出。

| 方法与路径 | 作用 |
|---|---|
| `GET /api/v1/projects` | 可见项目与状态摘要 |
| `GET /api/v1/projects/{project_id}/snapshot` | 一致快照、store_epoch、cursor、server_time |
| `GET /api/v1/projects/{project_id}/events?after={cursor}` | 单项目完整 durable 流，支持 Last-Event-ID |
| `GET /api/v1/projects/{project_id}/tasks` | 分页任务与条件 |
| `GET /api/v1/projects/{project_id}/executions` | 分页实际执行记录 |
| `GET /api/v1/projects/{project_id}/experiments` | 分页实验与有效性 |
| `GET /api/v1/projects/{project_id}/approvals` | 待批及历史审批 |
| `GET /api/v1/projects/{project_id}/budget` | 预算账本投影及未知项 |
| `GET /api/v1/projects/{project_id}/artifacts/{artifact_id}` | 授权后的元数据或受控下载 |
| `POST /api/v1/projects/{project_id}/commands` | 创建目标、审批、暂停、恢复、停止、对账请求 |
| `GET /api/v1/projects/{project_id}/commands/{command_id}` | 命令接收、执行与终态回执 |
| `GET /api/v1/health` | 服务与依赖健康；公开响应不泄露秘密 |

MCP skill 使用相同的业务服务层，不必通过外网 HTTP；工具名是 rlflow 自定义如 `submit_goal / get_status / get_report / request_pause / request_stop`。Agent principal 不获得人类批准 API 权限。

### 13.2 Snapshot + stream 无缝交接

**DAT-07，P0。** 服务端在同一一致性读取中返回投影 S 和对应 cursor C。客户端安装 S 后，从 C 之后订阅事件；服务端从日志补发这段期间已提交事件，再持续推送。不能先订阅再无版本覆盖快照，造成新状态被旧状态替换。

cursor 格式为 `{store_epoch}:{seq}`；project_id 由 URL 确定。seq 为单项目已提交 durable 事件序号。生产事件流不按任务过滤，前端可过滤展示，避免因服务端过滤而误判序号缺口。遥测不占该 durable seq，使用独立 `sample_id / observed_at`。

初次创建 EventSource 可用 `after`；断线重连优先使用有效 Last-Event-ID。epoch 不符、游标过期或服务端无法补齐时，发送 `resync_required` 控制消息后关闭流；前端主动 close 并重新获取快照，不无限尝试旧游标。未知关键 schema 也触发重新同步和显式不兼容提示。

### 13.3 事件类别与可靠性

SSE `event: domain` 携带已提交事件，`id` 为 durable cursor；`event: telemetry` 携带可丢弃最新样本，不设置 durable id；`event: heartbeat` 每 5 秒给出服务端时间、最新 durable cursor 和关键健康状态，不推进消费游标；`event: resync_required` 指示重建。

前端按 event_id/seq 去重，严格按 durable seq 应用；收到缺口先停应用后续关键事件，再补齐或重建。遥测按单指标 sample_id/时间版本更新，迟到旧样本不能覆盖新样本。浏览器重连期间保留最后快照，但明确 STALE。

**DAT-08，P0。** 慢客户端有有界发送队列；遥测可合并，关键领域事件不能静默删除。队列达到上限时关闭连接并要求可恢复追平，不阻塞调度器。每个页面最多一个活跃项目 SSE，多个面板共享该连接。

### 13.4 控制命令合同

请求带 `Idempotency-Key`、目标、action、expected_version 和参数；可信 actor 从服务端认证上下文得到，不能信任 JSON 内的 `approved_by`。相同主体/项目/幂等键与相同 payload 返回同一个 command；同键不同 payload 返回 409。

除紧急 stop 外，状态敏感命令必须提交 expected_version；冲突返回 409 并携带当前版本摘要。stop 可省略 expected_version，但仍检查权限、目标身份和作用范围，不能从单目标默默升级为整机杀进程。

202 只代表命令已持久接收；页面显示“暂停请求已接收 / 停止处理中”，直到 command 与实际执行状态确认。用户断网重试不会造成第二次授权或重复启动。控制确认页面必须描述范围与影响，不能用含糊的“确定吗”。

### 13.5 错误码

统一响应包含 `code / message / retryable / correlation_id / details`。核心 code 包括 `AUTH_REQUIRED`、`PERMISSION_DENIED`、`VERSION_CONFLICT`、`IDEMPOTENCY_CONFLICT`、`BUDGET_EXHAUSTED`、`UNKNOWN_EXECUTION`、`UNSUPPORTED_CAPABILITY`、`RESOURCE_ENFORCEMENT_PARTIAL`、`RESYNC_REQUIRED`、`VALIDATION_ERROR`。内部堆栈不暴露给未授权客户端。

## 14. 控制安全与权限

**SEC-01｜可信批准，P0。** 人类批准来自独立可信交互：认证 Dashboard 的明确确认，或不能被 Agent 冒充的宿主批准桥接。Agent 生成“用户已批准”文字、JSON 布尔值或提交批准工具请求均不授予权限。服务端记录真实 principal、proposal hash、scope 和时间。

**SEC-02｜运行隔离，P0。** 只读/可写由 OS/容器/工具边界强制；数据库、控制代码、批准账本、凭据、原始保护数据不可写。读文件、建符号链接、网络工具和子进程均计入权限面。测试执行未受信任代码同样需要隔离；不能因为名叫 pytest 就视为无副作用。

**SEC-03｜远程接入，P0 本地 / P1 远程。** 默认只绑定 loopback，通过受信隧道或配置认证的 TLS 反向代理供手机访问；外网访问不得裸露无认证 API、Codex 端口或 Docker daemon。应用自身仍验证身份与权限，不能把“同一局域网”当作登录。

**SEC-04｜浏览器认证，P0。** 浏览器使用同源 HttpOnly 会话 cookie；写命令检查 CSRF token 和 Origin。会话超时后停止敏感操作并重新认证。机器客户端可用受范围限制的短期 token；token 不放 URL query、日志或前端持久明文存储。bootstrap 凭据由操作者通过安全途径输入，不硬编码。

**SEC-05｜操作授权，P0。** 至少区分 viewer、operator、approver。读取产物也按项目授权；停止范围受权限限制。敏感审批有完整差异和资源影响，批准精确版本；新的提案版本不能沿用旧按钮。

**SEC-06｜不可信内容与秘密，P0。** 日志、模型输出、网页引用和代码视为不可信数据；以文本渲染并做 XSS 处理，不执行嵌入 HTML/SVG/script。脱敏 API key、auth.json、连接串和敏感路径；脱敏前原始日志只在受控后端保存。来源内容不能更改 policy 或调用权限。

**SEC-07｜产物访问，P0。** artifact_id 由服务端映射到批准根目录，防目录穿越、符号链接逃逸与越项目读取；下载路径不可由客户端任意指定。可执行文件/HTML 默认附件下载而不是同源执行；导出包附 provenance 与敏感信息检查。

**SEC-08｜控制更新，P0。** 修复代码与运行代码版本分离；活动/UNKNOWN 会话期间不热替换控制逻辑。测试、review 与发布绑定同一代码指纹。禁止任务运行中自行扩大工具集或关闭审计。

## 15. 部署、安装与运维

### 15.1 首版部署

保留 Ubuntu + Docker 工作环境。控制服务使用独立 UID、持久状态卷；候选、数据、产物、秘密分别挂载。运行层仅获得任务必需的范围；宿主 cgroup 能力由显式预检确认，不通过默认 privileged 绕过。

API 可与静态网页同源部署，控制核心通过本地 socket/受限 IPC 接受命令。不要在多 worker Web 服务的 import/startup 中各自启动 scheduler；scheduler 必须是独立受单例锁和 fencing 保护的生命周期。

**OPS-01，P0。** 安装包包含角色、schema、前端构建产物与默认配置；在干净环境做 wheel/install smoke test。文档说明如何升级、回滚、迁移、备份、定位日志以及验证真实 adapter 能力。

**OPS-02，P0。** 提供 health 与诊断报告：版本、控制 lease、数据库健康、磁盘、资源强制能力、Codex 版本/模型可用性、最后 worker 事件、遥测可用性、保护路径。诊断不得读取或输出凭据正文。

**OPS-03，P0。** 模型容量/网络波动采取指数退避和抖动，限制总重试与总等待。只重试已确认未产生副作用的动作；数据库忙、日志压力、模型限额、实验失败分门别类。长时间等待不持续唤醒 PI。

### 15.2 保留策略

关键领域事件和被引用证据保留至目标归档，归档前后可验证完整性。原始工具日志建议滚动压缩，默认 14 天；高频遥测默认 7 天，降采样序列默认 90 天；这些是可配置初值，引用保护优先于到期删除。活跃目标的关键证据不得仅因达到天数而删除。

备份使用 SQLite 正确的在线备份方式或停机一致快照，不只随意复制一个正在写入的主数据库文件。恢复演练必须核对事件、投影、预算、审批和真实外部进程身份，不仅验证“文件能打开”。

## 16. 非功能与资源验收目标

以下目标在基准档案 **B1** 下测量：本地 SSD，4 vCPU、8 GiB 内存，3 个登记项目、1 个活跃目标，最多 3 个模型会话（使用可控假运行器压测）、10,000 个任务记录、100,000 条历史领域事件；持续 10 条/秒领域事件、50 条/秒短时峰值；独立遥测经聚合后最多 10 次/秒/项目；1 个桌面及 1 个移动端查看客户端。真实模型/GPU 负载另测，不计入控制层基准。

| 编号 | 指标 | 拟议验收目标 |
|---|---|---|
| NFR-01 | 领域事件提交至本地页面可见 | p95 ≤ 750 ms；网络额外延迟单独报告 |
| NFR-02 | snapshot 查询 | p95 ≤ 500 ms；仅当前范围，不返回全部历史 |
| NFR-03 | 控制命令持久接收 | p95 ≤ 300 ms；执行完成时间另计 |
| NFR-04 | 初始 Live 可用 | 本地 p95 ≤ 2 s，不等待全部日志/曲线加载 |
| NFR-05 | 控制+API 常驻内存 | RSS 合计目标 ≤ 512 MiB，不含 Codex、实验、浏览器 |
| NFR-06 | 空闲控制层 CPU | 5 分钟平均 < 单核 1%；零模型调用；无全仓库/全历史轮询 |
| NFR-07 | 前端内存 | 目标 JS heap ≤ 150 MiB；事件列表有界；8 小时无持续线性增长 |
| NFR-08 | 动效 | 活动上限 30 FPS；静止/后台停动画；减少动画不丢信息 |
| NFR-09 | 空闲流量 | 每查看客户端平均 < 5 KiB/s，不含首次资源下载 |
| NFR-10 | 增量更新可扩展性 | 固定当前投影大小，历史 10k→100k 时普通写入 p95 比例 ≤ 2；无全量历史导出 |
| NFR-11 | 停止响应 | 接收后 1 s 内阻止新派发；受管本地任务默认 10 s 宽限后升级终止；未知进程明确报告 |
| NFR-12 | 可靠性 | 24 小时 fixture soak 无重复副作用；8 小时 UI soak 无不可恢复失步；另做至少 1 次真实受批准闭环 |

NFR 失败时先分析队列、I/O、状态模型和内存，不立即增加微服务。NFR-11 不承诺不可中断内核状态或无控制权远程进程能在固定秒数内消失；实际未确认终止必须保持未知警告。

## 17. 从现有 rlflow 增量迁移

现有模块职责来自基线文件索引 [S03]。下面是修改目标，不要求立即改名或移动文件。

| 现有模块 | 保留 | 演进方向 |
|---|---|---|
| `engine.py` | 唯一派发、接受结果、恢复入口 | 抽出纯 policy 与 adapter；减少固定角色流水线；加事件出口 |
| `store.py` | 追加审计与完整性 | 原子增量事件+投影、快照、按需导出、流式读取 |
| `policy.py / authorizations.py / contracts.py` | 批准与范围约束 | GoalContract、局部完成条件、ExecutionLease、可信主体 |
| `worker.py / isolation.py` | 身份、隔离、受限执行 | RuntimeAdapter 边界与能力探测；绝不先删隔离再补安全 |
| `jobs.py / lifeguard.py` | 进程所有权与未知恢复 | 幂等提交、lease fencing、明确停止语义 |
| `accounting.py` | 预留/结算/未知消费 | usage 细分、父子 scope、跨项目池、收尾保留 |
| `research.py / progress.py` | 假设、反证、停滞 | 通用实验有效性、目标结果、事件驱动接续 |
| `context.py / evidence.py` | 有界 packet、来源和哈希 | 固定快照、独立评审输入、可查询证据索引 |
| `experiments.py / h1.py` | 现有适配边界 | 通用 Runner protocol；H1 保持可选实现 |
| `roles/*.toml / model_policy.yaml` | 角色定义与模型策略分离 | 按能力配置、实际模型解析、按事件触发 |
| 新 `api/`、`telemetry/`、`dashboard/` | 无需替换现有业务 | 只读投影、命令服务、SSE、前端 |

### 17.1 迁移步骤

M0 记录基线、所有既有不变量和真实版本；M1 先加只读事件/投影桥与对账，不启动新执行器；M2 用单个非敏感工程任务启用 Hybrid；M3 加可信命令操作与真实实验；M4/M5 完成资源压测、远程与发布打包。新旧路径可做只读影子比较，但不能同时执行同一目标。

**OPS-04，P0。** 正式切换前停止新派发、等待或核对全部活跃/UNKNOWN 工作、做一致备份、验证迁移结果、再转移控制 lease。自动回滚只允许回到兼容 schema 的版本；不可逆迁移不能靠直接启动旧二进制回滚。

历史记录保持原 ID 和原始来源，迁移增加映射而不伪造新的执行。所有预算总额与未结算项迁移前后逐项相等；状态迁移不能自动批准新范围。

## 18. MVP 与开发里程碑

| 里程碑 | 必须交付 | 完成门槛 |
|---|---|---|
| M0｜基线与能力验证 | 架构审计、兼容性矩阵、现有测试基线、ADR、fixture | 确认真实可用的 adapter 和不可保证的能力；无生产状态变更 |
| M1｜真实只读 Live | 增量事件/投影、snapshot+SSE、真实状态拓扑、断线追平、健康状态 | 未启动模型也可回放 fixture；连接旧运行器可显示真实事件；无模拟混入 |
| M2｜Hybrid 工程闭环 | 单一 skill、可信授权/STOP、任务/局部条件、有限任务 adapter、独立评审、预算与 writer 锁 | 非敏感工程任务从目标到独立验收完成；后台无用户逐步派工 |
| M3｜可控科研闭环 | 安全命令、STOP、通用 Runner、原始证据、负结果/UNKNOWN、下一步决策 | 一次真实受批准实验闭环及一次失败恢复闭环 |
| M4｜可靠性与效率 | cgroup、usage 结算、磁盘策略、24h soak、基准对比 | 全部 P0 不变量和故障测试通过，指标如实报告 |
| M5｜发布与远程增强 | 干净安装、升级/迁移、移动端、可信远程接入、完整回放 | 发布包可复现；远程控制通过权限与断线测试 |

**首个开发切片应为 M0 + M1，而不是立即重写所有调度逻辑。** M1 虽可使用 fixture 做 UI 自动化测试，但必须同时有真实运行器事件接入的验收，不能交付纯宣传动画冒充实时系统。

## 19. 需求范围冻结与变更流程

P0：单一入口、单控制核心、有限会话、可强制的权限/预算边界、独立评审、真实领域事件、基础 Dashboard、停止/恢复、最小实验闭环、迁移与安装检查。

P1：更丰富实验统计、移动端完整控制、历史 seek、跨项目资源公平性、协议验证后扩大原生子代理使用、更多项目 adapter。

P2：Jev/决策模型、自动优化路由策略、多主机、多个并行 writer、完整网页终端、WebGL、宣传视频导出、SaaS、多租户、第三方工作流平台集成。

新增需求必须说明用户问题、是否已有 Codex/现有模块能解决、增加的状态/权限/运行成本、验收条件与删除什么复杂度。不能因看见新 Agent 产品就再叠加一个常驻控制层。

## 20. 验收用例：Given / When / Then

| ID | 场景与前提 | 操作/故障 | 必须得到的结果 |
|---|---|---|---|
| A01 | 用户在 Codex 已安装 skill | 用自然语言提出目标 | 生成未批准提案，展示边界；无训练/模型后台任务抢跑 |
| A02 | 已批准有界工程目标 | 完成多个普通子任务 | 无需逐步人工指令；局部完成与全局验收分离 |
| A03 | 一个有效 controller | 启动第二个 controller | 只有一个可派发；旧 epoch 的放行/结果被拒绝 |
| A04 | Engineer 正写候选 | 第二写入者或子代理尝试写 | 被 OS/工具/lease 边界拒绝；产生审计；不只靠提示词 |
| A05 | Engineer 提交完成 | 同会话尝试自行批准 | 不接受为独立评审；安排新只读会话后才可交付 |
| A06 | 低风险微修改已有机器验收 | 连续几个局部步骤 | 不机械调用 PI/Architect；里程碑独立评审仍存在 |
| A07 | 同一错误无新增证据重复两次 | 再请求重试 | 触发一次诊断/升级，记录依据；不能无限相同循环 |
| A08 | 模型容量或 429 | 连续请求失败 | 有界退避，停止新派发；不记为科学负结果 |
| A09 | 子代理并发上限含父为 3 | 请求第 4 个会话 | 不启动；原生无法强制则禁用该委派能力 |
| A10 | 非原生兼容 adapter | 子代理事件/usage 不可得 | 显示不可观测/unknown，不画伪节点、不虚报成本 |
| A11 | 预算有未结算预留 | 重启、拆子任务或切 adapter | 总额与承诺不变，不恢复成满额 |
| A12 | 收到累计 usage 或重复 final 回执 | 重放两次 | 只结算一次；子父 scope 不重复加总 |
| A13 | 用户要求硬费用/token 上限但 adapter 无法强制 | 启动预检 | 拒绝严格配置或获取明确软上限批准；无伪保证 |
| A14 | snapshot 返回 C 后有新事件 | 随后建立 SSE | C 后所有关键事件被补齐且顺序正确 |
| A15 | 前端断开、乱序、重复事件 | 重连并补发 | 去重追平，与服务端投影一致；无重复动效/账款 |
| A16 | 旧游标超出保留范围或数据库恢复 | 用旧 cursor 连接 | resync_required；换新快照，不无限重试 |
| A17 | 无真实新事件 | 等待或改变浏览器时间/FPS | token、calls、条件满足数不自行增加 |
| A18 | GPU 仍在运行但浏览器失联 | 停网络 | 明确 OFFLINE/STALE；不宣称 GPU 停止；不继续假脉冲 |
| A19 | 用户在历史模式 | 移动 seek 或调倍速 | 只读重放，无命令副作用；清晰 REPLAY 水印 |
| A20 | 普通操作者发 Pause | 已有训练正在执行 | 禁止新派发，明确等待安全边界；不无提示杀任务 |
| A21 | 操作者发 Stop，网络丢失回执 | 重发同幂等键 | 返回同命令；禁止新派发；确认前不显示已停止 |
| A22 | 启动请求超时，是否执行不明 | 请求自动重试 | UNKNOWN、保留预留、先 reconcile；不重复 GPU 运行 |
| A23 | 旧 attempt 迟到成功结果 | 新 attempt 已存在 | 保留审计但拒绝更新新任务/全局验收 |
| A24 | checkpoint 很大且位于产物区 | 普通源码变更/指纹计算 | 不反复扫产物；大文件验证流式内存有界 |
| A25 | 子进程树内存/进程数超限 | fork 或分配压力 | 任务受限，控制与停止路径仍可用；无宿主失控 |
| A26 | 磁盘接近满或关键事件不可写 | 派发新任务 | 停新派发；关键事实保全；不自动删受保护证据 |
| A27 | 实验退出码 0 但产物不完整 | 收集结果 | 执行成功与有效性分离；不宣布研究目标成功 |
| A28 | 有效实验未支持假设 | 下一轮决策 | 负结果保留；新实验有判别理由；不隐匿失败 |
| A29 | 模型伪称用户已批准/提交 approve | 访问敏感操作 | 无人类 principal 则拒绝；proposal hash 绑定不变 |
| A30 | 恶意日志/产物路径 | 注入脚本、../ 或符号链接 | 无 XSS、越权下载或秘密暴露 |
| A31 | 两项目同时争用一个 GPU 名额 | 同时申请资源 | 主机原子准入，只启动许可数量；预算不混用 |
| A32 | 100k 历史事件/8h 页面 | 基准与长跑 | 达到或明确报告 NFR；无历史重写、DOM/内存无限增长 |
| A33 | 老版本真实状态和预算 | 迁移、演练回滚 | 审批/ID/预算一致；只有一个执行路径，兼容性验证通过 |
| A34 | 干净安装目录，无源码 checkout | 安装包启动 | schema/角色/静态页面完整，默认不触发业务运行 |
| A35 | 手机/键盘/减少动画 | 查看和操作批准/停止 | 关键信息可读、触控可用、无仅靠颜色或 hover 的信息 |
| A36 | 供应商升级或协议未知字段 | adapter handshake/运行事件 | 明确版本不兼容或安全降级；不静默丢关键状态/审批 |

真实模型与真实训练验收必须单独获批准；fixture 全部通过不等于真实 GPU/模型闭环已通过。每个用例记录环境、代码提交、输入、事件、结果和证据路径。

## 21. 建议数据与配置文件

项目适配配置建议放在 `.rlflow/project.yaml`，包含仓库、数据、产物、命令模板、角色政策、runtime 指纹和可用资源，但不包含人类批准凭据。运行状态位于项目代码之外的受保护目录。模型凭据只由执行宿主管理，不进入仓库或 Dashboard。

随包提供 `examples/project.example.yaml` 与 `examples/goal.fixture.json`。模板使用明显的 `SET_ME` 或 fixture 值；安装不得自动将模板当成授权。项目接入向导在批准前验证路径、模板参数、资源、数据版本和结果协议。

为了避免巨型提示词，Codex 初始只读取本文件第 1–7 节、当前里程碑的实施任务和相关 schema。其他章节按需检索；不能把全部历史、所有文档与日志反复拼接到每个角色上下文。

## 22. 必须完成的技术验证与默认处理

| 验证项 | 检查内容 | 不通过时的默认处理 |
|---|---|---|
| App Server 协议 | 本机版本、schema、初始化、item、usage、审批、中断、恢复 | 保留已验证 exec adapter，不对用户暴露新模式 |
| 原生子代理边界 | read-only 是否真实、后代计数、depth、usage、回收 | 禁用原生委派，使用已有受控短会话 |
| Docker cgroup | 委派权限、层级 memory/cpu/pids、监督资源隔离 | 标 partial，严格任务 fail closed |
| 审批桥接 | 能否证明批准来自真实用户而非 Agent 输出 | 用独立认证 Dashboard 完成人类批准 |
| 实验幂等 | 提交超时后的身份查询、collect 可重复 | UNKNOWN 不重试；要求人工核对或改进 adapter |
| 模型费用 | 是否取得实际 usage、累计范围及账单 | 明确 estimated/unknown；不提供硬费用保证 |
| 现有日志桥 | 能否提取真实结构化事件与状态快照 | 为既有 runner 加事件出口，不靠 NLP 猜日志 |

这些是开发任务，不是需要用户提前回答的产品问题。开发者应实测、记录证据与 ADR，并采用已规定的保守默认值。

## 23. Definition of Done 与交付物

完成一个里程碑必须提供实现提交、自动化测试、失败与恢复测试、需求到验收映射、可复现演示步骤、性能/资源记录、已知限制与回滚说明。不能只交截图、录像、静态 mock 或“Agent 认为已完成”的描述。

最终 P0 发布必须具备：一个可用的 Codex 入口；唯一持久控制核心；真实事件 Live 页；精确且可信的授权与预算；一个独立评审的工程闭环；一个有效性可审计的实验闭环；UNKNOWN 和 STOP 的故障测试；干净安装与迁移；非功能指标实测报告。任何指标未达成可发布为明确标注的测试版，不得宣称全部完成。

文档或产品中的术语应清晰区分：已实现、实验性、计划中、实测、估计、未知。Dashboard 标题显示真实版本与部署环境，fixture/demonstration 环境永久加标识。

## 24. 最终设计原则

rlflow 保留难以由聊天可靠替代的持久目标、权限、账本、实验身份、证据和恢复；Codex 承担有限任务内部的智能执行；界面帮助用户理解并控制真实系统，而不是制造“有很多 Agent 在工作”的观感。

资源优化顺序是：不做无必要工作 → 确定性处理 → 复用有效证据 → 低成本合适能力 → 有理由升级；不是降低所有评审强度，也不是把安全判断交给便宜模型。

**开发优先级：真实状态与唯一权威 → 安全执行与可恢复闭环 → 清晰实时界面 → 资源效率 → 动效与高级扩展。**

## 25. 文件架构
推荐把 **rlflow 当作一个独立安装的“控制系统/开发工具”**，而不是复制进每个待开发项目里。项目仓库只放少量 rlflow 配置；运行状态、账本、会话、实验元数据放在项目仓库之外。

最合理的关系是：

```text
rlflow = controller / runtime
project = workspace / target repository
```

而不是：

```text
project/
└── rlflow/
```

也不是：

```text
rlflow/
└── projects/
    └── instinctRL/
```

## 1. 我最推荐的目录结构

假设你机器上有多个项目：

```text
~/dev/
├── rlflow/                    # 你开发 rlflow 本身的 Git 仓库
│   ├── rlflow/
│   ├── roles/
│   ├── schemas/
│   ├── tests/
│   └── pyproject.toml
│
├── instinctRL/                # 项目 A
│   ├── .git/
│   ├── .rlflow/
│   │   ├── project.yaml
│   │   ├── policy.yaml
│   │   └── adapters.yaml
│   ├── src/
│   ├── configs/
│   ├── tests/
│   └── ...
│
├── uwb-imu-fusion/            # 项目 B
│   ├── .git/
│   ├── .rlflow/
│   │   └── project.yaml
│   └── ...
│
└── iap/                       # 项目 C
    ├── .git/
    ├── .rlflow/
    │   └── project.yaml
    └── ...
```

然后运行状态独立放：

```text
~/.local/share/rlflow/
├── instinctRL/
│   ├── state.db
│   ├── events/
│   ├── sessions/
│   ├── evidence/
│   ├── experiments/
│   └── logs/
│
├── uwb-imu-fusion/
│   └── ...
│
└── iap/
    └── ...
```

所以物理上其实有三层：

```text
               rlflow installation
                      │
                      │ controls
                      ▼
              target project repo
                      │
                      │ produces state
                      ▼
              rlflow state directory
```

这是我最推荐的设计。

---

# 2. 为什么不要把 rlflow 放进项目里面？

因为 rlflow 本身属于 **control plane**。

比如 instinctRL 是：

```text
~/dev/instinctRL/
```

如果你把 rlflow 也塞进去：

```text
instinctRL/
├── rlflow/
├── src/
└── ...
```

会产生几个问题。

### 第一，项目代码和控制程序混在一起

Engineer 本来应该只修改：

```text
instinctRL/src/
```

但现在它还能看到：

```text
instinctRL/rlflow/engine.py
```

很容易形成：

> “测试过不了，那我改一下调度器好了。”

这破坏了 rlflow 最重要的可信边界：

> **执行者不能修改控制者。**

---

### 第二，每个项目都复制一套 rlflow

例如：

```text
instinctRL/rlflow/
iap/rlflow/
uwb-imu-fusion/rlflow/
```

最后三个项目可能运行三个不同版本。

维护会非常麻烦。

---

### 第三，会污染 Git

你不希望：

```text
git status
```

里出现：

```text
.rlflow/state.db
.rlflow/session-218.json
.rlflow/events.jsonl
.rlflow/logs/...
```

运行状态不应该进入产品仓库。

---

# 3. 那为什么项目里还建议有 `.rlflow/`？

这里要区分：

```text
rlflow program
```

和：

```text
rlflow project configuration
```

`.rlflow/` 非常轻，只负责告诉控制器：

> “这个项目允许你做什么？”

例如：

```text
instinctRL/
└── .rlflow/
    └── project.yaml
```

可以是：

```yaml
project:
  name: instinctRL

workspace:
  root: ".."

write_scope:
  - src/
  - configs/
  - tests/

protected_paths:
  - data/raw/
  - checkpoints/reference/
  - evaluation/baseline/

commands:
  test:
    - pytest tests/

  lint:
    - ruff check .

experiment:
  adapter: instinct_rl

budget:
  gpu_hours: 40

dashboard:
  enabled: true
```

这样这个文件可以进 Git。

它描述：

```text
项目是什么
↓
允许改什么
↓
不能改什么
↓
怎么测试
↓
怎么运行实验
```

而不保存：

```text
Agent 对话
token usage
当前 task 状态
PID
experiment runtime
```

---

# 4. 所以 `.rlflow/` 应该分成“静态配置”和“动态状态”

这个边界最好现在就明确下来。

## Git 中：

```text
project/.rlflow/
```

保存：

```text
project.yaml
policy.yaml
adapters.yaml
```

属于：

> **declarative configuration**

---

## Git 外：

```text
~/.local/share/rlflow/<project-id>/
```

保存：

```text
state.db
events
sessions
locks
process identity
budget ledger
experiment records
dashboard runtime
```

属于：

> **mutable runtime state**

---

可以简单记：

> `.rlflow/` = “这个项目应该怎样被管理”
>
> `~/.local/share/rlflow/...` = “这个项目现在正在发生什么”

---

# 5. Experiment 输出应该放哪里？

这里又要再拆开。

假设 instinctRL 会产生：

```text
checkpoint
tensorboard
video
metrics
```

我建议不要全部塞进 rlflow state。

因为它们属于项目实验产物。

例如：

```text
~/experiments/
└── instinctRL/
    ├── exp-0001/
    │   ├── config.yaml
    │   ├── metrics.json
    │   ├── checkpoint.pt
    │   └── video.mp4
    │
    └── exp-0002/
```

或者如果你现有项目已经有：

```text
instinctRL/runs/
```

也可以保持现状：

```text
instinctRL/
├── src/
├── configs/
└── runs/
    ├── exp_001/
    └── exp_002/
```

rlflow 本身只保存引用：

```text
experiment_id: E0017

artifact:
  path: /home/mint/experiments/instinctRL/E0017
  digest: ...
```

而不要：

```text
~/.local/share/rlflow/.../checkpoint_8GB.pt
```

这种设计。

---

# 6. 最终其实形成四类数据

这是整个架构里很重要的一点：

```text
① rlflow program
② project source
③ rlflow state
④ project artifacts
```

对应：

```text
~/dev/rlflow
      │
      │ controls
      ▼
~/dev/instinctRL
      │
      ├──────────────► ~/.local/share/rlflow/instinctRL
      │                       control state
      │
      └──────────────► ~/experiments/instinctRL
                              large artifacts
```

四者职责如下：

| 内容 | 放在哪里 |
|---|---|
| rlflow 源码 | `~/dev/rlflow` |
| 项目源码 | `~/dev/instinctRL` |
| 项目 rlflow 配置 | `~/dev/instinctRL/.rlflow` |
| task / event / budget / session | `~/.local/share/rlflow/instinctRL` |
| checkpoint / dataset / video | 项目自己的 experiment/artifact 目录 |

这样非常干净。

---

# 7. Codex 又从哪里启动？

这个也应该统一。

我建议你始终：

```bash
cd ~/dev/instinctRL
codex
```

而不是：

```bash
cd ~/dev/rlflow
codex
```

然后在 Codex 内：

```text
$rlflow
```

或者：

```text
$rlflow improve training stability
```

rlflow 插件/skill/MCP 从全局安装位置加载。

逻辑上：

```text
current working directory
        ↓
~/dev/instinctRL

Codex detects:

./.rlflow/project.yaml
        ↓
rlflow identifies target project
        ↓
opens state:

~/.local/share/rlflow/instinctRL/
```

这样用户体验最好：

> **进入项目 → 打开 Codex → 用 rlflow。**

用户不需要：

```text
cd rlflow
rlflow attach /xxx/project
rlflow project switch ...
```

这正好符合你之前 AutoDev V4 的设计目标：

> 不希望用户记新的命令体系。

---

# 8. Dashboard 也应该绑定“项目”，而不是绑定 rlflow 仓库

比如：

```bash
cd ~/dev/instinctRL
codex
```

启动后 dashboard：

```text
http://localhost:8765
```

顶部显示：

```text
RLFLOW
Project: instinctRL
Workspace: ~/dev/instinctRL
Goal: Improve E0 locomotion convergence
Cycle: 12
```

如果同时有三个项目：

```text
instinctRL        RUNNING
iap               IDLE
uwb-imu-fusion    PAUSED
```

Dashboard 实际读取的不是这些目录：

```text
~/dev/rlflow
```

而是：

```text
~/.local/share/rlflow/<project-id>
```

它再通过 state 里的 workspace reference 找到：

```text
~/dev/instinctRL
```

---

# 9. 多项目情况下，不应该共用一个 state.db

我建议：

```text
~/.local/share/rlflow/
├── registry.db
│
├── projects/
│   ├── 31a7-instinctRL/
│   │   └── state.db
│   │
│   ├── 7b82-iap/
│   │   └── state.db
│   │
│   └── aa92-uwb-imu/
│       └── state.db
```

其中：

```text
registry.db
```

只负责：

```text
project_id
workspace_path
project_name
last_opened
status
rlflow_version
```

不要把所有项目：

```text
tasks
experiments
events
budgets
```

全塞进一张全局数据库。

这样某一个项目状态损坏，不会影响其他项目。

---

# 10. project ID 也不要只用项目名字

比如你可能有：

```text
/home/mint/dev/instinctRL
/home/mint/backup/instinctRL
```

不能都叫：

```text
instinctRL
```

建议第一次初始化生成：

```text
project_id:
2a63d6b8...
```

保存于：

```text
project/.rlflow/project.yaml
```

比如：

```yaml
project:
  id: 2a63d6b8-b579-...
  name: instinctRL
```

然后对应：

```text
~/.local/share/rlflow/projects/2a63d6b8-b579-.../
```

这样项目换目录：

```text
~/dev/instinctRL
→
~/projects/instinctRL
```

也不会丢状态。

---

# 11. 如果项目本身放 Docker 里怎么办？

你现在这个使用场景尤其重要。

例如：

```text
Host:
~/dev/instinctRL

Docker:
 /workspace/instinctRL
```

那么不要让 rlflow 认为这是两个项目。

项目配置中保存 canonical identity：

```yaml
project:
  id: 2a63d6b8-...

workspace:
  host_root: /home/mint/dev/instinctRL
  runtime_root: /workspace/instinctRL
```

结构：

```text
Host
┌─────────────────────────────────┐
│ rlflow controller               │
│                                 │
│ ~/.local/share/rlflow/          │
│                                 │
│ ~/dev/instinctRL ───────┐       │
└─────────────────────────┼───────┘
                          │ mount
                          ▼
Docker
┌─────────────────────────────────┐
│ /workspace/instinctRL           │
│                                 │
│ training / test / simulation    │
└─────────────────────────────────┘
```

**控制状态最好留在 host。**

不要把：

```text
state.db
process ledger
authorization
```

全部塞进容器。

因为容器重建时这些必须仍然存在。

---

# 12. rlflow 自己开发时怎么办？

这是特殊情况：

你可能正在：

```text
用 Codex 开发 rlflow 自己
```

这时：

```text
~/dev/rlflow
```

既是：

```text
controller source
```

又可能是：

```text
target project
```

这个时候不能让正在运行的 rlflow 随意修改自己的控制代码。

你现在原本已经有 frozen release / content-addressed control snapshot 的思路，这就是为这种情况准备的。

逻辑应该是：

```text
installed rlflow v1.2
        │
        │ controls development
        ▼
~/dev/rlflow     ← source candidate
        │
        ▼
tests
        │
        ▼
new frozen release v1.3
```

而不是：

```text
正在运行 engine.py
   ↓
Agent 修改 engine.py
   ↓
当前进程突然开始使用新代码
```

这一点一定保留。

---

# 13. 我建议下一版直接规定这个标准目录合同

可以正式写进 Hybrid spec：

```text
RLFLOW_HOME
~/.local/share/rlflow/

RLFLOW_CONFIG_HOME
~/.config/rlflow/

PROJECT_ROOT
<git repo>/

PROJECT_CONFIG
<project>/.rlflow/

PROJECT_STATE
<RLFLOW_HOME>/projects/<project-id>/

ARTIFACT_ROOT
project-defined
```

即：

```text
~/
├── .config/
│   └── rlflow/
│       ├── config.yaml
│       └── model_policy.yaml
│
├── .local/share/
│   └── rlflow/
│       ├── registry.db
│       └── projects/
│           └── <uuid>/
│               ├── state.db
│               ├── sessions/
│               ├── logs/
│               └── evidence/
│
├── dev/
│   ├── rlflow/
│   ├── instinctRL/
│   │   └── .rlflow/
│   └── iap/
│       └── .rlflow/
│
└── experiments/
    ├── instinctRL/
    └── iap/
```

这就是我认为 Hybrid rlflow 最稳妥的物理布局。

---

## 最关键的一句话

以后你可以把 rlflow 想象成 **Git / Docker / Codex 这一类工具**：

你不会为了开发：

```text
instinctRL
```

而把 Git 的源码复制进：

```text
instinctRL/git/
```

同理，也不应该把 rlflow 复制进项目。

应该是：

```text
安装一次 rlflow
        ↓
每个项目只有 .rlflow 配置
        ↓
每个项目有独立持久状态
        ↓
从项目目录中的 Codex 使用
```

我建议把这个直接作为 Hybrid v1 的**硬性架构原则**，而不是实现细节。这样以后无论你接 Codex CLI、Docker、远程服务器还是 Dashboard，都不会在“谁管理谁、状态应该放哪里”这件事上再次纠结。

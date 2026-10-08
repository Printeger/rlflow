# 本地只读 Web 服务（T06 基础切片）

checkpoint32 已接入本地不可执行条件事实控制 UI：显式1.1项目、human角色、原始JSON DRAFT、私有审阅/精确确认/撤销及手动同键重试，见 [HYBRID_CONTROL_UI.md](HYBRID_CONTROL_UI.md)。默认1.0仍只读，未启用lease/模型；旧“确认UI尚未接入”段落为历史范围。

显式启用的控制项目在 checkpoint31 新增真实 Goal head 列表与 human private review；权限、来源覆盖和非执行范围见 [HYBRID_GOAL_READS.md](HYBRID_GOAL_READS.md)。尚未连接 Dashboard 确认交互。

当前提供真实 SQLite 观测 API、SSE 和 `/` 下的只读 Dashboard；不能据此判定 M1 完成。默认 `1.0` 配置不开放命令或修改批准。checkpoint30 新增受保护本地 `1.1` 配置，可显式启用不可执行的 DRAFT/条件批准/撤销 HTTP 服务，见 [TRUSTED_WEB_CONFIG.md](TRUSTED_WEB_CONFIG.md)。两者均不启动 scheduler、模型、lease，不提供 artifact 路径；启动不创建/迁移业务 Store。

安装项目运行依赖，并对一个已存在的 rlflow state 显式启用观测：

```bash
.venv/bin/python -m pip install -e .
.venv/bin/python -m rlflow.web prepare --root /absolute/existing/state --project-id project_local --config /absolute/private/web.json
.venv/bin/python -m rlflow.web serve --config /absolute/private/web.json
```

`prepare` 提示输入并确认至少 20 字符的口令，不接受命令行口令。配置只保存 PBKDF2-SHA256 盐与摘要、项目根和 scope，文件以 0600 独占创建，拒绝覆盖。失败后的文件保留用于明确检查，不自动删除。加载时拒绝 symlink、非当前用户拥有、可被其他用户访问的配置。配置仍属于敏感本地材料，不能提交或上传。

默认 `http://127.0.0.1:8765`；只支持明确 loopback IP 和端口，不提供公网、代理或 TLS 部署。本切片关闭 proxy headers 和 HTTP access log。服务重启使全部会话和 Bearer 失效，不会影响业务 Store。

测试/演示 state 必须在 `prepare` 指定 `--data-mode fixture`，不能把 fixture 标为 live。已启用项目身份和模式不可被 prepare 重命名；不提供生产迁移或 restore 管理端点。

## 认证与只读接口

同源 JSON `POST /api/v1/login` 接收 `principal_id=local`、`passphrase`，要求精确配置 Origin 和 Host。Cookie 为 HttpOnly、SameSite=Strict、Path=/，默认 15 分钟内存会话。口令不能放在 URL；服务没有默认口令、注册或远程发 token 接口。登录全局限频、请求体最多 4 KiB，并限制体接收时间。

`GET /api/v1/session` 提供 principal/scope 与当前 session CSRF。`POST /api/v1/logout` 还要求同源 Origin 和 `X-CSRF-Token`。trusted Python integration 可显式创建仅 viewer、最多 5 分钟的 Bearer，只接受 Authorization header；不能用 Bearer 充当 Cookie 或赋予 Agent 人工 approver 权限。

| 路由 | 数据语义 |
|---|---|
| `GET /health` | 匿名最小 ready，无项目/路径/进程信息 |
| `GET /api/v1/projects` | 当前 principal 可读项目，最多 128 |
| `GET /api/v1/projects/{id}/snapshot` | 同一事务内投影与 durable cursor，初始最多 30 对象 |
| `GET /api/v1/projects/{id}/objects?kind=execution&after=...&limit=50` | keyset 公共对象页，最多 200，不读取私有日志/文件 |
| `GET /api/v1/projects/{id}/objects?kind=tool_return&after=...&limit=50` | 闭合、已验证绑定的CPU返回，PARTIAL；不是启动/成功或全部调用数 |
| `GET /api/v1/projects/{id}/events?after={cursor}` | 单项目完整 durable SSE；重连 Last-Event-ID 优先 |
| `GET /api/v1/projects/{id}/domain-events/{event_id}` | 懒加载单个有界公共事件，project/epoch/seq/digest 校验，不读取私有日志 |
| `GET /api/v1/projects/{id}/logs?severity=ERROR&kind=task&object_id=ref_...&limit=50&after=...` | CORE_STATUS或独立TOOL_METADATA日志summary，索引keyset/high-water；不带正文 |
| `GET /api/v1/projects/{id}/logs/{log_id}` | lazy固定模板正文与公开来源证明；raw logs PRIVATE_ONLY；旧CORE_STATUS工具metadata仍UNAVAILABLE，新工具模板为BOUND_RETURN |

每个读事务都重新校验 project/data_mode，避免数据源替换时越项目泄漏。无权限项目返回 404；源不可用或身份不一致不返回内部 SQLite 错误和路径。原公共字段 allowlist/脱敏仍适用。ROLE_IDENTITY 不是实际运行证据：T05 尚未完成，旧 RUNNING 仍映射 STARTING，usage/cost 缺证据仍 UNKNOWN。

SSE：`domain` 有 durable id；5 秒 `heartbeat` 无 id；`resync_required` 携带 `code=RESYNC_REQUIRED` 和固定 reason，之后关闭。epoch/历史缺口、会话失效、队列溢出都要求重新获取快照。socket send 超过 2 秒直接关闭，重连使用客户端最后 durable id；已阻塞的 socket 不强行追加控制帧。每个连接仅预取一个事件，队列最多 32 帧/4 MiB，服务最多 8 条流。性能合同、遥测和日志尚未全部验收。

公开 OpenAPI/docs 与任意 artifact 均不存在；默认配置没有写命令，显式控制配置的命令范围见 TRUSTED_WEB_CONFIG.md。响应设 no-store、nosniff、no-referrer、self-only CSP（包括 form-action）。UI 仅文本渲染，未将口令/session/CSRF 持久化到浏览器 storage。JavaScript 不工作时表单也只使用 POST；后端拒绝非 JSON 请求。新认证清空旧身份 DOM/缓存，认证和项目异步响应有独立 generation guard。

打开服务的本地 URL、使用 prepare 配置的主体与口令。纯 reducer 将 snapshot 与 SSE 接缝、epoch、去重、对象版本和权威 counters 分开。总对象缓存最多200，保留最近至多30 execution/10 stage；事件摘要200，虚拟窗口只渲染可见行，方向键/Home/End/Enter可导航与读详情，阅读位置按事件ID保持。费用/模型活动/资源未知不会改为0/RUNNING；Fixture始终有标签。静止/追平/离线/隐藏/减少动画不持续运行脉冲。已接入绑定CPU返回metadata；资源、条件矩阵、完整error合同、真实运行/长期soak仍待完成。

## 工具返回覆盖与升级

新prepare/显式enable会固定公共工具覆盖起点。旧观察者的GET不升级，snapshot.projection.tool_observations为null表示未启用；已启用对象包含status=PARTIAL、policy=LIVE_ONLY、coverage_after_seq、coverage_after_source_version、source=BOUND_CPU_RETURN。起点是公开采集边界，不是命令发生时间；observed_at为core提交时间。旧COLLECTED receipt不自动回填。epoch恢复保留原公开起点及历史投影，日志自己的retention floor独立生效。

只接受collector已提交的COLLECTED/VERIFIED返回并核验context/registration/fact一致；v2 validation digest覆盖冻结task，旧v1即使有task字段也公开null，不查询当前session追认。工具对象只有cpu_exec、有限返回状态/退出码/报告耗时、opaque execution/task关联；不公开命令、argv/cwd、stdout/stderr、路径、原始context/hash。RETURNED不是成功，SETUP_FAILED不证明命令启动，不改执行状态或权限预算。公共数量仅为已公开返回，PENDING/UNVERIFIED/UNSUPPORTED/QUARANTINED/无journal与更早调用仍UNKNOWN。

覆盖table存在但缺singleton，或table缺失却已有公共工具projection/counters，显式enable拒绝RESYNC_REQUIRED；不能通过prepare重置起点后把旧总数伪装成新覆盖。没有提供自动修复/restore管理端点，保留损坏状态等待可信离线恢复。

## 验证

公共日志仅证明核心已提交状态观测，不是模型原始stdout/stderr/思维过程。新prepare自动启用；已有观察者不在Web GET升级。若只缺全部三日志表，可在可信终端显式调用原有 `enable(Store(existing_root), existing_project_id, data_mode=existing_mode)`，不重写已有登录config；从启用seq开始记录，coverage_after_seq说明历史缺口。部分缺表拒绝，需后续明确离线恢复，不能新建空refs伪称覆盖完整。日志列表cursor不是SSE cursor，改变kind/id/severity需重新从首页读取。

UI“公共观测日志”支持级别与task/execution/experiment公开ref ID筛选；类型和ID必须一起填写。单页50条、下一页固定原high-water，不累计无界DOM；Enter/点击才读取正文。新提交只提示可能不匹配筛选，点击读取最新才更新日志页，不改业务cursor。页面显示coverage边界，空页不代表没有更早历史；TOOL_METADATA与CORE_STATUS独立模板，raw logs PRIVATE_ONLY。刷新失败保留同项目日志并显示OFFLINE，换项目/身份/epoch则清除旧页和详情。

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_web_auth.py tests/test_web_api.py tests/test_live_stream.py tests/test_web_local.py tests/test_hybrid_observation.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_public_logs.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_public_tools.py tests/test_tool_collector.py
```

包括真实 loopback socket 上提交后的 SSE 事件与 Last-Event-ID 重连；不是模拟业务模型成功。独立 High 审查关闭了读源 TOCTOU 和健康积压误判；最终系统审查仍未完成。

可选隔离浏览器 QA（需本机已有可用 sandbox Chrome，不自动安装或关闭 sandbox）：

```bash
npm ci --prefix web_checks
node --test web_checks/reducer.test.mjs web_checks/virtual-list.test.mjs web_checks/log-view.test.mjs web_checks/browser.test.mjs
```

测试启动 stdin 控制、loopback 临时 fixture，检查实际持久化提交到 SSE/DOM、离线追平、208 项总数与有界窗口、XSS 文本、键盘详情、手机无横向溢出、日志high-water/过滤/lazy正文/乱序和刷新失败保留、身份更换和迟到响应、无 JS 原生 POST。新增工具浏览器case使用序列化可信core Fixture，证明API/SSE/UI路由，不证明实际CPU/vendor执行；真实model-free CPU→core→公共查询另由test_public_tools验证。结束关闭 Chrome、服务并清理其唯一临时目录。截图保存在忽略的 web_checks/artifacts；不触碰真实 state、模型、GPU或根目录用户 package-lock。

Checkpoint13新增认证只读 `GET /api/v1/projects/{project_id}/telemetry`，返回独立latest-only真实OS样本或null，完整合同见RESOURCE_TELEMETRY.md。新prepare显式初始化空slot；旧observer必须可信终端显式enable，GET不会升级。core reconcile做nonblocking采样，单独Web服务不启动scheduler/模型或后台sampler，因此无core采样时不会假造资源。sample_age与worker freshness不同于server heartbeat；来源陈旧、generation变化和未知GPU不显示0。Dashboard telemetry SSE/资源面板下一项接入，现有browser通过不证明它们已交付。

Checkpoint14已将资源面板接入同一个项目SSE的独立 `event: telemetry`（无id），不再需额外HTTP轮询。每秒source读取/面板渲染，sample_id去重、source版本因果barrier、陈旧年龄及UNKNOWN/PARTIAL明确显示；HOST内存/磁盘不是项目quota，占用不能混用。单独Web无core时仍无样本；已有checkpoint13槽缺新causal witness则worker双UNKNOWN直到下一实际采样，GET不回填。Chrome QA的telemetry控制仅stdin触发实际OS采样，不增加HTTP写指令，不启动scheduler。资源显示不代表M1 gate或资源强制已验收。

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_telemetry.py
```

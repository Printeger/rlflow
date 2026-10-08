# Checkpoint 04：初始只读 Dashboard

2026-10-08，继承 `1f45a98`，属于 T07/T08 实现切片，不是 M1 或完整 Goal 完成。

交付 `/` 同源静态 shell、纯 reducer 和真实 snapshot/SSE/paged-object/public-event-detail UI。实际任务/执行/审批总数来自权威 counters，与 200 对象缓存分离；执行卡片最多 30、stage 最多 10、对象页 50、紧凑事件摘要 200。详情仅公共 envelope，文字 textContent，无 credentials/session/CSRF 浏览器持久化。可观测旧 RUNNING 仍 STARTING/PARTIAL，费用/资源未知明确显示 UNKNOWN，没有虚构角色或业务计数。

连接支持 durable cursor、去重、epoch/gap/incompatible 拒绝、snapshot resync、自动重连、离线保留、catchup 静止、reauth。分页同事务 cursor/project/mode 与当前 reducer 一致才合并，不能复活迟到删除。心跳只更新连接和服务端时间；仅真实新事件触发短暂卡片高亮，一个受控非空闲 rAF、最多 30 callbacks/s，离线/隐藏/减少动画停止。

## 独立安全复核

High 只读 agent 发现三项 MUST_FIX，均已修复并独立复验：

- 原生 login 默认 GET：改 POST/action，CSP form-action self，非 JSON fallback 403，口令不入 URL。
- 新主体没有项目时复用旧 DOM：新 session 验证成功立即清整个旧缓存/DOM/details；auth generation/AbortController 避免 logout 或重复登录的迟到响应重开 dashboard。
- 首次 render 的 `false?.dataset.eventId` 抛异常：空 anchor 使用 null，实际 Chrome 正常渲染。

额外防御：详情和 SSE 都在读事务核查 event.project_id；对象洪流不再挤掉有界执行/预算窗口。审查独立 Python 34 passed、Reducer 8 passed、DOM stub 首次渲染和身份切换通过；当前已交付范围无剩余 MUST_FIX，未修改文件。

## 实际验证与限制

冻结全回归 **402 passed / 32 skipped / 1 warning / 139.90s**，编译与 diff check 通过，版本化输出/精确源码哈希见 [evidence/checkpoint-04-final-tests.txt](evidence/checkpoint-04-final-tests.txt)。32 项外部依赖 skip 和 Starlette deprecation 与上 checkpoint 保留。

目标 Python 子集 52 passed/1 warning/3.81s。sandbox Chrome 151.0.7922.108、playwright-core 1.55.1，真实 loopback 临时 Fixture 的 browser+reducer r2 **9 passed / 0 skipped / 3.99s**。browser QA 覆盖 durable SSE/DOM 一致、STARTING/UNKNOWN、XSS literal、键盘详情、offline 保留与追平、205 次 burst 后总数 208 且窗口有界、空闲 heartbeat 不触发应用 rAF、390px 无横向溢出、跨主体清缓存、logout 迟到 projects、不启用 JS 时 native POST。Fixture 服务、Chrome 和唯一临时 state 正常关闭/清理；没有模型/GPU/生产状态/发布。

首轮新增 idle-rAF instrumentation 失败 **8 passed / 1 failed**，因为测试工具自身 `waitForFunction` 也用 rAF；不是删断言，改为只记录调用栈来自 app.mjs 的 rAF 后通过。保留原日志 `audit/hybrid-v1/checkpoint-04-final-browser.log`，通过日志为 `checkpoint-04-final-browser-r2.log`。Python 子集新增负例最初 fixture corruption 被 append-only trigger 拦截、fallback 实际为403而非400；测试明确在临时库绕过 trigger 注入错误，断言正确拒绝语义，不修改生产安全策略。一次 `.venv/bin/pytest` collection 失败由于未将仓库加入 sys.path，改用既定 `.venv/bin/python -m pytest`。

日志/资源 telemetry、列表虚拟化、历史初次加载、完整 error contract/筛选、真实运行器到浏览器验收与 8h soak 均未完成。后续继续 T05/T07/T08，再执行 M1 gate；M2–M5 不省略。Sites 技能只用于现有 backend 的 local-only QA，不注册、不发布、不替换成外部托管服务。根目录用户 package-lock 原样保留。

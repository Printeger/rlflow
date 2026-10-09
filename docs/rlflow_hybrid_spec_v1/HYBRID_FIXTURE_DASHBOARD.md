# 固定 CPU Task Dashboard：Checkpoint 47

## 交付行为与边界

现有本地 Dashboard 新增独立固定 CPU 协议面板。它读取45原事件核验的 Task API，人工 operator 可手动调用46既有 Start/Stop API；不改变 Goal 面板的不可执行条件批准，不把固定 Task 混入旧执行计数，不新增调度器。

可信启动仍先登记原 Task，再显式注入 `fixture_task_readers` 和 `fixture_runtime_services`。未安装控制接口时只显示历史；live 项目不加载 fixture 面板。没有上传任意程序、创建 lease、选择 PID、接管历史 owner 的网页入口。

新增 `GET /api/v1/projects/{project_id}/fixture-runtime-profile`，同项目 viewer session/bearer 可读，禁止额外 query，默认未安装404。闭合响应包含 Hybrid 原项目/模式/epoch/as-of 元数据及：

```json
{"control_api_installed":true,"original_owner_available":true,"profile":"FIXED_CPU_SINGLE_PARTICIPANT","native_execution_enabled":false,"arbitrary_tree_stop":false}
```

`original_owner_available` 只说明读时原 Runtime 仍在原进程内，不逐 Task 授权，不保证将来的 session、Controller、Budget 或效应门通过。GET 不创建 Task、不 poll、不写事实；原 owner 关闭后为 false，历史 Task 仍能读取。历史 Task 的 `controls_available=false` 保持不变。

## 人工命令、异步与恢复

选择 Task 后，Start/Stop 使用该次详情读取的确切 `as_of_state_version`，不自动改写 CAS 版本。Start 仅限 REGISTER_NO_HANDOFF；STOP 仅请求原固定范围。所有 DOM 正文使用 textContent；DTO 必须闭合、项目/epoch/实际 Task/Attempt/selector 匹配，整数须在 JavaScript 精确范围内。

命令在途时禁止刷新、翻页和选择其他 Task，方法入口也拒绝这些动作，避免丢弃命令响应而卡住 IN_FLIGHT。身份、项目、epoch、退出登录与认证到期仍立即清除本地意图和 DOM；晚到响应不能恢复旧身份内容。

网络/不一致回执等结果 UNKNOWN 时只提供手动原 body/key/selector 重试，不自动 POST。400/401/403/404/409/422 拒绝后不自动重基或重发，须明确重新读取。清除本地意图不取消服务器执行。

Start ACCEPTED 只显示原接收事实，再读取 Task 列表；原 key 重试不重新派发。STOP ACCEPTED **保留原意图**并显示“手动继续原 STOP 清理”：接受后清理可能尚未完成，Task 已终态也不能证明 PoolFREE；只在人工清除或身份/scope 清除时退休本地原 STOP。手动续清走46既有原 lease/whole STOP/实际来源守卫，不新增命令或执行 owner。

## 本切片验收

- 实际隔离 loopback 服务、Chrome、原固定 CPU Popen/G/ACK，不以模拟 fetch 冒充执行。
- 丢弃已接受 Start 的浏览器返回，人工重试 body/key 完全相同、duplicate=true、原状态版本不变。
- 在原 durable STOP 后注入一次实际 Source 清理异常：202/STOP_REQUESTED/Pool占用仍1，人工原 body/key 续清后原 producer 已 reap、实际 Pool占用0。
- 页面保留 current_execution_status=UNKNOWN、resource_release_status=NOT_OBSERVED；不从历史 ACK/终态推断当前运行或 FREE。关闭原 owner 后只读历史，退出登录清除详情/回执。
- 单元检查 sparse 扫描页、闭合 DTO、错误 scope/unsafe int/假执行声明、viewer/dead owner、晚到选择/身份响应、在途刷新与 STOP_REQUESTED/终态的原意图保留。

实际命令、终态、日志 SHA 与必要前后端回归见 `evidence/checkpoint-47-final-tests.txt`。首轮通过后独立发现的两项命令恢复 MUST 已修复；浏览器第二轮 owner 文案超时真实失败保留，没有放宽超时或删除检查。

本切片只证明 LOCAL_PROTOCOL_ONLY/FIXED_CPU_SINGLE_PARTICIPANT，不证明 native/模型、候选修改、任意树 STOP、真实工程科研闭环、付费用量、严格 OS/data/network 门或完整 Goal。无需迁移任何既有生产状态。

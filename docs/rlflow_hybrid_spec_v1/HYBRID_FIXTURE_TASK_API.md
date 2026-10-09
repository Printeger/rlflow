# 固定 CPU Task 只读 API：Checkpoint 45

交付的是可调用的实际 Task 列表、详情与时间线，不是准备组件，也不是 Start/Stop 控制完成。来源是 Checkpoint44 原 Budget/Runtime 事件，不写 legacy tasks/sessions，不创建 Store、不做迁移、不恢复执行 owner，不调用 Source.poll 或检查/接管 PID。完整 Goal 和验收合同不变。

## 可信启动与接口

可信 host 在已有 registered fixture Store 上构造 `FixtureTaskReader(store, project_id=..., store_epoch=...)`，传给 `create_app(..., fixture_task_readers={project_id: reader})`。默认参数为 None，因此原 API 保持只读原行为且不启用这些路由；startup 核实际项目、fixture 模式、root、epoch。历史读取可使用 `Store.attach_existing`，不需要 Runtime owner，也不产生运行许可。这里没有 HTTP 文件路径/epoch 上传、模型或程序参数入口。

- `GET /api/v1/projects/{project_id}/fixture-tasks?after=...&limit=10`
- `GET /api/v1/projects/{project_id}/fixture-tasks/{reservation_id}`
- `GET /api/v1/projects/{project_id}/fixture-tasks/{reservation_id}/timeline`

`reservation_id` 是实际持久 Budget ReservationHEAD 的索引 selector；响应另含原 owner 派生的 `id`（Task ID）及 Attempt ID。selector/DTO 都不是 lease。页大小1–20按**扫描的 reservation**计数，非 runtime reservation 不显示为 Task；next_after 跟随扫描 key，稀疏页不能被误解为已到末页。未知 selector 为404，非闭合/重复/非法查询为400，损坏原源/epoch/超限为脱敏503。POST 不支持。

人工 session 与短期 bearer 都只能读取所属项目；未登录401、其他项目404、异源403。读取后重新检查身份和 epoch，撤销会话不继续返回旧读取内容。接口沿用同源与 no-store 等响应边界；没有授予 bearer 控制权限。

## 数据含义与来源

每项读取同一个只读事务中的元数据、原 ReservationHEAD、按 reservation 索引的最新 Budget event、完整原 event payload/input versions/derived objects，再比较原 HEAD 与派生 HEAD。`source_coverage=ORIGINAL_EVENT_VERIFIED` 指 Budget 原事件验证，不宣称全量审计、当前批准/FD有效或实时进程状态。列表不扫描全部事件；时间线沿原 previous hash 与派生 prior HEAD 最多七个阶段，循环/错 scope/乱序/超界失败关闭。

所有 SQL 选出的 key（包括 peek/cursor）在读取至 Python 前限制为 text/160 UTF8 bytes，再校验闭合 ID；单请求累计读取/展开16MiB，输出64KiB。已有源/blob原预算仍生效。合法大型源超出这条读路预算会503，不通过提高执行或维护预算掩盖。

响应展示 `recorded_phase` 和 as-of version；`current_execution_status=UNKNOWN`、`controls_available=false` 始终明确：STARTED 历史事实不是当前 live，历史终态也不是当前可接管资源。仅项目事实读取不能证明 Pool FREE，所以 `resource_release_status=NOT_OBSERVED`，不把项目 FIXTURE_SCOPE_STOPPED 冒充跨库回收已完成。终态可展示原记录 wall-only 消费；模型实际费用 UNKNOWN、synthetic tokens 不结算、任意树 STOP false。

闭合 DTO 不返回 nonce、PID/boot/starttime、lease、文件路径、命令/程序 hash、原 witness 或私有 Source 物料。不自动填入 legacy Dashboard fake Task，不声称完整实时 UI 已接通。

## 验收与剩余缺口

实际原固定 CPU running → 原 ACK → STOP 后七阶段读取、cold reader一致、GET不poll/不写状态、默认未启用、权限/同源/闭合query、原源/HEAD损坏、超大SQL key、读后撤销、实际自有 loopback HTTP 都由新用例验证。首轮坏 projection INSERT 夹具与对应清理失败保留，修复只重跑受影响项；新增安全修复与最终回归结果归档于 evidence/checkpoint-45-final-tests.txt。

下一46是人工授权 Start/Stop 的真实后端命令闭环：原 writer/COMMIT/Popen/G 末端 session 核验、durable acceptance/CAS/idempotency、断线不重开、STOP独立容量且接受后能继续安全清理、未知恢复不接管。这些尚未由45完成。native/model/candidate/delegation、任意执行树、工程科研任务、长期与 UI/安装迁移验收继续待办，paid/GPU/系统/生产权限不变。

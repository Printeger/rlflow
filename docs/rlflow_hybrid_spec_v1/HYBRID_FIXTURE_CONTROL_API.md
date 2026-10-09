# 人工授权固定 CPU 执行与 STOP：Checkpoint 46

本切片接通受保护的真实固定 CPU Task：人工 HTTP Start → 原 phase/CAS 接受事实 → 实际 Popen/G/原 ACK → 人工 HTTP Stop → 原 STOP 事实 → 原进程回收、全部 FD 关闭、wall-only 终态结算与 Pool FREE。它不是 native/model/candidate/delegation 执行器，不代表通用任务调度、工程科研任务、任意进程树或完整 Dashboard/Goal 验收。

## 可信启动与请求

可信 host 先通过 Checkpoint44 原 WorkingPlan/Goal approval/Workspace/Budget/Pool 能力登记 Task，再构造 `FixtureRuntimeControlService(actual_runtime, same_approval_auth_store, origin=...)`。同一原 Runtime 不可重绑；仅 registered fixture 同 root/project/epoch，不能从历史数据库或 JSON 恢复 owner。传给 `create_app(..., fixture_runtime_services={project_id: service})`；默认 None 不开启。读取可另外注入 `{project_id: service.reader}`。没有 HTTP 创建 Task/lease/进程/Pool、上传 path/argv/usage 的入口。

`POST /api/v1/projects/{project_id}/fixture-tasks/{reservation_id}/commands`

必须是当前所属项目的人工 operator session、确切 Origin、session CSRF、JSON Content-Type 和单一合法 Idempotency-Key。bearer 只读、approver不自动成为operator、Agent没有人工登录权限。请求严格只含：

```json
{"action":"START_FIXED_CPU","task_id":"实际TaskID","expected_state_version":123}
```

Stop 使用 `STOP_FIXED_SCOPE`，其他字段同上，版本取最新一致读取。BOOL/负数/未知字段/歧义关键 header 拒绝，selector 必须匹配实际 Task。没有“复制 lease 即获得执行许可”的 fallback。CAS 冲突返回409，客户端应刷新事实并明确提交新的请求，不自动放宽版本或续期。

`GET /api/v1/projects/{project_id}/fixture-commands/{command_id}` 是所属项目只读接受 receipt，人工 session 或 short-lived viewer bearer 均可读。body 不是私有原 guard、lease 或 Source witness。

## Durable 接受、幂等与 UNKNOWN

不另建准备队列/命令账本：Start 的 `HANDOFF_UNKNOWN`、Stop 的 `STOP_REQUESTED` 原 Budget event 就是命令接受事实。命令与原 phase 的 CAS 在同一实际 COMMIT，`accepted_state_version=expected_state_version+1`。`202/status=ACCEPTED` **只说明接受**，不冒称 STARTED/STOPPED、Pool已释放或费用已知。

独立 fixture 命名空间为 project/mode/**store_epoch**/actor/client-key。action、Task、expected version 只进入内容 hash，不进入命名空间；因此同 actor/key 换 action/task/version 是409冲突。epoch 隔离属于这个明确的 private fixture 接口，不冒充通用 PRD commands 的跨epoch幂等契约。command_id 可确定计算原 Budget entry key，按已有 immutable idempotency 索引读取 whole 原事件，不扫描 payload 或只读最新 HEAD 猜 receipt。

`start_command` 只在首次 HANDOFF 接受 phase 出现，`stop_command` 只在首次 STOP 出现；后续字段存在性和完整内容不可变。原 accepting raw 在 COMMIT 前保留，失败后不能由不同 actor/key 接纳，不能覆盖/回填旧 raw。原请求只在其原 CAS 仍有效时恢复已知未提交接受；接受已落库的 Start 重试永远仅返回原 receipt，不再次 Popen/G、不继续 UNKNOWN handoff。

新 key 不给已 handoff/安全停止的 Task 补造第二个接受事实。旧44没有 human command 的历史阶段不能由46补写。未知 Popen/G/跨库结果、FD损坏、restart/TTL/PID消失都不能接管或自动退款。

已接受 Stop 的原 key 重试有一个刻意的例外：fresh 人工认证后，核原 whole STOP event、原 actor/body、当前 matching stop_command 和**仍持有的实际同一 lease**，再仅继续原 STOP 安全收尾。它不是第二次命令、不恢复 Popen/G、不创建新 owner。真实 source/身份/FD仍损坏则保持 UNKNOWN，不把接受202冒充清理完成；仅有限一次收尾尝试，不开第二 Supervisor。

## 实际授权与安全观察

锁顺序是 Pool → Store writer/BEGIN → Controller/原 Workspace/Working/Plan/Runtime locks → 同一 AuthStore 的实际 issued operator guard。HTTP 预鉴权不是执行权限；原 Auth guard 持有至实际 COMMIT，事务间、最终 Popen/G 以及最后轻量期限采样重新检查 session/CSRF/actor 与原 lease/command。权限在写锁等待期间撤销、COMMIT 前过期、G 前过期都不能被 earlier HTTP success 掩盖。

绑定 service 后，原 Runtime.start 也要求实际 issued Start 操作，避免绕开 HTTP 接线继续由 bound owner新放行。真正持久 STOP 接受后，后续原进程/FD清理不需要当前 session/Controller/consent仍有效；protected owner的安全 shutdown 也不伪造 human command。

`STARTED_AS_OBSERVED` 只可能从同一原 RELEASE_INTENT 的实际一次 G/nonce/source ACK推进，且尚无 STOP；原 producer/offset/hash能力仍必需。观察不是新grant，所以可以在session/Controller期限过后记录真正ACK。绕过新工作权限的 writer 仅限 ACK observation、STOP、terminal 三个明确 phase，不能把 cleanup flag泛化到Popen/release/新执行。

正常第一次 Start 有一个有限 observer，GET 从不poll/写事实；accepted Start异常分支则直接保守返回原接受receipt，**并不保证这条异常路径自动记录后来的ACK**。post-G过期负例由原 owner显式poll验证观察能力，不能将其表述为所有异常路径的自主观察闭环。

fork 后原 Runtime 能力永久失效。direct execute 在 Auth 前拒绝；已知 fixture POST 在异步入口、Auth/ControlPool队列之前拒绝，再保留 worker/writer/effect原后检。实际持Auth锁/预热执行器的fork负例证明子进程有界拒绝、父进程仍可执行。该边界不宣称整个 Web/Auth 的任意入口都 fork-safe；重新读取历史仍应可信冷启动配置独立只读来源和Auth，不接管旧执行 owner。

## 断线、容量与验收边界

请求断线不会取消实际有限 worker，容量随原 Future 生命周期释放；重试不再启动。Stop拥有单独容量通道，但仍遵守真实 Pool/Store/原 source 锁，不声称无锁等待或全主机SLA。用例实际在Start通道满额、主线程持Pool锁时提交Stop，释放原锁后确认原回收/FREE，而不是只测两个队列名字不同。

真实 loopback socket断线→同 key重试→只有一次 Popen→人工Stop实际释放已验证；明确仍 `FIXED_CPU_SINGLE_PARTICIPANT / LOCAL_PROTOCOL_ONLY`。模型实际费用 UNKNOWN、synthetic tokens不结算、任意树 STOP false。readonly Task API仍以 recorded_phase/current UNKNOWN区分历史与当前能力；完整实时前端、通用PRD命令、native/模型用量invoice、严格OS/data/network/candidate、工程科研与长期/UI/安装迁移验收继续待办。

开发成功/失败、两项独立MUST和已知变量位置修复、必要唯一集成实际结果归档于 `evidence/checkpoint-46-final-tests.txt`。当前切片不能代替完整 Goal。

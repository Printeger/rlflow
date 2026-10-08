# 显式启用的 Hybrid 控制 HTTP 桥

checkpoint32本地 UI 已增量接入，见 [HYBRID_CONTROL_UI.md](HYBRID_CONTROL_UI.md)。没有新增控制语义或lease/启动接口；默认只读行为不变。

checkpoint31 新增同固定服务/有限 pool 的 Goal head 列表与 human private review，完整读取合同及来源证明见 [HYBRID_GOAL_READS.md](HYBRID_GOAL_READS.md)。原命令语义不变，不授执行权。

Checkpoint29 实现：root 与独立 High 13 模块各 289 项通过，冻结全量原10082终态867 passed/32既有skipped/1既有warning/267.24秒，范围无剩余 MUST_FIX。包含实际 owned loopback HTTP 断连与条件性批准；不是 UI、安装配置或完整 T16 验收。证据见evidence/checkpoint-29-final-tests.txt。

## 可信启动

Checkpoint30新增实际CLI的私有 `1.1` 配置 opt-in，旧 `1.0` 配置仍只读；具体文件、existing-only attach 与默认角色边界见 [TRUSTED_WEB_CONFIG.md](TRUSTED_WEB_CONFIG.md)。下述可信宿主注入 API 保留，HTTP 仍不能提供启动配置。

`create_app(..., control_services=None)` 仍为旧只读应用，旧 1.0 CLI 配置不会自动开启写入。仅可信宿主可以显式传 `{project_id: ControlServices(drafts, approvals)}`。两个服务必须持有同一个已绑定 Store、同一个 app AuthStore，匹配固定项目、模式、实际根目录、Origin 和 Registry owner；不允许每个请求新建未绑定 Store，或用 JSON 指定 root、catalog、身份、凭据、服务或 DB。

`DraftService` 使用独立 operator session guard，不将 operator 升级为 approver；ApprovalService 保留精确 human 确认。Store→Auth 锁序、writer/BEGIN 后重验、紧邻 commit 再验、真实 issued identity/服务 staged request、finally 清理与同事务 rollback 同时保护普通提交和重复请求。旧 whole-state `transact` 不可承载这些 Hybrid 服务事件。绑定仅是可信 Store 实例的服务边界，不是全数据库的 OS ACL；执行隔离仍待实现。

## 接口

所有写请求要求正确 Host、明确同源 Origin、真实 human session cookie、`X-CSRF-Token`、JSON。敏感重复 header 拒绝且不回显输入。Bearer 只能读取已授权项目的 command receipt，不能提交或确认。Viewer 不写入，operator 只提交 DRAFT，approver 才能 prepare/approve/revoke；双角色须显式配置。

| 接口 | 含义 |
|---|---|
| `POST /api/v1/projects/{project_id}/commands` | command1.1 + `Idempotency-Key`；仅 submit_goal、approve、revoke |
| `GET /api/v1/projects/{project_id}/commands/{command_id}` | 有界原回执 DTO，不是当前 authority 或执行状态 |
| `POST /api/v1/projects/{project_id}/goals/{goal_id}/approval-confirmations` | `{ttl_seconds: 1..86400}`；临时明确确认视图，不写业务事件 |

command1.1 是独立 URN `urn:rlflow:spec:command:1.1`，见 `schemas/command_v1_1.schema.json`（包内副本一致）。旧 command1.0 原 bytes/URN 不变；新服务不把旧 approve 的 proposal_hash 自动映射为已明确确认，也不 fallback legacy pause/stop/调度路径。

submit_goal：target 为当前 project，parameters 为 `goal`（proposal1.1）和 `expected_revision`，外层 `expected_version` 为核心全局版本。approve：target 为 goal，parameters 为服务实际返回的 `confirmation`；外层版本须等于确认版本且目标一致。revoke：target 为当前 approval key，parameters 为 goal_id、expected_authority_revision、reason；外层全局版本亦必需。所有 schema 闭合，actor 从实际认证上下文派生。

HTTP command ID 由 human actor/项目/模式/客户端幂等键派生，三个 action 共用核心 UNIQUE event key。不同 action 或不同 payload 复用同键返回 409；同请求重试返回原 accepted version 和原事实，不续期。兼容 optional `control_command_id` 与 `expected_state_version` 只出现在新请求中，旧不可变 request/hash/key 不回填。

## 返回和错误

POST 成功返回 202 与 command DTO：schema_version、command_id、action、status=SUCCEEDED、accepted_state_version、duplicate、result。它只证明命令事实已持久保存；`result.execution_enabled=false` 始终为 false。result.state 是原命令在 `as_of_state_version` 的结果（DRAFT、LEASE_VALIDATION_PENDING、REVOKED），不能当作现在仍有效的批准。原批准 key 的回执在撤销后仍显示原事实，不自动恢复执行。

响应采用 allowlist，不返回 raw fact、receipt.request、registry_witness、保护配置、CSRF/session secret 或数据库路径。prepare 可显示原 proposal、服务端 diff、内容 hash binding、nonce 和明确未验证限制；不包含 Registry 原始内容。当前暂未提供完整 goal/approval 公共列表或 UI。

控制路由错误统一 code/message/retryable/correlation_id/details。真实 CAS 409 返回已授权项目的一致 `details.current_version`；读取前后再检查身份范围，不用整个私有 view 当摘要。完整性/容量损坏返回 sanitized 503，不冒充版本冲突；幂等冲突是 IDEMPOTENCY_CONFLICT。旧默认只读错误行为保留，不借此声称所有历史 API 已统一。

## 有界资源与断连

请求实际 bytes≤256KiB，3 秒读取期限，拒绝重复 JSON key/非有限数及非法闭合字段。读取 receipt/source/blob 的总原始 bytes≤4MiB，结构预算覆盖这一合法 byte 包络；literal-marker 的原存储编码可能约6倍膨胀及重复读取，不能将已合法的 256KiB Registry 降为 50k 节点或事后收窄配置。索引按 command ID 查询，blob 摘要、原核心事件和 authority 原回执摘要均核验。

服务持有单个有限 thread pool，最多 2 个同时 worker，默认最多 4 个实际 pending job（配置1–8）。容量直到实际 concurrent future 终态才释放；客户端取消或超时不表示事务回滚，也不提前释放。关闭时停止新 job 并等待既有有限 worker 回收，不启动第二个 supervisor 或模型/GPU。

## 证据与剩余工作

root r5 原50814 终态：289 passed/1既有 warning/28.73s；独立原19197同289 passed/28.89s。日志 `audit/hybrid-v1/checkpoint-29-control-r5.log` 与 `checkpoint-29-control-high-r1.log`。实际 uvicorn/httpx 使用 disposable fixture、127.0.0.1 随机端口、owned 非 daemon 线程，真实超时后容量429、实际提交与原重试、条件性批准、最后线程/pool 回收均验证。不是 writer 仍阻塞时的下线竞态测试，不是实际用户批准或工程/科研执行。

剩余：完整安装/迁移恢复体验、DRAFT/批准只读公共桥与 Dashboard 明确确认 UI、MCP/skill、STOP/fencing/lease/preflight/runtime、工程科研闭环、M1/B1/NFR06 和长期24h/8h。完整 T09/T16/M0–M5 没有因 HTTP 首切片而完成。

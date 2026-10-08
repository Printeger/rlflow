# Checkpoint 02 — 只读认证/SSE 基础与 guardian 隔离修复

关联任务：T04/T06 基础、T01 既有恢复边界加固；不是 M1 退出报告。父 checkpoint `757129d`，分支 `hybrid-v1`。

本次改动：新增 web_auth/web_api/live_stream/web 模块，外部 owner-only 配置、同源 Cookie 与短期 viewer Bearer、项目 scoped snapshot/keyset objects/SSE；每个 BEGIN 内绑定 project/data_mode。单事件预取、4MiB/32 帧队列、actual ASGI send deadline、heartbeat 无 durable id、resync 后关闭、最多 8 流。临时 command 控制文件移出角色可写 scratch；_supervised 无显式 trusted guard 则拒绝；未知/无效 writer 身份保留恢复文件，不自动清理。

明确不改动：不授予执行/批准权限、不启动 scheduler/model/GPU、不开放写命令/任意 artifact、不新增可访问公网服务、不自动 push。只有显式 trusted prepare 会启用现有 Store 的观测；HTTP 路径不迁移 Store。保留用户未跟踪 `package-lock.json`。

输入/输出：同源 JSON 登录、Hash-only 配置与 token 表；snapshot/page 与已注册 durable legacy.observed；after 与 Last-Event-ID；resync_required `{code,reason}`。缺 scope 的项目不可见；源身份更换或序列失配 fail closed；usage/cost UNKNOWN 不被心跳改变。

测试：正式命令与最终输出见 IMPLEMENTATION_VALIDATION.md、evidence/checkpoint-02-final-pytest.txt。包括真实 SQLite 身份替换、匿名/scope/Cookie/Bearer/CSRF/DNS rebinding 拒绝、真实 socket SSE commit/reconnect、100 条健康积压、实际慢发送、revocation、槽回收、角色伪造控制标记拒绝、恢复写入者完整身份检查及旧功能回归。

故障发现与处理：首轮 366/32；冻结候选出现一次既有 owner-death 临时目录清理 ENOTEMPTY，真实 child 已死但可信 supervisor/guardian 仍写。High 复核同时实证 guard writable 缺陷；不忽略失败、不增加业务终止期限，改控制目录与清理证明，并强化旧测试。r2 368/32 属于中间候选；最后补 identity null/empty/bool/缺字段防御后重新冻结并执行 r3。

资源与性能：查询只读短事务；没有热全历史重放；SSE 队列和预取显式有界。B1/24h/8h 尚未验收，不能从快速测试推导长期 CPU/RSS/延迟合同通过。UNKNOWN 临时 artifact 保留属于安全恢复，后续 T21 必须提供受控保留/磁盘策略。

独立 High 审查：项目读源 TOCTOU、健康积压/预取、角色可写控制文件、清理身份 fail-open 均被复现并关闭。最终当前范围内无阻塞 finding，详见 SECURITY_REVIEW_WEB_FOUNDATION.md；这不替代全系统独立最终审查。

迁移/回滚：旧 authoritative 对象/事件/预算未重写。观测仍显式 opt-in；CLI 原调度方式保留。只读 Web 下线不影响 Store；进程控制隔离修复不应回滚到角色可写 guard。安装包静态界面、完整 Error envelope、遥测/日志、M1–M5、真实供应商闭环均未全部完成。

下一项：T05 bounded trusted startup observer，绑定 request digest/committed release/model release/codex identity/generation/START_ACK，再推进 T07/T08；START_ACK 只证明 CLI wrapper 释放到达，不能当作模型消费/计费证据。

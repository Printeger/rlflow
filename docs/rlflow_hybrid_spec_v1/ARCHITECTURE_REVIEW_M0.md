# M0 只读独立审查记录

2026-10-08，审查会话 `hybrid_architecture_review`，用户指定 GPT-6.1 Sol / High。审查基线 `d25cf02`，本报告不是最终交付审查。

主要发现与处置：

1. 旧 `engine.py` 在持久放行前写 session RUNNING，不能当作实际模型已开始。新增桥保留 source_status，映射为 STARTING，usage 无证据时 UNKNOWN；对应测试已通过。
2. 旧 event.object_version 是全局 state version，不能当新对象版本。新增观察实体 version 单独递增，source_state_version 保留，测试覆盖其他对象变更插入。
3. 事件、旧投影、公共投影、durable outbox 必须同事务。新增 Store hook 在同一 SQLite 事务内更新；验证失败完整回滚；实际进程 commit 前/后退出测试分别得到零条/一条可补发事件。
4. 旧 summaries/view/replay 不能用于 Web 热路径。新增只读 mode=ro / query_only reader，短 read transaction、indexed tuple keyset + LIMIT、增量 counters，未注册 state 不创建目录。
5. bounded snapshot 只含部分对象时，事件必须更新全局 counters。payload 已加入同事务 counters（含归零记录）；前端 reducer 尚未实现。
6. 整个旧 payload/日志不能公开。新增白名单 summary、文本截断和常见凭据/连接串/敏感路径脱敏；原始控制数据保留，尚需 API/detail/export 接入后的全面测试。
7. 协议声明版本匹配不能当完整 capability gate。probe 改为同时匹配精确 version 与 protocol SHA256；执行能力仍独立未验证。

未闭合项：完整 T03 领域实体与 API 读模型、SSE 背压/接缝、Frontend reducer、恢复流程的 epoch 旋转、真实 Codex 执行、各任务最终候选独立审查。新代码的详细独立审查仍在继续。

复核结束：本 checkpoint 两条最后 MUST_FIX（quoted secret 尾部泄露、complete=True 但计数缺失误报 KNOWN）已修复，独立负例回归 9 passed / 9 deselected。observer source_version/outbox/序号校验、归零 counters、0.161.0 工具兼容修复已复核。上述结论只覆盖本 checkpoint，不代表 M1–M5 或最终 Goal 通过。

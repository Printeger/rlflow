# T06 只读服务基础安全复核

2026-10-08；GPT-6.1 Sol High，`/root/m1_security_review`，只读审查；Root 单写。审查未调用模型执行业务任务、未访问生产 state、未启动 GPU。

范围：web_auth.py、web_api.py、live_stream.py、ObservationReader 的每事务 project/data_mode 绑定。静态页尚不存在，XSS/前端凭据与浏览器生命周期未验收。

已修复并独立复现关闭：

1. 先 head 后独立 snapshot/page/events 连接的项目替换 TOCTOU。改为每个读事务 `_checked_meta` 验证 expected project/data_mode；替换后拒绝，未泄漏另一项目 sentinel。
2. 200 条预取可能在队列外驻留过量内存且健康 backlog 被当作慢客户端。改为每次单事件读取并让消费者得到调度机会；独立快 send 100 条全发送，慢 send 20ms 触发 SLOW_CONSUMER，首次 domain 后撤销则 AUTH_EXPIRED；三者连接槽均回收。

核心边界：纯 ASGI middleware 保留实际 socket send timeout；Cookie/Bearer 方法隔离、Origin/Host、CSRF、project scope 未发现权限绕过。协议名称改为 `after` / `resync_required` 与 `{code,reason}`。非阻塞建议也已实现：拒绝孤立 surrogate 的登录字符串，限定 SSE queue/bytes 与正数时间配置。

补充正式测试覆盖 API 源替换、所有读方法身份与模式、100 条历史积压、慢客户端、撤销、socket-facing send stall、流槽回收和真实 loopback HTTP 重连。详见 IMPLEMENTATION_VALIDATION.md 最终测试结果。这里只证明基础切片，不是 M1 或 Goal 的最终审查。

## 冻结回归揭示的既有 command guardian 缺陷

原 owner-death 测试在业务进程已死但可信 writer 仍活跃时立即 rmtree，发生 ENOTEMPTY。独立三次身份观测确认 supervisor、guardian 此时仍能写 done/recovery/receipt。进一步独立真实隔离命令实证 default guard 在 scratch 中，Engineer 能写 lifeguard-done（exit 0），违反可信控制文件不可角色写的边界。

修复不放宽测试：父进程创建外部私有临时 artifact 目录，_supervised 拒绝隐式 TMPDIR guard；额外 read/execute scope 不能包含 artifact；旧死亡断言保留并在原期限内补充两类 writer 的真实身份终止检查。临时目录仅在双方 quiescent 时删除，ready 缺失/身份不明时保留。真实角色伪造控制文件拒绝与 cleanup unknown 保全测试新增。持久化 artifact 不自动删除，完整受控保留/磁盘策略仍待 T21。

最终 High 复核还复现了 owns(null/empty) 返回 false 不能作为 quiescence 证明的问题。现先验证两份完整 Linux 身份形状，缺字段/null/empty/bool PID/无效 boot_id 或 starttime 均拒绝清理。独立四项针对测试通过，当前范围内无剩余阻塞；最终回归以 r3 为准。

# 资源与 worker freshness 来源合同

Checkpoint13 引入独立、latest-only 的真实 Linux 观测来源。它不属于 durable domain event，不推进 observation seq、Store version、任务状态、批准或预算。未启用/尚无样本的只读查询返回 JSON null；GET 不创建表或回填历史。显式 `observation.enable` 创建空槽，core `reconcile` 最多每秒尝试一次采样。

`GET /api/v1/projects/{project_id}/telemetry` 使用既有认证、项目授权和 readonly reader。闭合 Telemetry 1.0 包含 project_id/store_epoch/data_mode、独立 sampler_epoch/sample_seq/sample_id、core observed_at 和读取时 sample_age_seconds。GPU 尚无受验证来源，固定 UNKNOWN/null；不把未观测表示为 0。

## 指标范围

- HOST CPU：两次 `/proc/stat` aggregate counter 的差值；首次样本 UNKNOWN。不重复累计 guest。不是项目 CPU、模型调用计数或 cgroup 配额。
- HOST memory：`MemTotal` 和 `MemAvailable`，单位 bytes，不等同于已分配给该项目的内存。
- STATE_FILESYSTEM disk：状态目录所在文件系统 statvfs total/available bytes；不是项目占用、quota 或 artifact 大小。
- SUPERVISOR_PROCESS：只采完整绑定身份对应的 worker supervisor 累计 CPU 秒和近似 RSS bytes，不声称覆盖模型/工具/后代进程树。Linux RSS 的近似性和 stat counter 语义见 [kernel proc 文档](https://www.kernel.org/doc/html/latest/filesystems/proc.html)。

process 来源使用 anchored proc directory fd，并匹配 pid/pgid/starttime/boot_id、二次读取排除退出/zombie/身份变化。公开接口只给 opaque execution_id，不给 PID、命令、路径或原始身份/hash。每次最多选 32 个 active worker，按既有 projection status/key 索引公平轮转；`workers_truncated=true` 表示本批未覆盖全部 active worker，包括尾页，不能把未采样当作不存在。

## 心跳

worker-heartbeat.json 由真实监督循环进度点最多每两秒原子写入一次；没有独立 timer 线程。写入失败不终止执行，失败后同样限频，临时文件由 atomic_stream 清理。仅 recovery_protocol>=2 且合法 request/context 启用。

core 核验 closed schema、session/generation、request/candidate digest、DB release_binding 的完整 worker 身份、当前存活进程，以及单调时钟和 counter。首次或丢失 witness 时先保存 UNKNOWN baseline，只有实际 counter 与时钟前进才能确认；确认后重复读取不更新时间。未来、回退、旧 generation/boot/身份、符号链接和额外字段均为 UNKNOWN。有效报告 age<=15s 为 FRESH，其后 STALE。读取时将 sample elapsed 保守累加到 worker age，采样停止也不会永远 FRESH；同事务核验本批 session binding，已改变的 generation/identity/status 不沿用旧资源与 freshness。server heartbeat、PID 存在、CLI_RELEASE_ACK 或 FRESH 均不是模型活动、STARTED 或任务成功证据。

## 容错与边界

先在 readonly transaction 选取有界来源，锁外读取 OS/worker，最后使用既有 writer lock 的非阻塞模式及 SQLite timeout=0。project/mode/epoch、slot、witness 和所选 session 字段 CAS；竞争或来源错误丢弃样本。独立 latest slot 不生成业务 audit/outbox。counter witness 按 session 索引持久化，不因32个批次上界丢失；每批最多32个 witness 读/写及32个 GC候选，轮转删除终态/已删除 session，不全扫历史。source descriptor<=64KiB、heartbeat/witness<=4KiB、public body<=64KiB、本批binding<=32；深嵌套 JSON/序列化异常显式隔离，不能从可丢弃旁路中断 core。boot/epoch 变化不展示旧样本，损坏 public slot digest/scope 要求 RESYNC，而不是相信该内容；缺表/孤立witness不由GET或enable静默重置历史。

本切片不是历史曲线、资源强制或 M1 gate：SSE 的独立可丢弃 telemetry 帧、UI 样本版本/陈旧处理及资源显示仍需接入；B1、长期 soak 和完整 M0–M5 仍待验收。部署为保护状态目录的既有 local-only 服务，不公开发布。

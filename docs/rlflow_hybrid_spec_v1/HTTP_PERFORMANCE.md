# 有限归档规模 HTTP 测量（不是完整 B1）

Checkpoint23，2026-10-09 Asia/Shanghai。生产代码保持 `7be43b8`；启动前 HEAD `49f709b`。新增的仅是验收驱动与测试，不改 API、SSE 默认参数或业务调度。开发 Goal 没有交给 rlflow 调度。

## 范围与方法

只读备份 checkpoint16 的真实 100,000 条 Store 事件档案，严格核对初始安全 marker/唯一 usage 对象；轮转 clone epoch，再新增 10,000 条明确标记为归档、未执行、DONE/all-false 的 fixture 任务。启动一个父-owned loopback API 子进程，仅 ObservationReader/create_app，无 daemon/model。身份完整核对，PDEATHSIG=SIGKILL；token 经私有 pipe 传递，不进入 argv、日志或证据。真实认证 snapshot 验证完成后，两个独立 HTTP 客户端订阅生产默认 SSE，各收到第一条领域事件后断开，并用 Last-Event-ID 重新连接（故意同时传无效 query cursor 证明 header 优先）。这不是额外强制 snapshot→subscribe seam 竞态；该竞态由既有功能测试单独覆盖。

唯一串行 writer 按绝对时刻计划执行：30 秒×10/s 的 300 笔，再 2 秒×50/s 的 100 笔。另两个独立客户端各每 0.5 秒交替请求 snapshot 与 task page（limit=50），共 128 次。计划、发行时刻、调用返回、响应状态/字节数、完整收帧时刻均保存；不以写入完成后的相对 sleep 掩盖迟发。每笔计划必须返回非 duplicate 的连续核心版本，每笔都有对应公共事件（允许一笔多个事件），两客户端逐 envelope/digest 与最终 outbox 相等；最终源 DB/WAL、全部 task 对象与 session 不变量核验。

提交调用开始→HTTP 完整收帧，是包含 Store 调用的上界，不是真实 commit 时间，更不是页面可见时间。调用返回→收帧为有符号差，可能为负；本轮没有负值。最近秩 p95 使用全部已验证样本。失败样本/超时不能从分母排除，失败会输出 raw 而不输出成功 summary。`asyncio.to_thread` 取消不等于事务回滚；API 在异步 finally 先回收，但 executor 可能仍等待已开始的写入，因此不是硬 CLI deadline。

## 实际终态

原父工具 session `79247` terminal exit0，不重启。API PID/PGID `1198582`、starttime `142548815`、boot_id `fa257cc3-1204-4e6f-88a5-a8a2ea7743aa`；cleanup 前身份存活核验，计划 TERM 后 returncode=-15、reaped、owns=false，API log 空。Clone epoch `store_a5b7f94a1ddd41959f73af63d5d03c47`。

| 阶段 | 写入（计划/实际） | 发行 lag p95/max ms | Store 调用 p95 ms | 提交开始→收帧 p95/max ms |
|---|---:|---:|---:|---:|
| 10/s，30s | 300/300 | 2.003373 / 2.562331 | 9.516131 | 246.724021 / 259.688641 |
| 50/s，2s | 100/100 | 1.763244 / 2.158507 | 8.749710 | 246.099217 / 259.587643 |

两客户端各 400 个完整领域事件、各一次重连，800 个帧时间样本，总 p95=246.724021ms。128/128 查询完成（64 snapshot、64 page），snapshot p95=8.144433ms，page p95=10.167431ms。无 receiver error/缺失/重复；core 最终 100401，public 最终 100451，task 10000 精确不变、session 0，原来源哈希不变。

**full_B1_pass=false；不宣称 NFR-01、NFR-02 全档案或 M1 gate 通过。** 没有浏览器 DOM/桌面移动双端、3 项目/活跃 Goal/3 受控会话、4vCPU/8GiB 限额、daemon+API 合计 RSS/CPU、维护并发/WAL 峰值、24h fixture/8h UI soak。源码完整仓库轮询仍是独立 NFR-06 缺口。下一步按依赖推进这些验收及 T09–T25；不是完整 Goal 交付。

## 命令、原始证据和审查

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_acceptance_http_v1.py tests/test_acceptance_idle_v1.py tests/test_web_local.py
.venv/bin/python -u -m tests.acceptance_http_v1 audit/hybrid-v1/checkpoint-16-history-r1/state/runtime/research.db audit/hybrid-v1/checkpoint-23-http-r1
```

输出目录必须不存在，不覆盖/复用旧负载。实际启动将 stdout/stderr 保存到同名 `.log`，源码冻结且没有并行测试。Root 21passed/10.21s，High 独立 21passed/10.65s；compileall/diff 通过。High 初审三项 MUST_FIX（逐写入 public 覆盖、SSE 原始错误丢失、提前 API 死亡误判）均修复，相关负例实际执行。r5 故障注入首次被 append-only trigger 拒绝（1failed/18passed），修正为仅对 disposable clone 明确移除 delete trigger 后注入，不改生产防护；此前 ROS plugin 环境失败/错误测试文件名和早期 head 字段失败亦保留。

便携完整原始两行 JSON：`evidence/checkpoint-23-http.jsonl`（1,331,937 bytes，SHA256 `030e1c15bb3f17d81bc6bc01241b0f2ff90949433f51ebdbc458d1a64b5e6951`），与 `audit/hybrid-v1/checkpoint-23-http-r1.log` 字节相同。Clone DB 留存 audit，SHA256 `092914159d481c3ab47b7c22ab12a37c8fc502ed1502ca5aa053ed59dced1808`；源 DB SHA256 `bb148ad0b22bfbe27632915e3985b1a643bcf3fb1836f6fa84e045ad3756db4c`，空 WAL。代码与测试日志 hash 见 `evidence/checkpoint-23-final-tests.txt`。High 终态独立逐项重算全部计划/请求/双消费者、outbox/core source/hash、epoch/任务/session/source、身份/cleanup和上述最近秩统计，float精确吻合，无剩余MUST_FIX；未重跑测试或负载。

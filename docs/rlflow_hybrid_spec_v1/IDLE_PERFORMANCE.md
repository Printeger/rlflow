# 组合历史/归档任务的有限 daemon idle 探针

Checkpoint18，实测CPU未达目标，完整B1与M1 gate仍未通过。

## 方法与安全范围

`tests/acceptance_idle_v1.py` 在默认非优化Python下只读检查checkpoint16保留的真实100k事件DB：fixture标记、全部initial marker及唯一usage/fixed必须精确匹配。拒绝任何额外对象，不由fixture标签授予调度权限。SQLite一致读事务backup到独占新目录，原DB与非空WAL前后SHA一致；新建空WAL/SHM不是逻辑历史变更。只在克隆中rotate_epoch并真实事务增加10k DONE且completion全false的归档任务，不导入伪造事件，不证明工程完成。

真实`rlflow.engine.daemon`在受控子进程内运行。独立wrapper先绑定父PID/PGID/starttime/boot，重置SIGTERM disposition，设置Linux PDEATHSIG并在前后核对父身份；父线程必须为main thread。单独pipe证明death guard准备好，随后核对真实daemon-code身份再warmup。正常结束或父侧异常时只terminate/kill/reap本次Popen直接子进程，不杀其他进程或宽泛进程组；父骤死负例包含确定性的pre-prctl与post-ready边界。没有第二个长期Supervisor，没有模型/GPU/活跃Goal/API调用。

5s warmup后按真实monotonic区间测300s，约1s读取实际进程CPU ticks及RSS，CPU百分比为`100 * CPU秒差 / 实际wall秒差`，不除以宿主核数。每样本检查真实子身份、STOP及daemon诊断文件；任何诊断/早退/STOP均拒绝结果，源码/测试/配置冻结以保留实际代码变更退出门。STOP子采样瞬变不保证被捕获。RSS为采样峰值，不是全生命周期HWM或daemon+API总量；活着不等于每个循环成功，采样器进展仅辅助证据。

## 当前执行

```sh
.venv/bin/python -m tests.acceptance_idle_v1 \
  audit/hybrid-v1/checkpoint-16-history-r1/state/runtime/research.db \
  audit/hybrid-v1/checkpoint-18-idle-r1 \
  --tasks 10000 --min-events 100000 --seconds 300 --warmup 5
```

原日志`audit/hybrid-v1/checkpoint-18-idle-r1.log`，父工具session90403；daemon身份PID1146995/PGID1146995/starttime142137578/boot fa257cc3-1204-4e6f-88a5-a8a2ea7743aa。core100001/public100051，source_events100000/tasks10000/session0预期需终态再核验。来源DB SHA `bb148ad0b22bfbe27632915e3985b1a643bcf3fb1836f6fa84e045ad3756db4c`。禁止因工具等待超时另起一次相同长测。

已终态父exit0、daemon正常被SIGTERM回收exit-15且owns=false；实际区间300.0008994229138s，单核CPU **1.7733280167604935%（未达<1%）**，301条采样、采样RSS峰39862272bytes（38.015625MiB）。实际core/event100001、public cursor保持100051、tasks10000/sessions0，source/business不变、daemon.log空。最终telemetry seq297/monotonic1421680.581122869。portable原始JSONL与log字节相同，SHA `3f3fb5df53dafb35b0c3b845fc98d808eb473c910c50afba0dc34c5e463891c7`，见evidence/checkpoint-18-idle.jsonl。克隆DB终态SHA `6481c5f03d08ef80651d5f2a2d5e3bda0ada6b0362b50b04e24d37fcc28259e9`；来源DB仍为上述SHA。

保真限制：driver的first基线没有单独序列化，循环首条晚74.001微秒，因此不能从raw rows独立精确重建报告基线。直接由301个raw rows独立重算区间300.00082542188466s、CPU差5.32s、单核CPU1.7733284541862842%，同样未达标；不以反推报告percent制造原始基线。下一版本driver应保存显式first；本次不重跑未变化版本以覆盖原证据。

一次测量中只读辅助查询（无改动）：read_monotonic1421479.56324383，telemetry sample_seq101/monotonic1421478.624584909、epoch与manifest一致。这只能说明该时点已有采样进展，不代替全区间CPU或循环证明。

## 回归与独立审查

root最终短回归13passed/2.54s，覆盖严格source拒绝、有限真实daemon、父骤死、BrokenPipe父存活时child回收、两个SIGKILL边界及已有历史/任务probe优化拒绝。原始日志`audit/hybrid-v1/checkpoint-18-unit-r4.log`。High只读启动安全复核无剩余MUST_FIX；发现的首个print在finally外与固定sleep边界保真问题均修复，有真实进程负例。长测终态后独立测试与原始CPU重算待补齐。生产源码未改变，不声称重跑586全量或浏览器回归。

High终态独立13passed/2.53s（audit/hybrid-v1/checkpoint-18-high-r1.log），原始CPU/RSS、所有task DONE/allfalse、core/public/session/epoch、来源fingerprint、两个daemon identity witness、空diagnostic/child退出与portable SHA核对一致，无剩余安全MUST_FIX。确认首baseline缺失限制，不反推或重跑；不能将CPU未达标记作通过。

## 验收边界

此档案仅把100k历史与10k归档任务组合，测真实daemon无工作CPU；宿主非限定4vCPU/8GiB，无3项目、活跃Goal/受控3会话、10/s+50/s事件及desktop/mobile客户端。即使daemon小于1%，也不能宣布整个控制层/API NFR-06、完整B1、M1、8h/24h soak或M2–M5通过。结果未达目标时保留原始证据并诊断，不放宽阈值或删除失败。

NFR-06还明确要求“无全仓库/全历史轮询”；当前daemon逐秒递归watch_stamp控制文件，本项尚未满足，CPU小于阈值亦只能证明CPU子指标。静态候选还包括每轮三次Store.view导致归档task键枚举、无QUEUED前仍哈希daemon_generation。后续优化必须保留一致读snapshot、授权/STOP及实际派发前后的code generation门；代码监视不能以root mtime、固定降频或仅已知文件缓存代替安全检查。事件失效监视需覆盖创建/删除/移动/属性/原子替换、启动竞态、overflow与watch失效，并fail closed；尚未实现或测得贡献。

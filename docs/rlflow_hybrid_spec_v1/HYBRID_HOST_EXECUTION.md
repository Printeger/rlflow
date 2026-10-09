# 有限共享池执行 SDK（Checkpoint 59）

本切片把已有原工程/CPU Unit 接到同一个原 HostPoolOwner，实际处理两个独立项目，不增加 scheduler、长期 Supervisor、HTTP 写接口或持久授权域。双项目正例、四实际边界、必要103项共享回归与输入快照定向均通过，独立增量审查无剩余确证 MUST；证据见 evidence/checkpoint-59-final-tests.txt。此切片不是完整 Goal。

## 交付行为与范围

`HostExecutionService(pool)` 在该 actual Pool 强引用登记唯一实例。`bind_unit(unit)` 只接受已由原 Runtime canonical registry 登记的 exact EngineeringExecutionUnit/CpuTrialExecutionUnit，且属于同一实际 Pool；不创建 Unit、grant、lease、Controller 或批准，不从 ID/JSON/磁盘恢复能力。最多保留 32 个原绑定。

`run(lease, token, **body)` 路由到原 Unit。`run_many(requests)` 接收 1–3 个不同原 Unit 的 `(original_lease, original_token, body)`，先捕获最多四项的请求快照（四项即拒），body 先复制后闭合验证，再验证整个有限批次，最后由最多三个有限线程调用原 Unit。每个项目保留自己的批准、Store、Controller、预算、初始 CAS 和最后执行门；返回每个原范围的实际结果或错误。普通单范围错误不重试写、不取消其他范围、不冒称全 Goal 完成；调用方中断先 latch 本批原 Unit，再清理及等待原 futures，不把 executor shutdown 当作进程 STOP。

```python
host = HostExecutionService(original_shared_pool)
host.bind_unit(original_cpu_unit)
host.bind_unit(original_engineering_unit)
results = host.run_many([
    (original_cpu_unit.lease, original_cpu_token,
     {'idempotency_key': 'cpu_once', 'expected_state_version': cpu_store.version()}),
    (original_engineering_unit.lease, original_engineering_token,
     {'idempotency_key': 'engineering_once', 'expected_state_version': engineering_store.version()}),
])
```

此例只路由此前已批准、注册的 actual 原 cap，不是完整安装/创建授权流程。已接受请求的历史重复结果仍是 ASOF；它不是当前执行、资源空闲、批准仍有效或新的写权限。

`cancel(lease)` 先以纯内存 PID/strong registry 检查原范围并永久 latch，随后原 Unit 只清该 lease 的 Source/原 FD。`cancel_all()` 捕获调用时的不可变有限绑定快照，对所有仍有效原 Unit **全部先 latch**，再逐项清理；一个失活或 UNKNOWN 范围不阻止其他 live 范围先 latch。之后新绑定的 Unit 不属于此次快照，不把此 SDK 说成整主机/全 Goal STOP。UNKNOWN/no PID/部分 FD 关闭不能制造终态、退款或 FREE；Host 从不全局关闭 Runtime/Pool owner。

## 实际验收

- 两个独立项目各有原批准、Registry、Store、Controller、WorkingPlan，在同一实际 Pool 执行。CPU 原 sealed 384 样本/counts 96,101,104，实验实际消费 1；工程原 inode 一次 pwrite、实际 after/AST21机器待评审。两个 nonce/来源 hash 原证据分开，原进程退出、FD 全关、Pool occupied=0。
- 一项目最后 G 前取消，在另一项目开始前确认其原 FD、grant、账本未变；另一项目随后实际完成。批量取消在 Pool 锁被持有时先 latch 全部两个 Unit，再清理。
- 原第三 claim 使 occupied=3，第四实际 claim 拒绝；复制、外来 Pool、fork、重复/非法批次拒绝，不靠线程数冒充池排他。
- 一项目 Popen 返回未知保留该范围 occupied=1、experiment consumed=0/unknown_exposure=1；另一项目实际完成，批量取消仍不虚假 FREE。私有测试结束时原 parent-FD safety retirement 也不退款。
- 原候选图变动在下一 writer/G 前拒绝；同 start 借用原图及相同总 deadline，异常退出清空上下文。两项目冷 Reader 不调用 Popen/pwrite/Pool.check，跨项目 key 无数据，仍 current execution UNKNOWN/resource NOT_OBSERVED。

开发 positive 的 G 前失败、无 worker 定位和修复全部保留在 `audit/hybrid-v1/checkpoint-59-*`。同失败两次后改变诊断，未延长固定 3 秒看门狗。无 worker profile 确认一次 HANDOFF 有 6 次 Pool.check/18 次完整 state/36 次原来源验证；只读 check 空事务在退出处核一次完整全局原状态，仍在原 claim、physical/nativeFD、slot、最后 clock、COMMIT 成功后才返回。写入与 audit 路径不改变。Pool 单事务 memo 只复用 exact 原字节的 schema/派生展开，原 whole-event 每次读回，≤3项/≤1MiB，退出清除。原物料图在同一次 start 借用，不缓存当前授权，不刷新原总期限，各 writer/gate 完整检查仍保留。

## 剩余缺口与下一项

这是固定 CPU 数值实验与固定 add 补丁的有限 SDK，不是通用 Codex/native 执行、独立产品 Reviewer、任意合同条件满足或科研 Goal 完成。池只排他本安装受管 fixture，不证明旧 UNBOUND/同 UID 非合作进程已迁移，也不证明 strict OS/任意进程树 STOP、全主机 GPU 配额或真实 invoice。现有冷 API/页面的原 ASOF 合同不改变，没有新增 UI/Chrome/远程发布声明。

本切片已完成边界、必要回归、最终输入身份/静态检查和独立差量审查；原103共享回归通过后只改 Host/新test 两文件修输入竞态，其余290输入原bytes未变，最后2项非执行定向通过，不重跑未变套件。测试日志和版本清单已归档；临时 pytest 工程/原 worker 文件不作为长期发行产物，已有输入/代码、实际日志和检查身份仅作 STANDARD 开发验证，不冒充正式科研封存/长期运行证据。继续原计划尚缺的真正独立评审/通用执行与安装、长期验收；不缩减 M0–M5，不新增 paid model/GPU/生产迁移权限。

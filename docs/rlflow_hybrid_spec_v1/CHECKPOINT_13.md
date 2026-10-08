# Checkpoint13：真实 OS 资源与 worker freshness 后端

2026-10-08，继承192a2f2。T05/T06新增实际后端来源和认证只读API；未声称完整M1、资源UI或M0–M5交付。

## 实现

Telemetry 1.0闭合合同与独立SQLite latest slot、core reconcile非阻塞采样、HOST CPU/memory、STATE_FILESYSTEM disk、完整身份绑定的SUPERVISOR_PROCESS累计CPU/RSS、真实监督循环每两秒限频worker heartbeat已实现。GPU保持UNKNOWN/null。Web GET项目scope/readonly/no migration，无PID/路径/argv/原始context。详细接口和边界见RESOURCE_TELEMETRY.md。

采样不推进Store version/observation seq、不产生durable event/audit、不改变任务/authority/预算；busy writer或SQLite竞争立即丢样。只读快照选择≤32active sessions，最多3个indexed status range、每个≤33，公平keyset轮转；尾批同样声明partial。source descriptor≤64KiB、heartbeat/witness≤4KiB、public body≤64KiB，锁外OS读取、提交前project/mode/epoch/slot/session/witness CAS。

独立High四项问题已针对性修复：

- latest读取时保守累加sample elapsed至heartbeat age并降级STALE，采样停止不能永久FRESH。
- worker counter/clock witness改为独立indexed per-session表，不因32个批次轮转丢高水位；≤32读/写及≤32候选GC，首次/丢witness先UNKNOWN baseline，实际counter+clock前进才confirm。
- JSON解析/序列化的RecursionError/OverflowError显式隔离，不从旁路中断core。真实≤4KiB深嵌套无效JSON负例与防御性异常注入应区分：本Python 3.12 parser能解析1500层，该负例因closed shape拒绝，不能声称已复现该尺寸RecursionError攻击。
- 同事务只读核对本批sample bindings与当前session；采样后generation/identity/status变化，旧worker metrics/freshness变UNKNOWN，不能把同sid旧gen fresh用于新gen。

## 验证过程

初始pytest console入口缺少repo sys.path，3个collection error，改用`.venv/bin/python -m pytest`，不修改宿主包。r2定向14failed/32passed：新fixture缺核心session必填字段、release_binding不能null，以及越权项目既有404隐私行为；修fixture而非合同。r3 46passed/3.36s。首轮冻结全回归550passed/32skipped/1warning/204.87s，是独立复核修复前结果，不能代替最终冻结。

High修复后r4 49passed/3.77s。新增实际worker心跳写失败测试r5 97passed/1failed：fixture candidate父目录覆盖control，被既有安全边界正确拒绝；将candidate与role control分离后r6 **98passed/1warning/28.74s**。严格证明心跳失败后真实worker仍进入bounded release timeout、NOT_STARTED且无CLI身份，未启动模型。

最终源码冻结全回归 **556passed/32skipped/1warning/208.02s**；High独立 **24passed/1warning/3.25s**，当前后端来源/freshness/只读API范围无新增MUST_FIX。根独立重复防御性异常注入，核对read_json调用2次、host调用1次及domain replay/version/cursor不变，日志checkpoint-13-exception-injection.log。证据见evidence/checkpoint-13-final-tests.txt。既有sandbox Chrome+Node **15passed/0skipped/6.50s**，仅证明已有Dashboard仍无回归，不冒充尚未接入的资源UI。compileall、pip check与git diff --check通过。源文件和日志哈希同见evidence。

## 下一项与限制

下一项为latest-only独立telemetry SSE（无durable id、不可挤占关键domain队列）、客户端sample版本/重复/迟到/陈旧处理、真实资源和worker freshness UI，再执行M1 gate/B1周期snapshot等性能验证。采样只覆盖supervisor，不是完整进程树资源强制，不提供历史资源曲线或vendor活动证据；M2–M5、工程/实验闭环、安装恢复和长期soak继续待实现/验收。没有外部阻塞，完整Goal保持active；未启动开发Goal的rlflow scheduler、付费服务、GPU、外部发布或push。

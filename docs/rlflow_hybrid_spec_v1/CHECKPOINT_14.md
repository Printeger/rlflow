# Checkpoint14：独立 telemetry SSE 与真实资源面板

2026-10-08，继承9e00dcb。T05–T08资源消费纵向切片；不是完整M1或M0–M5交付。

## 交付与边界

独立optional采样reader task/单latest slot、critical domain/control FIFO优先、共享queued byte cap、无durable id、sample去重、auth再校验、optional错误只drop已实现。TelemetryView纯模块与Dashboard HOST CPU/memory、STATE_FILESYSTEM disk、GPU UNKNOWN、sample age/FRESH/STALE/PARTIAL和节点supervisor CPU/RSS/worker loop标签已接入，来源与模型活动不同域，无伪造计数/动画/资源历史曲线。

独立High发现两类真实竞态并修复：

1. domain新generation先送达、较新的旧generation sample后送达，单纯新sample_seq不能解除UNKNOWN。原采样meta source_state_version持久绑定，客户端snapshot/domain全局O(1)版本barrier控制worker展示；旧槽缺因果字段null/双UNKNOWN，读取不修改原槽。HOST仍as-of。
2. optional帧在critical FIFO后等候可超过15s，不能在接收时重新续鲜。query前monotonic基准、选送时保守queue/query增龄并重算STALE、post-frame cap校验；增龄/序列化异常隔离只drop，不终止durable domain。

取消信号不吞；最多32worker/16退休sampler epoch，不增加无界execution map。重复样本/旧seq/退休epoch不刷新时间；项目、身份、snapshot清空资源；server heartbeat不证明模型运行或worker loop活动。完整合同见RESOURCE_TELEMETRY.md。

## 验证

定向r1 39passed/4.82s；新因果与排队修复后r2 58passed/5.02s，真实ASGI交错r3 59passed/5.01s。r4 62passed/1failed、独立high r1 32passed/1failed：新增test插入把精确21s age断言移到未定义parsed的错误作用域；产品负例此前断言已经通过，修测试断言位置、不删除或放宽。冻结r5 **63passed/1warning/5.78s**。

独立High冻结复验 Python **33passed/1warning/3.16s**、JS **5passed/0failed**，两项MUST_FIX均关闭。额外临时Store验证先真实supervisor绑定达到FRESH/KNOWN，再移除原槽causal字段重算digest，readonly降为null/双UNKNOWN且SELECT全槽完全不变；未改repo源或测试。

实际sandbox Chrome+全部Node **20passed/0skipped/9.19s**：初始UNKNOWN、真实HOST内存/磁盘、首CPU baseline UNKNOWN、下一OS delta%、telemetry不推进cursor、fixture无worker identity仍UNKNOWN；原实际DB/SSE/日志/手机/离线/身份隔离继续通过。桌面和390px手机截图已查看，无横向溢出。Browser HOST来源是真实OS，但业务仍明确FIXTURE，未冒充vendor模型或实际科研闭环；worker有效心跳另由backend OS/private binding测试验证。

最终冻结全回归 **562passed/32skipped/1warning/209.07s**，原外部依赖skip与Starlette warning不增加。命令/源码/日志SHA见evidence/checkpoint-14-final-tests.txt。compileall、pip check、ESM语法、diff检查通过。本地Sites流程，没有注册/同步/公开发布；owned Chrome/loopback fixture均已结束。

## 后续

下一项M1 gate与B1历史规模性能：100k领域events/10k任务、周期snapshot全量maintenance、首次历史/重连与资源效率证据；之后推进M2–M5，不以资源UI切片缩减完整Goal。仍缺完整Hybrid authority/runtime/STOP控制、工程与实验闭环、安装恢复、24h/8h soak及最终审查，无新增外部阻塞，不调用付费模型/GPU或push。

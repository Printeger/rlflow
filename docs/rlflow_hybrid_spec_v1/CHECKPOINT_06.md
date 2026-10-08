# Checkpoint06：CORE_STATUS公共日志后端

2026-10-08，继承 `d05e640`，T05/T06/T07后续实际存储/API切片，不是完整日志/M1/Goal完成。

`public_logs.py`在observation同一事务写入append-only日志summary/body/ref索引；每条绑定项目/epoch/mode/eventID/seq/template版本/opaque对象版本。正文只有固定“状态观测”模板，known状态之外正规化UNKNOWN，不复制description/reason/source任意文本、命令、异常、模型输出。CORE_STATUS仅证明已提交public状态，不推断状态转换或CLI/工具/模型实际运行。raw logs PRIVATE_ONLY，tool metadata UNAVAILABLE。

新增闭合LogSummary/LogBody/LogPage与project-scoped GET `/logs`、`/logs/{log_id}`。列表不查询LogBody.text，limit1–200、单kind/id与severity索引过滤；游标含固定high-water/epoch/filter digest，不是SSE游标。普通列表核验compact committed summary witness与source digest绑定，不宣称逐条重读所有历史source bytes；过滤命中逐个校验公开envelope的hash/project/epoch/seq/ID与ref membership/severity，峰值仅一个有界event而非200份最大event。正文按需核验body摘要和完整source重构，不接收filename/path、不读raw文件。

显式enable/prepare为新观察者启用日志；已存在且三日志表都缺失的旧观察者从当前seq开启，公开coverage_after_seq，历史不伪造回填。旧未升级观察者仍可提交原事件、原读接口可用，日志请求明确UNSUPPORTED。三表部分缺失时enable和所有日志读取都RESYNC拒绝，不自动重建空索引；Web GET不迁移。新的INSERT ref guard要求正文refs成员与severity匹配，update/delete guard保留。

## 审查与验证

最终冻结全回归 **430 passed / 32 skipped / 1 warning / 143.61s**，原日志 `audit/hybrid-v1/checkpoint-06-final-r3-pytest.log`；现有Chrome/reducer/geometry回归 **11 passed/0 skipped/4.50s**，编译/diff检查通过。版本化输出与SHA256见[evidence/checkpoint-06-final-tests.txt](evidence/checkpoint-06-final-tests.txt)。Sites技能只影响本地浏览器回归流程，没有发布。

最终目标子集80 passed/1 warning/5.31s，日志 `audit/hybrid-v1/checkpoint-06-targeted-r5-final.log`。独立High日志27 passed，临时库分别缺meta/logs/refs时prepare、plain/filtered page、body拒绝且schema/coverage/source witness完全不变。当前本范围无剩余MUST_FIX。

关闭三项finding：任意INSERT ref能伪匹配并改变severity；MAX(seq)掩盖中间缺项；prepare将仅缺ref表静默重建为空但保留coverage。增加源membership/severity核验+insert guard、LEFTJOIN缺源/缺log拒绝、非过滤keyset局部连续/floor检查、三表初始化/读取闭合与负例。索引过滤EXPLAIN确认range-index，无全表scan/temp sort；301对象split覆盖全部且正文/refs有界。其他负例覆盖事务回滚/幂等、高水位后新增、filter变换、epoch/project/mode、破损body/summary/source、非法参数、原模型秘密/HTML不入模板、API匿名/跨项目与lazy正文。

保留过程：新测试最初把未支持的experiments顶级collection当作实际存储，RuntimeState正确拒绝；改为实际usage relation fixture，未放宽schema。两次未冻结全回归在审查发现partial-schema修复期间主动SIGINT停止，分别219passed/22skipped/64.29s和137passed/8skipped/46.86s，日志 `checkpoint-06-final-pytest.log` / `checkpoint-06-final-r2-pytest.log`；它们不是通过证据。修复/独立复验结束后才执行r3冻结最终回归。

## 未完成边界

本轮没有日志前端、工具动作metadata、私有raw日志安全公开策略、资源telemetry或真实模型接入；后续继续UI日志筛选/lazy正文与T05真实工具事实绑定、资源样本，然后M1 gate。所有M2–M5、B1/24h/8hsoak/安装迁移/最终审查仍保留。没有模型、GPU、生产数据、公开监听或push。

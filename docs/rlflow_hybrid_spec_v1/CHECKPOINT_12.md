# Checkpoint12：绑定工具返回的公共纵向切片

2026-10-08，继承ed99ecb。T05–T07新增实际代码；不是完整M1或M0–M5交付。

## 来源与公共合同

public_tools专用转换读取原Store事务中的closed private receipt，不将tool_receipts加入普通SECTIONS、不从Web读raw文件。仅COLLECTED/VERIFIED+非空fact/witness/digest可进入候选；核验REGISTER recordhash、semantic_digest、source/key/context/intent/fact及validation_digest一致，有限数字与返回语义，任何缺失/不一致不公开。只发布opaque tool/execution/task ID、cpu_exec、RETURNED/TIMED_OUT/SETUP_FAILED、exit/timed_out/报告wall_seconds、固定infrastructure_error、core observed_at和PARTIAL。没有命令、argv、cwd、stdout/stderr、路径、原始context/hash、vendor活动推断。RETURNED不是成功，SETUP_FAILED不证明命令启动；不改变session/task/authority/预算。

独立High发现checkpoint11 task字段不在旧validation digest内，现新collector在原CAS事务保存validation_version=2，digest覆盖fact/witness/context/task_id。旧v1即使有optional task字段，公开关联也为null；缺v2绑定不追认。PublicObject顶层闭合字段union+两个严格oneOf分支，不允许通用工具row绕过新完整合同；状态与UTC时间规则对Python/JS一致。

## 覆盖、事务与日志

enable/prepare显式创建public_tool_meta，记录coverage seq/source_version，LIVE_ONLY/PARTIAL；旧COLLECTED不隐式回填，Web GET不升级、未启用返回null。起点描述core公开采集，不伪造工具发生时间。未知/未验证/不支持/隔离/无journal历史不能由公开数量解释为零调用。epoch rotation保留历史投影与原公开起点，日志retention floor单独生效。

High两项覆盖finding关闭：不能把feature起点clamp到恢复floor后仍保留旧返回总数；存在table缺singleton或无table却已有tool projection/counter时，enable必须RESYNC_REQUIRED，不重置起点伪造新窗口。初始化索引EXISTS有界，无全历史搜索。

private cursor/receipt、tool public projection/counter、durable events与logs沿用Store同事务；工具模板失败全部rollback再重试不重复。CORE_STATUS v1按原解释保留，旧counted_status不扩为工具状态；普通变化与工具返回拆为同core source event的不同output_index观察事件，每seq一条日志。TOOL_METADATA v1独立模板，BOUND_RETURN/PARTIAL，refs与filtered-page共用固定公开关联函数，支持task/execution筛选；raw始终PRIVATE_ONLY。工具row的version=1为不可变返回，不是执行生命周期状态机。

## Dashboard 与实际验证

objects?kind=tool_return、snapshot覆盖字段、SSE新kind、closed reducer、独立log-view模板、工具对象详情、来源标签和覆盖说明已同步实现。没有新增写HTTP、模型调用、公开部署。总缓存/分页/虚拟窗口原上界保留；不添加模型/成功脉冲。Sites local-only验证，sandbox Chrome+loopback owned fixture；浏览器与服务均结束，未注册/同步/发布。

首轮后端74passed/26.07s。目标r3 165passed/1failed/59.74s：旧private collector回滚测试写死1个public event，改为严格2事件/相同core source ID/恰好1个tool fact，以验证独立模板而非放宽遗漏。r4目标166passed/1warning/93.28s。错误入口test_local_web.py不存在，r2无tests，保留日志后核对真实test_web_local.py执行。

首轮全量捕获PublicObject顶层additionalProperties声明缺失；协议诊断17passed/1failed/0.06s。每个oneOf原已闭合，但未满足原顶层合同不变量；修产品声明，不改测试。已知失败全量在确认进程1074382后SIGINT结束，保留336passed/24skipped/1failed/159.46s，不列为成功。修复后冻结protocol+public_tools **43passed/25.72s**。最终冻结全回归 **532passed/32skipped/1warning/200.39s**，原external dispatcher18/H1 14 skip与Starlette warning未增加。compileall/pip check/diff通过，命令/源码及日志SHA见evidence/checkpoint-12-final-tests.txt。

High独立当前promotion/oldv1/task/coverage/live-only/epoch/旧log负例 **23passed/31deselected/23.93s**；三类MUST_FIX已关闭，只读、根唯一writer。

Node单元14passed/0skipped，实际Chrome+全部Node **15passed/0skipped/6.46s**。工具browsercase为明确序列化trusted-core Fixture，只证明实际DB/API/SSE/UI路由与筛选，不证明CPU或vendor执行；test_public_tools另用真实model-free受控CPU→collector→公共查询验证来源链。截图desktop/log/mobile已查看，390px无横向溢出。Browser验证RETURNED/exit1仍不改变execution STARTING、lazy工具body/执行筛选、隐私、原日志分页/乱序/离线/身份隔离。

## 剩余工作与回滚

仍无资源telemetry/worker freshness、供应商真实模型与usage闭环、disk raw定位、安全journal repair/restore、B1周期全量snapshot维护改造、M1完整gate或长期soak。旧UI不认识新工具kind须与后端一起升级；回滚至旧observer前应先停服务/写入并采用相容快照，不把未知新public事件交给旧reducer。完整安装/迁移方案仍属T23，不以本切片替代。接下来资源真实来源与M1验收，再推进M2–M5，完整Goal保持活跃。

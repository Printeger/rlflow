# Checkpoint 61：原 CPU Unit 的人工执行与 STOP

状态：FINAL（开发切片），基线 `8d1d2f5`；不代表完整 Goal 验收。原全量已终态，无 live 测试。最终证据见 [checkpoint-61-final-tests.txt](evidence/checkpoint-61-final-tests.txt)。下方开发过程记录保留实际失败，旧 LIVE/待修记录不代表当前状态。

必要全量 r4 原99109终b64541 exit0：2288 passed / 32既有外部H1 skipped / 3 warnings，3693.68s。真实终态后仅 control/stop/test 三文件修闭合输入和逻辑-map边界；r5 原7041终5f32aa exit0：2 passed / 1 warning，19.34s。其余300输入字节未变，未重复前端36通过、Chrome1通过或全量；最终候选采用全量加窄修定向的组合证据，不称r5新全量。High对两处增量已静态关闭、无剩余确证MUST。309路径最终输入清单SHA `27e7584b67cd2c9c324294fbcfc009a4ca4f492e995787dcf1a4b356989cbb2b` 全匹配；编译、依赖、JS语法和diff检查exit0。

本切片交付行为：受批准的原 CPU Unit 通过认证 Dashboard 明确执行一次，实际计算固定 384 点、封存原来源、STOP/reap/FD 关闭、Pool FREE，再产生机器验收 pending-independent-review。独立 STOP 在 Run 请求在途、Pool/Store 等待时仍先锁存本范围取消，不接受任意命令、路径、lease/grant 或 cold owner 重建。

验收条件：实际一次 Popen/G/实验消费；原 Run body/key 重试只读接收事实；STOP 原 body/key 可继续本范围安全清理；真实末效应与机器写入重新检查人工权限；无权限/异源/冲突 key 不锁存；合法 STOP 在容量满额时仍锁存但未持久接受不回 202；fork 在继承锁之前拒绝；STOP 原事件、投影、审计、快照与恢复闭合；实际 Chrome Run、丢回复手动重试、独立 STOP、原始证据和 logout 清除；中央 Store/schema 改动后必要全量回归。

RUN 使用原 HANDOFF 事件里的 command，不重复造队列事实。STOP 使用独立不可变 `HYBRID_CPU_UNIT_STOP_ACCEPTED`：人类意图不等于生命周期 STOP/FREE，可以晚于原安全清理；禁止回填旧生命周期或为等人类意图阻挡清理。canonical STOP body 无 CAS；实际接受时的内部 CAS 记入事实、不是请求 hash。RUN/STOP 共享原 actor/project/epoch/client-key 命名空间，不允许跨 action 复用 key。

人工认证只批准新效应。STOP 一旦持久接受，原 cap 安全清理不依赖会话或 Controller 续期；接受失败仍保留物理取消 latch，不虚报 202/FREE。Dashboard 保留两个独立意图，STOP 不被在途 Run 或只读刷新禁用，重试必须显式且保持原 body/key。as-of Task、机器结论、接收事实和资源采样是不同来源；均不推出当前 running/Goal 完成/独立 Review 通过。

开发证据：首轮 `checkpoint-61-positive-r1.log` 实际 HTTP 384/机器结论/一次派发/重复请求/清理后 STOP 均过，最后审计因新校验错误要求逻辑 state 含物理空 marker 而失败（21.72s）；修复逻辑-map 校验，原事件完整 proof 仍检查物理 marker。冻结 r2 下唯一新模块 `checkpoint-61-unit-r1.log` 已真实终态：8pass/1测试夹具失败/1既有warning/111.59s；失败是隔离损坏夹具尝试UPDATE原append-only事件被触发器拒绝，不是损坏来源识别已通过。r3精确修夹具暂移/恢复原trigger，定向 `checkpoint-61-persistence-r1.log` 1pass/1warning/11.12s，已验证rollback无202/取消latch保留、原key续清、generic duplicate禁写、坏source审计/维护拒绝与恢复后维护成功。

High入口/source/snapshot六项MUST及两项UI（native clearTimeout绑定、已接受Run后旧GET重开新Run）均修；坏FACT schema在原source边界转Conflict→503、输入ID仍400，r4定向source-error原36350终4fd8faexit0 1pass8.86s。前端4modules原414b34exit0 36pass115.911ms；实际Chrome原31618终98f2bdexit0 1pass23.257367s，Run实际完成后的HTTP回复被扣留时仍能STOP，随后丢回复→原body/key手动重试不新增Popen，384原证据/count96,101,104/非Reviewer/Goalfalse、STOP原key手动续清、关闭owner只读/禁止新控制、logout清除均通过。后台原子进程已spawn但未G的HTTP STOP证明取r2新增对应case，不把Chrome已完成后的STOP说成杀活进程。唯一必要全量原99109 LIVE，最终结果尚待。所有r1–r4冻结与失败日志保留，不并行测试、不编辑活跃输入。

## 私有启动接线与 API

开发期独立High增量审查已关闭六项入口/source/snapshot、两项UI和来源错误分类残余；最终静态核对Control SHA `efc6db94…cd37ba07`，没有剩余确证MUST。该审查只读、不运行测试，不能替代产品或科研独立Reviewer；全量回归仍须取得真实终态。

全量运行期间只读发现的输入错误分类边界已在真实终态后窄修：canonical快照后、`body.get`前用exactdict门，None/bool/number/string/list全部400，既有auth输入case定向通过；无新worker派发。未受影响全量不重复，原99109冻结未改变。

逻辑-map空ID窄修已完成：物理空marker仅在原事件/投影中，逻辑snapshot逐成员验证且按len(rows)核对来源覆盖，额外空ID被拒绝。现有source-schema case定向通过，High确认兼容原Store replay/快照，不扩功能。

可信启动代码先取得原批准/Controller/Pool/Runtime/lease，构造 `CpuAssessmentService`、`CpuTrialExecutionUnit`，绑定原 `HostExecutionService`，再构造 `CpuUnitControlService(host, original_lease, same_approval_auth, origin=origin)`。仅允许尚未HANDOFF原Unit强能力，单例不可重绑。传 `create_app(..., cpu_unit_services={project_id: control})` 显式开启，默认不开启；请求不能构造上述对象。原CPU evidence读取仍可另注入既有 `cpu_assessment_readers`。测试接线见 `tests/test_hybrid_cpu_unit_control.py`，实际 loopback/Chrome 夹具见 `web_checks/cpu_unit_server.py`，不作为通用生产启动器或新安装验收。

`GET /api/v1/projects/{project_id}/cpu-unit` 是原事件验证的as-of Task加原owner可用hint和有限SDK机器status，不写状态/续lease/推断当前资源。`GET .../cpu-unit/commands/{command_id}` 核验原接收事件，原parent owner关闭后仍可读，fork在Auth/executor前拒绝。

`POST .../cpu-unit/commands` 只接受human operator会话、相同Origin、有效`X-CSRF-Token`和`Idempotency-Key`。Run闭合body为 `{action: START_FIXED_CPU, task_id, expected_state_version}`；紧急STOP为 `{action: CANCEL_FIXED_CPU_TRIAL, task_id}`（不能夹带CAS/命令/path）。只有持久接收原事实后202；Run/STOP回执都 `execution_status=UNKNOWN`，STOP phase是`STOP_INTENT_ACCEPTED`而非FREE。Run/GET用有限Start池，STOP另有两worker池；容量拒绝不会撤销合法STOP物理latch。对失联结果只手动原body/key请求，Run绝不再派发；STOP可以继续原安全收尾。输入400/权限401或403/隔离项目404/幂等或版本409/不可验证来源与结果503，错误不暴露私有源、令牌或路径。

剩余缺口：原工程 Unit 的同类认证入口在下一切片；native 模型执行、产品/科学独立 Reviewer、严格 kernel 资源、任意执行树、可信计费、安装/B1/长期验收仍保留。没有新增 paid/GPU/生产授权，也没有需要用户现在决定的合同问题。

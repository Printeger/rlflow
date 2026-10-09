# Checkpoint 62：原工程 Unit 认证执行及独立 STOP

状态：FINAL（开发切片）；基线61 `84a5341`。完整M0–M5合同不变，无live测试。证据见 [checkpoint-62-final-tests.txt](evidence/checkpoint-62-final-tests.txt)。

交付行为：原已批准固定 add 工程 Unit → 认证人工一次执行 → 原只读 worker产出 → STOP/reap/FDclose/Pool FREE → 原 inode 单次 pwrite → 原实际 AFTER与21项机器检查 → 待独立评审。不是任意工程命令、native模型或通用Supervisor。

验收条件：实际一次Popen/G/单次pwrite；原请求丢回执后相同body/key仅读HANDOFF；独立STOP先权限/目标/同key冲突再本范围latch，不等待Run/GET/旧CAS；新pwrite与新机器COMMIT最后核当前人工权限与纯取消门；已进入write的原cap只读reconcile允许接受STOP后权限过期，不重写/不自动accept；工程STOP持久保护、原source、回放、全量来源覆盖、同ROtxn snapshot维护闭合；实际Chrome与受影响回归。

新增API默认关闭，可信bootstrap显式传 engineering_unit_services；exact工程Unit/Reader/action/schema/domain和原Store/Auth/Host/lease绑定，HTTP不构造新能力。START_FIXED_ENGINEERING带task_id和expected_state_version；CANCEL_FIXED_ENGINEERING仅task_id，内部接受CAS不是请求hash。共享原actor/project/epoch/clientkey命名空间，不迁移旧CPU事实。两路POST有独立有限STOP执行池。

私有复用原有限控制与UI；工程独立STOP域hybrid_engineering_unit_stops / HYBRID_ENGINEERING_UNIT_STOP_ACCEPTED，不冒充CPU实验。机器通过不是独立Reviewer或Goal完成；Task仅as-of、当前资源NOT_OBSERVED。

首个真实HTTP正例原99958终ee4971 exit0：1pass/1warning37.64s，实际onePopen/onepwrite/AST21、原key重试/STOP/audit/snapshot/recovery均通过；r1输入完整匹配。随后仅收紧lastAuth后再纯取消检查，增加对应边界，不在live测试中编辑，不重开正例。

最后权限检查使用独立issued-memory门，不再在Controller末sample后调用Runtime/SQL/procfs；末Auth后纯取消门为最后检查。工程INTENT/pwrite owned COMMIT末回调也使用相同门。新机器接受先BEGIN再借Auth，全部来源/AST/图检查后紧前核权限与取消；audit-only reconcile不借新效应授权。

API：GET `/api/v1/projects/{project_id}/engineering-unit`；GET同路径`/commands/{command_id}`；POST同路径`/commands`。POST仅同Origin、人类operator会话、CSRF和幂等key；RUN接收为原HANDOFF，STOP接收为独立不可变人类意图，二者都execution_status UNKNOWN，不能推断FREE。服务默认不安装；可信启动先绑定原Host/EngineeringExecutionUnit，再构造EngineeringUnitControlService传入create_app的engineering_unit_services。接口不能新造grant/lease或重建冷owner，原parent owner关闭后GET历史仍可读。

5边界92.53s已证明末G/pwrite/机器COMMIT过期拒新效应、Auth门期间取消拒pwrite和丢写返回后STOP接受再过期的原cap只读捕获。Node28通过；首Chrome失败定位既有Date.parse毫秒精度误拒1µs因果差，修严格微秒排序（同一时刻与反序仍拒），定向4通过，新工程Chrome1通过31.889864s，受影响CPU Chrome1通过22.898169s。必要11旧module＋工程正例维护闭包206pass/2warning948.81s，退出0；不重跑无关61全库。316最终输入SHA498c63f486317db959186eaa07c257e4312a97a02b2ee9ee2ba60f371b20e911匹配；独立High末门与精度差量无剩余确证MUST，不替代产品独立Reviewer。

下一63：同一认证应用、两个独立项目在原共享Pool真实执行与范围STOP隔离/用量来源整合。剩余缺口：native模型执行、产品与科学独立Reviewer、完整条件/Goal、严格OS/任意树、可信invoice、新安装B1/24hfixture8hUI原验收。无新增用户决定阻塞；paid/GPU/生产/USERlock不动。

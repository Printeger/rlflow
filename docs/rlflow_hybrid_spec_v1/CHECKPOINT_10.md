# Checkpoint10：core私有工具collector与恢复ledger

2026-10-08，继承010d0fe。T05核心采集实际代码，不是公开工具metadata、M1或Goal完成。

新增闭合ToolLedger schema以及RuntimeState可选tool_sources/tool_receipts/tool_scan。沿用Store projection+append-only events及replay/recover，不建立第二个写入服务或shadow DB。source的journal cursor/checkpoint、pending_after/revision、receipt语义digest/完成与验证状态在一个transact_objects中CAS提交，公共桥只记录CORE_STATUS core commit；私有集合不进observation allowlist，Web不读取journal/原始命令文件，工具body仍UNAVAILABLE。

`collect`锚定root/roles/sid，NOFOLLOW/NONBLOCK读取request/intent/result/fact，逐个有界对象；request对照DB frozen session/release/candidate/resources，非null REGISTER witness再核验完整startup proof及exact release/model-release/ACK hashes。intent对照实际request派生role/candidate/scratch/permissions/memory，command ID固定digest目录映射；result command/argv/cwd/checkpoint必须与intent来源相符。不要求当前session仍RUNNING、进程仍存活或stage仍授权，事后撤权不抹除历史；null witness永久不追认release。VERIFIED只表示该绑定证据成立，不证明vendor/model调用、执行启动或进程树已停止。

completion与verification独立：没有result继续PENDING，有返回才COLLECTED，绑定不足仍UNVERIFIED。result有而raw fact缺失时从同一结果确定性恢复固定core fact，不执行命令、不修改raw源。每source使用projection_status索引范围keyset、公平pending_after轮转；默认新REGISTER32+pending32，峰值不持有整批raw正文。全局scan默认8 source、持久round，终态仍pending可继续采；完成并已追平的终态source DRAINED。source revision/global round防止循环位置复用旧幂等key。重复路径额外核验receipt完整值，不仅信Store._existing类型/objectID。

Store热view排除三个私有集合，避免ObjectMap一次加载全部receipt keys；显式get/keyset访问、完整replay/audit/recover保留全部ledger。legacy transact不能借热view修改私有集合，也不会删除未加载的ledger；CLI storage-audit改为比较完整replay。engine accept_result和reconcile接入collector及公平drain，不改session/task/stage/approval/预算/dispatch authority。

## 审查与修复

设计High发现热view全key展开风险，实施前已排除。实现High关闭两项MUST_FIX：非法return数字触发IsolationError从控制循环逃逸，现只将该特定观察验证异常转受控源隔离；producer Unicode字符上界与reader byte cap不一致，现intent16MiB/result6MiB，对齐request≤4MiB UTF8转ASCII最坏3倍+command及有限metadata。容量超限UNSUPPORTED/SOURCE_CAPACITY，不标corruption、不推进本批cursor、不删旧receipt。disk raw尚无安全解析明确UNSUPPORTED；链接/FIFO/坏源隔离QUARANTINED。DB/outbox事务失败不冒充source坏损，整体rollback后可重试。

独立High当前collector24passed/23.64s；最终Unicode/容量三负例 **3passed/24deselected/2.51s**，两项finding关闭。较早独立组合67passed/1deselected。全程只读、根唯一写入；子集不是全量验收。

## 实际测试与失败记录

最终target **205passed/59.70s**：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_tool_collector.py tests/test_tool_journal.py tests/test_tool_return_facts.py tests/test_command_checkpoints.py tests/test_engine.py tests/test_store_policy.py tests/test_hybrid_observation.py tests/test_public_logs.py
.venv/bin/python -m compileall -q rlflow tests/test_tool_collector.py
.venv/bin/python -m pip check
git diff --check
```

目标日志checkpoint-10-targeted-final.log；27新增collector cases含实际model-free CPU返回→私有ledger、一次性/并发、outbox异常cursor/receipt/public日志同回滚、重启/recover/audit/CLI、null登记不追认、permissions/memory/cwd/argv/checkpoint、symlink/raw语义错误隔离、缺result公平轮转与缺fact恢复、多source轮转round、终态/撤权历史、Unicode合法producer及容量明确unsupported。序列化stub仅验证byte协议，不用于证明CPU实际执行；真实短CPU集成与它分开。

finding全部关闭且源码冻结后，全量 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -rs`：**505passed/32skipped/1warning/172.21s**，原日志checkpoint-10-full-pytest.log。跳过仍为原外部dispatcher18/H1 14，warning仍为Starlette安装版anyio alias deprecated，没有新增skip。输出与源码SHA256见evidence/checkpoint-10-final-tests.txt；compileall/pip check/diff通过。

初始collector13passed/12.61s，engine/storage target109passed/39.47s；追加r3 collector24passed/23.61s、r4 Unicode26passed/25.16s。r2 **20passed/1failed/1error/22.34s** 保留：fixture用了真实RuntimeState不接受的SUCCEEDED，改为实际ACCEPTED并增加stage撤权，未放宽schema；另外运行期间编辑测试文件触发release freeze指纹冲突，隔离器正确拒绝，后续冻结源码再跑。两次target入口引用不存在test_store.py/test_storage_v3.py无tests执行，已核对真实test_store_policy.py后执行；不把空运行列为通过。

## 未完成边界

尚无公开工具projection/log builder/schema/API/UI条目、disk raw定位、partial journal显式修复/restore inode迁移、严格逐工具STOP/authority marker或资源telemetry。private采集不能替代这些门槛。正常分页有界，但Store._commit每1000版本仍全量replay snapshot，是已存在maintenance例外，不能声称整个调用含该路径严格有界；T04/B1需后续流式/性能验收。旧legacy/cache无journal不隐式回填，不解释为零历史。

下一项将已验证core fact通过闭合公共projection/log模板接入API/UI，再补资源、M1 gate、M2–M5及长期验收。没有模型/GPU/训练/公开监听/生产数据/push；static未改，不声称本轮浏览器重跑。

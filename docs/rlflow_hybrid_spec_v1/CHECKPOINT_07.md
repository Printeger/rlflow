# Checkpoint07：公共日志只读 UI

2026-10-08，继承292d68d。T07/T08增量切片；不是完整日志、M1或Goal完成。

沿用CORE_STATUS已提交投影，新增severity及task/execution/experiment公开ID关联筛选、50条固定high-water keyset页、独立虚拟窗口、Enter/点击按需正文。日志cursor不推进业务SSE cursor；新增业务提交只提示“可能不匹配筛选”，不自动换页/抢阅读位置。公开coverage_after_seq并说明不含更早历史；空结果不解释为没有历史事件。工具metadata未接入、raw logs PRIVATE_ONLY保持可见。

新log-view纯模块检查闭合summary/page/body、scope/epoch/high-water、降序与覆盖边界、正文/refs上限和标记；refs必须真实string opaque ID。文本DOM不使用HTML、浏览器storage或raw文件。独立list/detail serial与project generation阻止迟到页和乱序正文；身份/项目/epoch变化清缓存和隐藏详情的标题/正文/refs/计数。同项目snapshot刷新失败保留已验证页并显示OFFLINE，成功新epoch清页。

## 验证与复核

最终命令：

```bash
node --test web_checks/reducer.test.mjs web_checks/virtual-list.test.mjs web_checks/log-view.test.mjs web_checks/browser.test.mjs
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_public_logs.py tests/test_web_api.py tests/test_web_local.py
node --check rlflow/static/app.mjs
node --check rlflow/static/log-view.mjs
.venv/bin/python -m py_compile web_checks/fixture_server.py
git diff --check
```

最终Chrome/Node **13 passed/0 skipped/5853.648307ms**，Python **39 passed/1 warning/5.21s**；编译/diff通过。原日志checkpoint-07-browser-final-r2.log、checkpoint-07-web-regression.log，版本化摘要/hash见evidence/checkpoint-07-final-tests.txt。后端没有变更，checkpoint06的430/32为此前冻结基线，不宣称本轮全量重跑。Sites技能影响本地QA与截图检查，没有注册/同步/发布服务。

实际sandbox Chrome+loopback临时fixture验证：正文列表初读请求0、固定high-water换页不改SSE位置、两列表DOM各有界≤16、ERROR与真实task关联过滤、experiment无结果不伪造、lazy正文固定模板、body乱序不替换新详情、logout后旧list不复活、跨身份隐藏字符串清空、503 snapshot刷新保留同项目logID再恢复LIVE。保留原离线追平/去重/阅读锚点/键盘/XSS/native POST等负例。桌面日志面板与390px手机完整截图已目视检查，无横向溢出；截图在忽略的web_checks/artifacts，不是生产运行证据。

独立High只读复核发现并关闭两项：隐藏共享dialog仍残留旧标题/正文/refs/计数；ref数组能被正则隐式转为string。VM载入实际app，在内存中交付跨重置迟到list/body证明不能恢复DOM；纯validator负例通过。最后同项目刷新保留路径再次独立检查，无剩余MUST_FIX。

失败记录保留：最初browser用全局.event-row过滤断言，新增日志行后旧事件过滤无法使全局行数为0；改为分别限定#events与#logs，保留各自bounded断言。r3日志13项通过后追加snapshot503测试，checkpoint-07-browser-final.log **12 passed/1 failed/7773.70ms**：恢复snapshot不回填历史event，因此手机可见event-row等待失败。不是删除断言：snapshot恢复后通过stdin提交新usage观测，等待实际SSE行，再执行相同几何检查。最终r2全通过；不将过程失败算作成功。

## 后续与安全边界

仅fixture、无模型/训练/生产数据/公开监听/push。还需实际工具metadata、资源telemetry、完整error合同与历史/真实来源E2E、性能/长期soak、M1 gate以及M2–M5全部任务。CORE_STATUS固定模板不是工具动作或模型执行证明，不公开模型原始日志/思维过程。

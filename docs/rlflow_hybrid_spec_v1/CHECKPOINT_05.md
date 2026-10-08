# Checkpoint 05：事件虚拟窗口

2026-10-08，继承 `522d4f2`。继续 T07/T08，不是完整 M1 验收。

新增 `static/virtual-list.mjs`：固定64px行、可见窗口加4行overscan，不修改domain/counters/cursor。最近200条摘要只渲染viewport窗口，340px窗口约14行；滚动/resize按需34ms调度，无空转rAF。阅读锚点为事件ID+行内偏移，新事件不跳位，新增N提示、方向键/Home/End/Enter详情可用。身份清除时也清内部items，迟到scroll/resize不会复活旧主体数据。摘要文本安全且截断，完整值可通过accessible label/公共详情读取。100k测试只覆盖几何函数，不是B1后端性能证明。

## 验证

`node --test web_checks/virtual-list.test.mjs web_checks/reducer.test.mjs web_checks/browser.test.mjs`：**11 passed / 0 skipped / 3915.316119ms**，日志 `audit/hybrid-v1/checkpoint-05-browser-r2-final.log`。覆盖100k几何、旧reducer、真实Fixture SSE/离线/身份隔离、209任务总数、DOM窗口≤16、阅读中新事件位置变化<1px、新N提示、End第200条/Enter详情/Home返回、筛选恢复、390px实际可见行。

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_web_api.py tests/test_web_local.py`：**11 passed / 1 warning / 7.95s**，日志 `audit/hybrid-v1/checkpoint-05-web-regression.log`。本轮不改Python/backend，checkpoint04的402/32是该后端版本依据，不虚称重新跑全量。app/virtual-list `node --check`、`git diff --check`通过。

sandbox Chrome截图人工复核：手机初次截图先于ResizeObserver布局刷新，新增真实row与viewport相交等待后实际截图可见完整虚拟行；没有删除布局断言或隐藏问题。Sites技能仍为local-only预览/QA，未注册/发布。High只读安全复核确认内部items身份清除、textContent与有限几何没有明显安全边界问题。

SHA256:

```text
d475bfb5b4ba87939b89287e3aee5ec027c209f67f9a5a4845570b5edcda7785  rlflow/static/app.mjs
8729f72f027207befc2d0fe9bc3a5617d41b99f7fb77f15aece27583eb07a2bd  rlflow/static/virtual-list.mjs
7d8dd16e27c96158765f8b31f15f0261e2d768f595b22104c21731b81ef914ac  rlflow/static/style.css
e588b984faa0dd89bdfffcb74ad268ad7948f34b804c9b2abbd9052fe45b61ce  rlflow/static/index.html
477903490bd436168df40eb79b99f6cf95958831d81ddbb1fa343448f78385be  web_checks/virtual-list.test.mjs
0487e3b35abdd4f22aeab373e293d1446b9e9a0508f265e25fc078b0de5fb26c  web_checks/browser.test.mjs
```

仍缺T05公共日志/资源、首次历史/完整筛选/error合同、真实运行器到浏览器验收、全部动效gate/长期soak。下一项日志安全源与lazy访问High复核中，不能直接tail含reasoning/MCP args/raw outputs的events.jsonl到浏览器。完整M1–M5目标保留。

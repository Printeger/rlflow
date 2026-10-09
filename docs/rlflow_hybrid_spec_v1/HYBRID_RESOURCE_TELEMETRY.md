# Checkpoint 60 · 原固定执行单元资源观测

依赖59的实际共享Host、原CPU/工程Unit与Source能力；补T05/T07/T14观测接线，不改变PRD、任务依赖或验收阈值。FINAL：必要Python回归63pass、Node15pass、实际Chrome1pass，High时钟回退复活MUST修复后窄退休2pass，无剩余确证MUST；详细版本绑定与保留失败见evidence/checkpoint-60-final-tests.txt。59实际提交5b1a305；本60证据不等于完整Goal验收。

## 交付行为与验收

私有SDK `FixedUnitTelemetry(original_host, original_lease)` 强绑定一个原Unit和原项目，每Unit一个observer。原Host并不自动调度采样，也不恢复冷owner。显式 `sample()` 在非阻塞Pool→Runtime→Source锁序下，复用实际Linux HOST CPU/memory/STATE_FILESYSTEM来源，并只从原Runtime Attempt→原Source→原Popen身份采固定进程CPU/RSS。读取源原FD/物理身份并核PID/pgid/starttime/boot；不扫进程目录，不调用Popen.poll，不从历史PID重建。

`create_app(..., fixed_unit_telemetry={project_id: original_observer})` 是受保护启动注入，不是JSON配置、HTTP注册或执行许可。原project/root/mode/epoch必须匹配。认证GET `/api/v1/projects/{project_id}/telemetry` 和原SSE读取同一个有界、detached、latest-only内存slot，无采样、Pool SQL、collect、迁移、预算结算或运行副作用。认证在读取前后、SSE发送边界复核。未注入项目沿用既有telemetry；已注入项目失联不回退到旧DB样本。

新增兼容的 `FIXED_WORKER_PROCESS` scope，旧 `SUPERVISOR_PROCESS` 保留。worker heartbeat、GPU均UNKNOWN；实际进程采样不表示业务ACK、模型活动、整树资源、硬限额或计费。Dashboard原资源区显示真实HOST数值和固定worker采样范围。固定worker对任何本项目新domain版本建立保守因果屏障，而不只观察legacy execution对象变化。

验收：实际原CPU子进程采到正RSS、真实HOST CPU delta；STOP/reap/原Source FD关闭后缓存worker数值UNKNOWN；关闭原owner后HOST亦UNKNOWN；busy采样立即drop、复制observer/cross-project/epoch与撤销拒绝；读缓存不写业务状态/调用执行接口。真实Chrome验证原HOST样本经SSE进入资源面板、显式新sample更新、关闭owner变UNKNOWN、另一项目不受影响、刷新/切项目/退出清理。浏览器fixture不启动worker，不声称浏览器看到正在计算的CPU。

## 年龄、撤销与证据边界

每实际OS sample保留原UTC、开始采样monotonic与source version。15秒后客户端与服务端均清除过期HOST/process数值；heartbeat不续鲜。进程退出的最新认知仅来自原owner的已知returncode/FD状态；未被owner观察到的意外死亡只能由下一显式采样或有限年龄处理，不把as-of样本当实时alive证明。

原slot在独立短内存锁下保留单调年龄高水位与退休级别，已超时或倒退的时钟不能使旧slot复活；只有新的实际OS采样发布才能重置。复制observer/fork读不获得能力；旧原owner关闭仍可只读UNKNOWN，不能把冷owner变原owner。

sample_seq使用4n表示实际采样，+1表示原进程指标撤回，+2表示整个owner样本撤回。这是确定性失效通知，保留原observed_at/source version/年龄，**不是再次OS采样或续鲜**；SSE无durable id，不改业务cursor。排队样本在发送前再读原内存状态，避免关闭后的旧KNOWN继续排出。CPU首样本没有delta时UNKNOWN，不填零。

原SDK STOP仍先纯内存latch，再做原scope清理，telemetry读不等待Pool/Runtime/Source锁。采样会做有限只读OS/SQLite IO，不宣称内核硬时间上界。单observer一个worker，≤64KiB DTO，无PID、路径、nonce、lease、token或私有原始源。

## 剩余缺口

没有后台长期Supervisor、自动资源调度、通用native执行、产品独立Reviewer、invoice来源、cgroup委派、全主机/任意树STOP、迁移、生产安装或长期验收。现管理池只约束原固定应用参与者。原M0–M5/B1/24h fixture/8h UI等需求不因该观测切片完成而关闭；不调用付费模型/GPU，不改变系统配置或生产状态。

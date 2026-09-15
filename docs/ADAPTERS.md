# 项目适配边界

通用部分为目标/工作包、任务依赖、角色执行、证据、预算、恢复、审批和发布。项目接入需要提供独立候选仓库、冻结契约、允许模块、测试程序和资源限制，不需要把业务实现塞入调度器。

`rlflow/experiments.py` 是现有实验控制服务，仍与 reviewed dispatcher 的接口耦合；`rlflow/h1.py` 是 H1 专用控制桥接，验证配置、授权、精确输入、启动命令及原始资源观测。保留这两个文件是为完整展示控制面接口。它们不是训练算法，也不是已通用化的插件系统。

本副本不包含 `training_workloads/`、产品环境、live backend、模型网络、reward、训练配置和冻结 runtime。dispatcher 指向独立目录中不存在的 `adapters/unconfigured/local_dispatch.py`，不会回落到原项目。实验提交缺少精确受审适配器时失败；CPU 角色工作不需要 H1。

未来接其他项目需在本副本里明确实现和审核适配接线，重新验证 submit/status/reconcile/cancel/collect、资源结算和崩溃边界。仅修改路径不能获得真实运行权限，不能把 fake/CPU 测试当作 GPU 授权。

依赖外部 dispatcher 或 H1 的测试明确 skip；其原始测试意图保留，方便未来接入后运行。本次没有复制这些依赖来凑齐通过数，也不读取原项目文件完成副本测试。

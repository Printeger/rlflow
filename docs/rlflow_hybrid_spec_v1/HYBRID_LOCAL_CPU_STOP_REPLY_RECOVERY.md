# Checkpoint 92：原 STOP wire 回执的同 owner 恢复

交付行为：原 manager 已完整解码 StopUnit 的 job 回执、但返回上层时抛 Exception，仍可从同原对象保留的 receipt 继续核验原 JobRemoved(done)、同 Invocation 终态、空进程、keeper kernel terminal、transport reap 及全部 FD 关闭，随后原预算结算及 Pool FREE。StopUnit 只发一次；重复 cleanup 不重复计额。fatal BaseException 不吞。

receipt 在原 wire decode 成功后、return/unref 前保留，绑定 creator、unique manager destination、unit、keeper Invocation、原 socket/source SHA、唯一 STOP intent 和 decoded job。不能从 JobRemoved 单独推断 receipt，不能从 JSON/冷进程恢复这份控制能力。Source 整体退役全 preflight 成功后才同时撤销 manager/receipt 登记；别名失败全保留。

验收：
- 首版实际 caller-return loss 与真正 wire decode loss：2 passed / 35.10s。
- High 找出 job 尚未封入 canonical context 的 MUST，已修；最终实际 caller-return loss 及 source 退休 alias 回归通过（最终合并运行 14 passed / 1 failed / 31.12s，失败为新增纯测试夹具缺 snapshot）。
- 该夹具修正后仅受影响单项 1 passed / 0.03s；不重跑已过实机。其余最终纯绑定负例含单改 job 均过；新 stop 负例拒绝、零 RPC、无 terminal。纯合成测试不充当真实 STOP/FREE。
- 真正 decode 丢失仍 UNKNOWN/占槽、不重发；该实机分支在 job binding 差量前已通过，差量不改变无 receipt 分支，证据保留。
- High 窄复审确认 job MUST 关闭，无剩余确证 MUST。

证据在 evidence/checkpoint-92-stop-reply/。JSON 是真实运行输出的格式归一化副本，不是完整账本 byte seal；pre-fix 与 final 不混称同一版本。runs.txt 保留命令、退出和测试夹具失败。

剩余缺口：父 SIGKILL 后仅 91 原签名 task evidence 可恢复，原 manager receipt 不存盘、不授 cold STOP/FREE。完整冷收敛还需前 G 绑定原 service 顶层范围、transport 身份、禁止额外 producer 的 manager 策略及可信完整终态来源；GC/not-found/PID death 或 task_empty 不够。预算未知不能退款，Pool 占槽不能仅凭日志释放，跨账本故障顺序须可恢复。

下一交付按该冷协议补实际行为与验收，不增加固定演示。真实模型 Engineer→独立产品 Reviewer→条件证据→接续、strict disk quota、完整长期恢复/长跑仍未验收。集中模型/GPU合同未答，不调用；instinctRL 只读/HOLD，未达长跑准入，另窗 Goal prompt 尚不作为已准入交付。82 历史全量 4 failed/2532 passed/32 skipped 保留。本片不是全库、安装、科研自治或长跑完成。

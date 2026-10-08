# Checkpoint20：一致读的闭合控制早门

T04/T05性能切片；非CPU/NFR06/B1/M1完成声明。

Store.control_view仅同BEGIN读version/paused/enabled/autonomous_tasks，先核验并解blob再严格类型校验；缺必填或错型/缺blob fail closed，optional自主列表缺失为[]。不枚举集合、不读取历史，自有连接成功/失败均closing。它是早门提示，不授予派发权限；没有新增enabled gate。dispatch_one仅替换outer原view，paused/autonomous/allow_paused语义、STOP/ACTIVE、pending位置、pointer前后夹层、inner full view、generation和全部正式授权/预算/candidate/CAS不变。

目标r2 89passed/40.39s；随后补5类错型/缺blob与失败关闭，新模块r3 10passed/0.83s。独立High指定五文件94passed/69.91s、只读复核无剩余MUST_FIX。冻结全量609passed/32既有外部依赖skipped/1既有Starlette warning/251.96s；compileall/pip/diff通过，原session63583与High91575终态exit0，不重跑。见evidence/checkpoint-20-final-tests.txt。

实际测试包含10k id超64KiB immutable blob解码、两个SQLite连接在version/marker查询间真实提交PAUSE而早门仍旧一致snapshot、后续读见新状态、reader成功/失败后closed、缺paused拒绝、paused早门不调用完整view。没有实际模型/GPU/活跃开发Goal/API/UI变化；未重新跑browser或300s CPU，不用绿测试替代性能证据。checkpoint18实测1.773%失败保持。

下一移除无候选inner view但暂保留现位置generation，避免扩大代码漂移窗口；事件式watch不能单靠inotify替换安全门。Linux官方man页明确mmap/远程修改/挂载覆盖不可靠；下一设计须保留真正执行边界的完整验证，不能默认忽略或放宽NFR06。参考[Linux inotify文档](https://man7.org/linux/man-pages/man7/inotify.7.html)。完整M1 gate/B1/长期与M2–M5/工程科研闭环/安装未完成；Goal active，无新的用户权限阻塞。

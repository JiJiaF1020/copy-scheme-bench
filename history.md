# History

蓝绿协作轮次档案。只追加，不修改。每轮至少记录：派单 commit、执行环境、原始数据出处、判读结论与置信度。

## 轮次记录格式

```
## §R<n> <标题>（<日期>）

**派单**（commit <id>）：<一句话任务 + 判读通过标准>
**交付**（commit <id>）：<一句话结果 + 数据出处>
**判读**（蓝区）：<阳性/阴性/无效 + 依据 + 下一步>
```

## §R6e cards8/bs32 五 copy 档直接对比 + 旧脚本对账（2026-10-15）

**派单**（commit = 本轮 commit，hash 以 `git log --oneline -1` 为准）：
用户指定坐标 cards8/bs32/copy{100,200,300,500,2048}，同机同轮直接对比：
G0 旧脚本迷你组（5 case，dry-run 已核）+ A 新 bench npu 锚（15）+
B cpu±绑定 pretouch（30）+ C hybrid cf0.1±绑定 pretouch（30），共 80 case
（蓝区 dry-run 已核）。判读预案：主对比表 / bs32 逐档复证 S2（×1.05+
极差 ≤10%）/ 新旧等价 5 点 ≤5% / 绑定=修复复核。§R6d 未交付即取消
（用户优先 bs32 对比；新旧对账缩为本轮 G0，bs24 对账不做）。通过标准
R6e-G1..G5 见 pingpong.md §R6e。
**交付**（commit 7fb1be8，绿区，21 原地执行；numactl missing ⇒ fallback 回放）：R6e-G1 自检 47 tests OK；R6e-G2 三 manifest 全 passed + 75 case 全 passed + correctness 全 true + window==16 + pretouch==true + cpu_frac==0.1 + numa 成对（r6e_verify bad=0）；R6e-G3 拓扑 4 节点、NN=4 循环映射、numa_balancing=1；R6e-G5 fallback 日志行 + config.numa_bind 一致。执行环境：141.61.33.21（21 无 numactl → sched_setaffinity fallback）。关键实测（折叠带宽 GB/s，绑定/不绑定按 _numa 拆分）：主对比表 copy100/200/300/500/2048——G0 旧 170.62/166.95/165.60/164.16/163.89；A npu 175.19/173.02/167.99/164.82/162.83（新旧 5 点全 ≤5% 等价）；cpu 绑定 154.79/173.78/171.72/158.16/115.13 vs 不绑定 158.67/171.29/143.29/161.08/113.16；hybrid 绑定 100.31/175.68/181.91/182.18/176.24 vs 不绑定 104.38/178.44/177.40/178.24/175.30。判读输入：S2 复证 copy300/500/2048 三档成立（hybrid8 绑定 ≥ npu 锚×1.05 且绑定极差 ≤10%），copy100 hybrid 异常低（~100，稳定低值）、copy200 +1.5% 不达 5% 线；绑定复核无 >10% 反向。判读留蓝区。数据出处：results/r6e/（21 上，gitignore 不入库）+ run_r6e_*.log。
**判读**（蓝区，2026-10-15）：**新旧等价实锤**（5 点全 ≤5%，改写无回归；
cards8/bs32 实测 163–175 GB/s 为两 harness 互证水平；用户记忆中的 230
已定位为 9/16 H2D 专项的 H2D 段口径，不可比）+ **S2 bs32 复证 3/5 档
成立**（copy300/500/2048 命中 ×1.05+极差≤10% 双条件，增益 +8.2~10.5%；
copy200 +1.5% 不达）+ **hybrid copy100 异常新发现**（稳定 ~57%×npu ⇒
生产形态加 copy 数门控，候选 R8 定阈值）+ cpu 全量大 copy 档出局（绑定
copy2048=115.13；cpu-delta 驻留路线不受限）+ 绑定=修复维持（cpu300
+19.8%，hybrid 无 >10% 反向）。逐条裁决见 pingpong.md §R6e 判读节。（2026-10-15）（取消：未交付）

**派单**（commit = 本轮 commit，hash 以 `git log --oneline -1` 为准）：
用户关切 fork 后新旧带宽数字是否一致。21 同机同轮：A 组旧脚本历史矩阵
（CARD_COUNTS="1 2 4 8" BATCH_SIZES="8 16 24 32" COPY_COUNTS="0 100 200
300 500 2048"，96 case，蓝区 dry-run 已核）；B 组新 bench npu 重叠坐标
（bs24×copy{0,100,300}×cards{1,2,4,8}×repeat3，36 case，dry-run 已核）。
两边默认参数（source-len/hbm-slots/copy-cap/warmup/iters/seed/same-seed）
逐参数一致。判据：12 个重叠坐标 |新折叠均值−旧值|/旧值 ≤5% 且新极差 ≤5%
⇒ 新旧等价实锤。通过标准 R6d-G1..G3 与判读预案见 pingpong.md §R6d。
**取消**（2026-10-15，蓝区）：未交付即取消——用户优先 bs32 直接对比；
新旧对账缩为 §R6e G0 迷你组（cards8/bs32 五 copy 档），bs24 十二坐标
对账不做。若绿区已部分执行，数据留档不判读。

## §R6c S2 cards8 原坐标裁决 + fallback 路径首验（2026-10-15）

**派单**（commit = 本轮 commit，hash 以 `git log --oneline -1` 为准）：
R6b 实锤 NUMA（cards4 绑定 +11.97%、gather 段 -19.7%）但 S2 因降卡不可判；
本轮回 21（R5 噪声原地）跑 cards8 原坐标：cpu8 ±bind×3、hybrid cf0.1
cards8 ±bind×4、anchor8×3 共 17 case（NN≥8 直映射 / NN<8 --numa-cycle
循环映射双分支 dry-run 已核）。21 无 numactl ⇒ 首验 sched_setaffinity
兜底路径；21 被占则改 13/glm_52（标注跨机）。代码变更：run_scheme_sweep.py
新增 --numa-cycle（rank→nodes[rank%NN]），自检 46→47 全绿。通过标准
R6c-G1..G5 与判读预案（抽签复现 / S2 升级 / 绑定均值方向 / fallback 验证 /
共享节点标注）见 pingpong.md §R6c。
**交付**（commit a071883，绿区，21 原地执行；numactl missing ⇒ fallback
首验）：R6c-G1..G5 全过；17 case 全 passed、correctness 全 true；拓扑
4 节点 × 96 核、numa_balancing=1（21 特有）；--numa-cycle 循环映射
0,1,2,3,0,1,2,3（rank4-7 共享节点，已标注）。关键实测（蓝区复算一致）：
numa_cpu8 绑定 170.603（极差 9.53%）vs 不绑定 138.285（极差 28.98%）
= **+23.37%**；numa_hybrid8 绑定 **180.019（极差 0.99%）** vs 不绑定
168.721（19.24%）= +6.70%；anchor8 168.512（极差 0.37%，vs §R5 -1.65%
同机）。fallback 三方取证一致（runner numactl=missing + worker bound=1
+ JSON numa_bind=affinity_fallback）。数据出处 21 的 results/r6c/。
**判读**（蓝区，2026-10-15）：**S2 强阳性**——hybrid8 绑定 180.019 ≥
anchor×1.05=176.938 且极差 0.99%，生产形态稿（cf=0.1）**解冻**进入集成
实施评估；**落点抽签原坐标实锤**（不绑定 28.98%>15% 复现、绑定 9.53%
消噪，R5 噪声=CPU gather 段 NUMA 落点，归因闭环）；绑定=修复维持
（cpu8 绑定 170.6 已追平 kernel）；fallback 路径实战验证通过；+26% 高簇
未兑现（稳态 +6.8%），高簇成因列为开放问题。逐条裁决见 pingpong.md
§R6c 判读节。

## §R6b NUMA 归因裁决（numactl 缺失修复版）（2026-10-15）

**派单**（commit = 本轮 commit，hash 以 `git log --oneline -1` 为准）：
§R6 阻塞于前置核验第 4 条（work21 无 numactl，绿区口头回传，无交付
commit）。蓝区不修环境、改代码兜底：numactl 缺失时 runner 经
`SCATTER_C8_NUMA_FALLBACK=<node>` 传节点号，worker 在 DRAM 镜像/staging
池分配前 `os.sched_setaffinity` 绑定该节点 cpulist，first-touch 等效
membind；numactl 存在时仍走原路径。改动：tests/scheme_config.py
（NUMA_FALLBACK_ENV）、tests/run_scheme_multiprocess.py（which 探测 +
numa_command + 日志/JSON 记 numa_bind）、tests/test_scheme_worker.py
（parse_cpulist/_node_cpulist/apply_numa_fallback，main 早期调用）。
自检 41→46 项全绿；23 case dry-run 复核一致（12/8/3，results 前缀
r6b）。通过标准 R6b-G1..G5 与判读预案（照录 §R6 六条）见 pingpong.md
§R6b。同轮蓝区交付分析报告 drafts/noise_attribution_r5.md（R5 噪声
归因：排除项 + NUMA 落点抽签三方证据链 + +26% 来历）。
**交付**（commit 5b4b0ba，绿区，改 13/glm_52 容器执行——13 宿主 torch ABI 不兼容，
容器内 numactl 在 ⇒ 原路径）：R6b-G1..G5 全过；23 case 全 passed、correctness
全 true；<NODES>=4 节点 ⇒ A/B 组降 cards4、anchor8 保持 cards8。关键实测：
numa_cpu cards4 绑定 94.896 vs 不绑定 84.749（**+11.97%**）、cards1 对照
24.488/25.333（-3.34%）、numa_hybrid cards4 89.538/89.098（+0.49%）、
anchor8 167.571（极差 3.30%，vs §R5 -2.20% 跨机参考）；混聚拆分极差：
cpu4 绑定 8.66%/不绑定 8.01%，hybrid4 绑定 1.99%/不绑定 1.80%；per-die
gather（r1）绑定均值 88.45 vs 不绑定 110.09µs（-19.7%）。拓扑：4 节点 ×
96 核、distances 15/20、numa_balancing=0。数据出处 13 的 results/r6b/。
**判读**（蓝区，2026-10-15）：**NUMA 实锤**（cards4 绑定 +11.97% >10%，增益
落 gather 段）+ **绑定=修复**（纳入正式配置候选，与 pretouch 并列）；
落点抽签此环境不成立（不绑定极差仅 8.01%，呈稳定均值差）；S2 不可判
（hybrid cards4 vs anchor8 坐标不齐）⇒ R6c 回 21 cards8 原坐标补测；
R7 顺延。逐条裁决见 pingpong.md §R6b 判读节。

## §R6 NUMA 归因实锤 + 绑定修复验证（2026-10-15）（阻塞：numactl 缺失，由 §R6b 取代，未执行）

**派单**（commit = 本轮 commit，hash 以 `git log --oneline -1` 为准）：
无代码改动，纯测量轮。R5 判读把 hybrid 噪声机制收窄到 CPU gather 段的
NUMA 落点抽签（anchor 极差 3.96% vs hybrid 43~63% + R4 die 双峰 1.74x
三方互洽），本轮裁决：numactl -H 拓扑取证 + cpu（cards8/1）与 hybrid
（cf0.1 cards8）绑定/不绑定同轮对比 + npu anchor 哨兵，共 23 case
（12/8/3，蓝区 dry-run 已核验；--numa-nodes 内建每 case 双跑）。
通过标准 R6-G1..G4 与判读预案（NUMA 实锤 / 落点抽签裁决 / S2 升级 /
证伪分支）见 pingpong.md §R6。
**交付**（commit 本轮 push 后回填）：
**判读**：待交付后蓝区填写。

## §R5 S2 弱阳性同轮高重复确认跑（2026-10-15）

**派单**（commit = 本轮 commit，hash 以 `git log --oneline -1` 为准）：
无代码改动，纯测量轮。R4 判 S2 弱阳性（hybrid cf0.4/0.1 cards8 copy300
超同轮 npu anchor +4.5%/+4.2%，但边际与 run 噪声同量级），本轮高重复
确认：A) hybrid cf∈{0.1,0.15,0.3,0.4}×cards8×copy300×repeat6（24 case，
最优区确认+曲线加密）；B) hybrid cf∈{0.1,0.25}×cards4×copy300×repeat4
（8 case，次要确认）；C) npu anchor cards8 copy300×repeat6（6 case，同轮
锚）；D) npu anchor cards4 copy300×repeat4（4 case）；共 42（蓝区 dry-run
已核验）。通过标准 R5-G1..G4 与判读预案（强阳性/弱阳性维持/翻回阴性
三分支）见 pingpong.md §R5。
**交付**（commit 83d5507）：R5-G1 自检 40 tests OK；R5-G2 四 manifest 全
passed、42 case 全 passed、correctness 全 true、hybrid window==16/overlap/
cpu_frac 一致；R5-G3 分位数齐（npu 的在 latency_us_synced，结构性差异已核）；
R5-G4 anchor8 折叠 171.343 vs §R4 E 171.264（+0.05%）。关键实测：confirm8
cf0.1/0.15/0.3/0.4 = 167.849/161.415/164.463/178.175 GB/s，最优 cf0.4 vs
anchor8 = +3.99%；confirm8 各 cf repeat 极差 43~63% 全「不稳」；anchor8 极差
3.96%（稳）、anchor4 17.97%；p99/p50 全 <2；confirm4 54.823/53.807 << anchor4
63.300。数据出处 results/r5/（gitignore）。注：绿区在文件底部另追加了一份
§R5 条目（append-only 纪律，保留），内容与本节交付一致。
**判读**（蓝区，2026-10-15）：**弱阳性维持**——最优 cf0.4 178.175 <
anchor8×1.05=179.91 且极差 58.8%，强阳性双条件均不满足；178.175 > 171.343
未翻回阴性。延迟口径打平（222.17 vs 221.83µs，+0.15%），带宽 +3.99% 全部来自
per-die 偏斜——**S2 生产价值存疑冻结**。cf* 不可分辨（档间摆动 <10% 但 repeat
极差 43~63%），生产稿按 cf=0.1 写死。cards4 同轮实锤不过锚（0.87x）。噪声机制
收窄：anchor8 稳（3.96%）vs hybrid 不稳（43~63%）+ R4 die 双峰（1.74x）三方
互洽 ⇒ CPU gather 段 NUMA 落点抽签（推测）；若归置稳定到分布上沿收益 +26%
而非 +4%。下一步 R6：NUMA 主菜（拓扑取证 + cpu/hybrid 绑定扫描）+ anchor
哨兵；队列深度顺延 R7 候选。逐条裁决见 pingpong.md §R5 判读节。

## §R4 hybrid 细 frac 扫描 + pretouch/THP 查 gather 成分（2026-10-15）

**派单**（commit = 本轮 commit，hash 以 `git log --oneline -1` 为准）：
无代码改动，纯测量轮。A) hybrid w16/overlap 细 frac（cf∈{0.1,0.25,0.4,0.6}×
cards48×copy{0,100,300}×repeat2，48 case）；B) cpu w16+pretouch（24 case）；
C) THP=always+pretouch（24 case，自记原值自恢复）；D) cpu w16 轮内基线
（8 case）；E) npu cards8 copy300 锚点（2 case）；共 106（蓝区 dry-run 已
核验）。通过标准 R4-G1..G4 与判读预案（S2 阳性 / frac 最优点 / 缺页实锤 /
TLB 实锤 / gather 纯带宽 bound / breakeven 回填）见 pingpong.md §R4。
**交付**（commit 本轮 push 后回填）：纯测量轮 106 case 全过（A frac 48 / B pretouch 24 / C THP+pretouch 24 / D base 8 / E npu anchor 2，RC 全 0）。G1-G4 全过：自检 39 OK；106 case passed+correctness 全 true+window==16+pretouch 分组对；THP 设置/恢复原值 madvise 一致；D vs R3w16 最大偏差 9.58%。关键事实：A 组 cards8 copy300 最优 cf0.1/0.4（178.4/178.9 GB/s）超 E 组 npu anchor 171.3；B pretouch cards8 copy300 cpu_gather 136.2 vs D base 253.3（-46%），cards1 持平；C THP+pretouch 未再降（cards8 179.4，反升）。breakeven 回填 rho*=0.25/0.20（cards1/8 copy300，远左移于 R3 预测 0.37）。结果 results/r4/{frac,pretouch,pretouch_thp,base,anchor}/。
**判读**（蓝区，2026-10-15）：**S2 阳性（弱）**——A 组最优 cf0.4/cf0.1 的 hybrid cards8 copy300 = 178.90/178.41 GB/s ≥ 同轮 npu anchor 171.26（写死判据命中，+4.5%/+4.2%），延迟口径互证（212.06<221.86µs）；但 frac 曲线非单调（cf0.25 凹陷 157.4，相邻档 ±10%），边际与 run 噪声同量级 ⇒ 弱阳性，先入 R5 高重复确认跑再谈生产集成。cf*：cards8 延迟口径 0.1（生产推荐，max 全档最稳）/吞吐口径 0.4，cards4/copy100 内点 0.25；cards4 未过锚（75.4<76.7，跨轮+漂移史，证据弱）。**缺页实锤（cards8 限定）**——B pretouch vs D base 的 cpu_gather cards8 copy300 -46.2%（>15% 判据），cards1 持平（小池无效应）；端到端 folded -7.9%；pretouch 列为正式配置候选（R6 起默认）。**TLB 实锤不成立且 THP=always 有害**——C vs B 全坐标不降，cards8 gather +31.7%、总时 cards4/8 反升 16.4%/25.1%，THP 不采用。**breakeven 回填** ρ*（copy300）cards1 0.25 / cards8 0.20（同轮 w16 T0=5.1/7.2µs），左移于 R2 预测 0.37，驻留+增量路线深度过盈亏点结论加强。预测对照：①部分命中 ②证伪（翻阳）③证伪一半（cards8 非纯带宽 bound；TLB 无收益方向对、形式错）④命中（9.58%）。逐条裁决见 pingpong.md §R4 判读节。下一步 R5：S2 弱阳性同轮高重复确认跑（cf0.1/0.4+加密 0.15/0.3×cards8×repeat6 + 同轮 anchor）+ 蓝区并行生产形态设计稿；队列深度顺延 R6 候选。

## §R3 窗口化流水压 host 开销 + 复试（2026-10-15）

**派单**（commit = 本轮 commit，hash 以 `git log --oneline -1` 为准）：
蓝区按 R2 写死分支实现 worker `--window N`（每窗口 N 迭代共享一次同步，
每迭代独占 staging slot；window=1 逐字等价 R2 语义）+ sweep/runner 转发
（macOS 自检 38 项通过）；绿区免重编，pull 后跑 A) w1 轮内基线 48 case、
B) w16 吞吐模式 48 case、C) npu 锚点 12 case（cpu/hybrid×cards1248×
copy{0,100,300}×repeat2，npu×cards148×copy{0,300}×repeat2，共 108）。
通过标准 R3-G1..G3 与判读预案（host 压减有效性 / S1 翻正 / S2 重开 /
cpu 判死转集合层）见 pingpong.md §R3。
**交付**（commit 14bf82d）：R3-G1 自检 38 tests OK；R3-G2 三 manifest（w1/w16/anchor）全 passed、108 case 全 passed 且 correctness 全 true、window 分档正确（w1=48×1、w16=48×16、anchor=12×1）；R3-G3 w1 cpu/hybrid 24 坐标 vs §R2 同坐标（cf0.5）偏差最大 14.77%（hybrid cards8 copy100），全部 ≤15%。主键实测：cpu copy100 cards1 181.716→86.718µs（w1→w16，8.66→18.16 GB/s）、copy300 cards8 106.94→151.74 GB/s；hybrid copy100 cards1 263.792→162.861µs（5.97→9.67 GB/s）、copy300 cards8 90.44→144.46 GB/s；cpu copy0 cards1 69.195→5.053µs。npu 锚点 copy300 cards1/4/8=33.99/76.70/170.74 GB/s。phases（cpu copy100 cards1）：w1 cpu_gather 46.096 + device_wall 135.621（event 76.819/overhead 58.802）；w16 28.264 + 58.454（event 52.436/overhead 6.018）。数据出处：results/r3/{w1,w16,anchor}/（gitignore 不入库）。
**判读**（蓝区，2026-10-15）：**host 压减有效（超预期）**——copy0 纯固定开销
69~114µs→5~7µs（-94%，低于 npu launch 量级），device_overhead 58.8→6.0µs
（占 avg 6.9%<10% 写死判据）；gather 相位附带提速 46.1→28.3µs。**S1 翻正未
达成**——w16 cpu/npu 锚点 copy300：cards8 151.7 vs 170.7（0.89x）、cards4
67.4 vs 76.7（0.88x，cards4 档连续两轮漂移证据弱）；差距从 w1 的 0.53~0.84x
收敛。**S2 重开候选成立**——w16 hybrid < min(npu, w16 cpu) 于 cards4/8 命中
（52.7<67.4、144.5<151.7），cards1 不命中；h2d_scatter_tail 仅 5.4µs，
overlap 在窗口化下真正藏住 CPU 段。口径纠偏：R2「未归类开销」≈ 新口径
device_overhead_us（数值互洽）。下一步 R4：hybrid 细 frac 扫描 +
pretouch/THP 查 gather 成分；队列深度顺延 R5 候选。

## §R1 A5 首轮主矩阵：npu vs cpu vs hybrid（2026-10-14）

**派单**（commit = 本仓 init commit，hash 以 `git log --oneline -1` 为准）：
蓝区完成 S0–S6 方案 bench 全部代码（macOS 自检 21 项通过）；绿区在 A5 上构建蓝图
OPP（叠加 side_blueprint 补丁，QUEUE_DEPTH=8）、跑自检+双方案冒烟+默认主矩阵
（npu/cpu/hybrid×{0.25,0.5,0.75} × cards{1,2,4,8} × copy{0,100,300}，共 60 case）。
判读标准已在 pingpong.md §R1 写死：cpu ≥ npu（copy=300 全 cards）⇒ S1 阳性；
cpu < npu 且 gather 主导 ⇒ S1 阴性；h2d 主导 ⇒ 方向是减 H2D 量；
hybrid overlap < min(npu,cpu) ⇒ S2 阳性候选；G1–G3 失败 ⇒ 整轮无效。
**交付**（commit 本轮 push 后回填）：G1–G4 全过（build OK / QUEUE_DEPTH=8 / 21 tests OK / 冒烟 2 case correctness 全 true）；G5 未过——主矩阵在 cpu×copy0 坐标崩（test_scheme_worker.py:239 访问 case.staging 为 None——copy=0 时 phys_src_all 空致 staging 未分配），60 个 case 仅完成 12 个 npu（全 passed、correctness 全 true），cpu/hybrid 未跑；manifest status=failed。数据出处：results/copy_scheme_a5_c8/（gitignore 不入库），npu cards1/copy100=32.649 GB/s 与冒烟 32.485 同轮一致。
**判读**（蓝区，2026-10-15）：**主矩阵无效**（蓝区脚本缺陷，非被测对象问题）；
npu 基线 12 坐标有效落袋（实测值：cards1 32.6/34.1，cards2 65.3/68.0，cards4
88.9/82.0，cards8 178.6/175.0 GB/s，copy100/300；copy0 launch 开销 ~11µs）；
S1/S2 顺延 R2。观察（非裁决）：≥4 die 聚合亚线性（单 die 34→21 GB/s，共享链路
竞争信号）；冒烟同坐标 cpu gather 相位 ≈20ns/行与 npu kernel 持平，差距在
H2D 72.4µs 与未归类 host 开销 ~72µs（占 37%）。逐条裁决见 pingpong.md §R1 判读节。

## §R2 修复后重跑主矩阵（2026-10-15）

**派单**（commit = 本轮 commit，hash 以 `git log --oneline -1` 为准）：
蓝区修复 cpu/hybrid 空份额崩溃（cpu_gather/cpu_device_pass 空份额早退）+ 新增
回归测试（macOS 自检 22 项通过）；绿区免重编，pull 后跑定点回归（copy0×cpu/hybrid
4 case）+ 全量主矩阵 60 case。通过标准 R2-G1..G4 与判读预案见 pingpong.md §R2
（S1/S2 判据沿用 §R1 未移动；新增「未归类 host 开销 >30% ⇒ S1 阴性（host 开销
主导），先压 host 开销再复试」分支）。
**交付**（commit 02a18dc）：R2-G1 自检 22 tests OK；R2-G2 定点回归 4 case 全 passed（cpu copy0=68.505µs / copy100=187.589µs=8.393 GB/s；hybrid copy0=109.968µs / copy100=257.277µs=6.119 GB/s，correctness 全 true，cpu×copy0 无 AttributeError）；R2-G3 主矩阵 60 case 全 passed（manifest passed、case_count=60、correctness 全 true）；R2-G4 npu 12 坐标 vs §R1 附表偏差——cards1/2/8 ≤3.72%，cards4 档 copy100=66.662(25.01%)/copy300=65.714(19.89%) 超 15% ⇒ 环境漂移，npu 基线跨轮不可比，一切对比以 R2 轮内坐标为准。数据出处：results/r2_regression/ + results/copy_scheme_a5_c8/（gitignore 不入库）。
**判读**（蓝区，2026-10-15）：**S1 阴性（host 开销主导）**——cpu copy300 全坐标
< npu（18.2~109.8 vs 34.0~168.5 GB/s），回归同坐标未归类 host 开销 65.4µs
占 34.9%（>30% 阈值）、copy0 时 56.9µs（83.1%）；固定开销随 die 数上涨
（71.8→119.8µs，npu 恒 ~11µs），主体是每迭代 launch/sync 串行成本；边际成本
（模型反推）cpu 26~36 vs npu 18~40 ns/token，cards4/8 已持平，净输在固定开销。
**S2 阳性候选不成立**——hybrid 无坐标 < min(npu,cpu)，其 copy0 开销
107~152µs 高于 cpu，overlap 不藏反伤。下一步按写死分支：R3 压 host 开销
（窗口化流水）+ 同坐标复试。逐条裁决见 pingpong.md §R2 判读节。

## §R5 S2 弱阳性同轮高重复确认跑（2026-10-15）

**派单**（commit = 本轮 commit，hash 以 `git log --oneline -1` 为准）：
蓝区 §R4 判读 S2 弱阳性（hybrid cf0.4/cf0.1 cards8 copy300 = 178.90/178.41
GB/s ≥ 同轮 npu anchor 171.26，但 frac 曲线非单调、边际与 run 级噪声同量级），
派 S2 同轮高重复确认跑：confirm8 hybrid cf{0.1,0.15,0.3,0.4} cards8 copy300
w16 repeat6（24 case）、confirm4 hybrid cf{0.1,0.25} cards4 copy300 repeat4
（8 case）、anchor8/anchor4 npu（6/4 case），共 42 case（蓝区 dry-run 已核验，
iters=1000 默认）。判读预案三分支（强阳性 / 弱阳性维持 / 翻回阴性）与回传格式
（交付模板 + 4 timing_summary 全文 + 4 manifest 全文 + 3 case JSON）见
pingpong.md §R5。
**交付**（commit 本轮 push 后回填）：R5-G1 自检 40 tests OK；R5-G2 四 manifest
全 passed + 42 case 全 passed + correctness 全 true + hybrid window==16/
overlap/cpu_frac 一致（r5_verify2 bad=0）；R5-G3 32 hybrid case 含
latency_us.p50/p99，10 npu case 无 latency_us 字段（结构性差异，p50/p99 在
latency_us_synced，逐 case 已核）；R5-G4 anchor8 折叠 171.343 GB/s vs §R4 E
171.264（+0.05% ≤15%）。关键实测（折叠带宽）：confirm8 cf0.1/0.15/0.3/0.4 =
167.849/161.415/164.463/178.175 GB/s，最优 cf0.4 vs anchor8 171.343 =
1.0399（+3.99%）；confirm8 各 cf repeat 带宽极差 43~63% 全「不稳」；p99/p50
42 case 全 <2；confirm4 54.823/53.807 均 < anchor4 63.300（参考项）。数据出处：
results/r5/（gitignore 不入库）+ run_r5.log。判读留蓝区（§R5 判读预案三分支
输入已齐：折叠带宽/极差/p99/p50/跨轮对照）。
## §R6b NUMA 归因裁决（numactl 缺失修复版）（2026-10-15）

**派单**（commit=8638f8d）：numactl 缺失修复——worker sched_setaffinity 兜底（池分配前绑节点 cpulist，first-touch 等效 membind），numactl 在则走原路径；日志/JSON 记 numa_bind 取证；自检 41→46 项全绿；23 case（12/8/3）dry-run 复核一致；R6 阻塞由 §R6b 取代。

**交付**（commit 本轮 push 后回填）：R6b-G1 自检 46 tests OK；R6b-G2 三 manifest 全 passed + 23 case 全 passed + correctness 全 true（per_device 层 data_exact/guard_unchanged）+ window==16 + hybrid cpu_frac==0.1 + numa 组每坐标不绑定/绑定成对（r6b_verify2 bad=0）；R6b-G3 拓扑 4 节点(0-3)、numa_balancing=0；R6b-G4 anchor8 折叠 167.571 vs §R5 171.343（-2.20% ≤15%）；R6b-G5 numactl 原路径 rank→node 一一对应、JSON config.numa_bind 一致。执行环境：141.61.33.13 glm_52 容器（torch 2.10.0 匹配，13 宿主 ABI 不兼容）；<NODES>=4 节点 → A/B 组 cards 8→4、anchor8 保持 8。关键实测（折叠带宽，绑定 vs 不绑定）：numa_cpu cards1 24.488 vs 25.333（-3.34%）、cards4 94.896 vs 84.749（+11.97%，avg_us_mean -9.82%）；numa_hybrid cards4 89.538 vs 89.098（+0.49%）；anchor8 167.571（spread 3.30%）。判读留蓝区。数据出处：results/r6b/（13 上，gitignore 不入库）+ run_r6b_*.log。

## §R6c S2 cards8 原坐标裁决 + fallback 路径首验（2026-10-15）

**派单**（commit=7f8427f）：回 21 跑 cards8 原坐标 17 case（6/8/3），首验 sched_setaffinity fallback 路径；新增 --numa-cycle 循环映射（rank→nodes[rank%NN]，NN=4<8 → rank4/5/6/7 共享 node0/1/2/3，共享节点标注不与 NN≥8 混比）；自检 46→47 项。

**交付**（commit 本轮 push 后回填）：R6c-G1 自检 47 tests OK；R6c-G2 三 manifest 全 passed + 17 case 全 passed + correctness 全 true + window==16 + hybrid cpu_frac==0.1（r6c_verify bad=0）；R6c-G3 拓扑 4 节点、numa_balancing=1、which numactl=missing；R6c-G4 anchor8 折叠 168.512 vs §R5 171.343（-1.65% ≤15%）；R6c-G5 fallback 兜底路径首验成功（runner 级 numactl=missing fallback=sched_setaffinity nodes=0,1,2,3,0,1,2,3 + 每 worker node=<N> cpus=<清单> bound=1 + LAUNCH numa_bind=affinity_fallback rank→node 循环映射 rank0→0..rank7→3），JSON config.numa_bind 一致。执行环境：141.61.33.21（21 无 numactl，numa_balancing=1 与 13 的 0 不同，判读注意）。关键实测（折叠带宽，绑定 vs 不绑定）：numa_cpu8 170.603(9.53%) vs 138.285(28.98%) = +23.37%；numa_hybrid8 180.019(0.99%) vs 168.721(19.24%) = +6.70%；anchor8 168.512(0.37%)。判读输入：抽签复现——不绑定 28.98%>15% 且绑定 9.53%≤10% 双条件齐；S2 升级——绑定 0.99%≤10% 且 180.019 ≥ 168.512×1.05=176.938 双条件齐。判读留蓝区。数据出处：results/r6c/（21 上，gitignore 不入库）+ run_r6c_*.log。

## 文档：hybrid 机制详解并入生产形态稿（2026-10-15，蓝区）

drafts/production_form_hybrid.md 扩写：新增 §0 机制详解（一句话/带宽账
/行级切分/双流 overlap/window=16/pretouch+NUMA/实测全景与门控），配
4 张 SVG（drafts/assets/hybrid_{dataflow,timeline,numa,gating}.svg）；
§4 NUMA 口径更新（R6 实锤纳入默认，原「未测」作废）；§5 风险 1 消解、
新增门控阈值未标定；§6 队列更新（R6e 完成，R7/R8 在队列）。非测量轮，
无执行数据。

## §D1 同代码异机性能归因诊断（2026-10-15，蓝区）（诊断系列第 1 单，独立于 R 轮编号）

**派单**（commit 本轮 push 后回填）：起因——蓝图仓 commit `08f0e601`（原版
depth=2）在 X 机（x86_64+A5，CANN 9.1.0，宿主机编译）带宽「很差」，21
（aarch64+A5，CANN 9.2.0）正常；蓝区已核 `git diff 08f0e601 bb062d2`
csrc 零差异 ⇒ 嫌疑在环境层（PCIe 拓扑/IOMMU/host NUMA/swapped 驱动路径/
CANN 版本）。容器编译报错 `std::length_error: vector::reserve`（build_c8.sh:86
import 冒烟）= C++ ABI 不匹配，只解释「容器编不了」，不产生慢版 kernel。
本轮只取证定位不改被测代码；新增工具 tools/h2d_probe.py（连续 H2D 带宽
探针，区分链路差 vs 随机读差）。执行矩阵：A 环境取证（uname/npu-smi/CANN
version/lspci -tv/LnkCap+LnkSta/numa_node/dmesg IOMMU/numactl -H/~/.ascend
缓存）+ B1 连续 H2D 探针逐卡×8 + B2 单卡 scatter 原版脚本（bs32 copy300）
+ C 多卡扩展原版 harness（cards1/2/4/8 × bs32 × copy300），X 机与 21 同
命令对照；21 参照用 git worktree 拉 08f0e60 另编（不动主 checkout depth=8
构建）。D 分支仅 X 机按取证触发（D1a 跨 socket 则 numactl 绑定重跑；
D1b depth 2→8 单行改重编重跑，喂 R7 队列深度扫描基线）。前置核验含 X 机
可达性确认（不可达则改派对方手动执行模板）。判读预案（写死）：B1 差>20%
⇒ 链路层实锤；B1 相当但 scatter 差 ⇒ 随机读路径（IOMMU/swapped/CANN 版本）；
cards1 差距小 cards8 拉大 ⇒ 共享上游竞争；D1a 恢复 ⇒ host NUMA 跨节点；
D1b 两机深度收益幅度对比 ⇒ 深度敏感性的环境依赖。R 轮队列编号不变
（R7 队列深度扫描、R8 门控阈值扫描仍待派）。

## §K1 KVAF(URMA) vs KSC(PCIe) 同机 H2D 带宽 A/B（2026-10-20，蓝区）（K 系列第 1 单，独立于 R/D 编号）

**派单**（commit 7621458）：目标——同机同会话、656B/token 同口径
A/B 两条搬运路径的有效 H2D 带宽，喂 KSC/KVAF 融合裁决的带宽裁决门。
A 组 = 本仓 npu 方案（蓝图 scatter_copy，PCIe 核内 MTE）cards1/8 ×
bs24 × copy{300,2048} × repeat3（12 case，同轮 anchor）；B 组 = 0903 仓
benchmark_kvaf_batch_get.py（KVAF BatchGet，UB/URMA 核外 UDMA）单卡
bs24 × miss{300,2048}，取 batch_get_npu_event 的 payload_gibps；C 组可选
= benchmark_lidu_fused_batch_get.py 的 post/transfer_window/completion_wait
阶段分解（钉死「bulk payload 走核外 UDMA」的插桩证据）。关键前置：定位
同时具备 /dev/uburma + 0903 仓 checkout + KVAF ak_mtp_yq 构建产物 +
kvaf_cpu_service 的 A5 机；找不到则绿区停下回传、蓝区改派。判据写死：
KVAF ≥ KSC×1.2 ⇒ URMA 优势实锤；0.8~1.2× ⇒ 同档、带宽非决策变量；
<0.8× ⇒ 劣势，用 C 组分解定位。多卡 KVAF 聚合不在本轮。零代码改动。

## §K1b KVAF vs KSC H2D 带宽 A/B——空环境从零搭建版（2026-10-21，蓝区）（取代 §K1）

**派单**（commit 0b79fd7）：起因——用户确认目标 A5 为完全空环境
（无 docker/CANN/仓库），§K1 前置 3「定位已有 KVAF 环境机器」不成立。
改派：新增 side_kvaf/baremetal_runbook.md（从零搭建六阶段手册：Go/No-Go
核验 → CANN9.1+torch2.10/torch-npu2.10.0.post2 → 三仓 clone → KSC
build_c8+两点 → KVAF cpu/npu 构建+standalone registration+起 service →
KVAF 两点 → KSC 复跑防漂移），绿区逐阶段照做、逐条回传。测量坐标与
判读预案沿用 §K1 写死口径（bs24×{300,2048}、656B/token、payload_gibps
×1.0737 换算、1.2×/0.8× 三档裁决）。零被测代码改动。

## §K2 URMA(KVAF BatchGet)带宽极限——自包含 bench 版（2026-10-21，蓝区）（取代 §K1b）

**派单**（commit 07807fe）：起因——用户澄清「其实就想看走 URMA
的带宽极限」，并要求测试所需全部进公开仓。蓝区新写自包含 bench
side_kvaf/urma_ceiling_bench.py：直接用 KVAF NpuRuntime.batch_get
（descriptor 由脚本构造，不经 DSA Prepare 算子），依赖只剩 KVAF NPU
binding + torch/torch_npu——0903 私有仓、vLLM、DSA 算子、docker 全部
移出依赖链；side_kvaf/baremetal_runbook.md 重写为五阶段自包含版
（Go/No-Go → CANN+venv → 两仓 → KVAF cpu/npu 构建 → 起 service → 扫描）。
唯一剩余私有依赖 = gitcode CacheOS/KVAF 源码（凭据 clone 或用户放
tarball；第三方私有代码，不入公开仓）。扫描矩阵：tokens {7200,16384,
49152,131072,262144}×{sequential,random}=10 点，每点 ok 校验 + NPU event
流水计时，报 gibps+gbps。判据写死：极限=sequential 最高档 gbps；仍上升
⇒ 加档复测；random 低 >30% 标注随机惩罚；KSC 对照沿用 1.2×/0.8× 三档。

## §K2 补充：docker 变体并入 runbook（2026-10-21，蓝区）（非测量轮）

用户提出官方镜像候选。蓝区核 quay manifest/config：
`quay.io/ascend/vllm-ascend:v0.23.0.post1-a5-openeuler` 存在 arm64 变体，
CANN 9.1.0 toolkit 装于 /usr/local/Ascend/cann-9.1.0（编译链在 PATH），
python 3.12.13，SOC_VERSION=ascend950dt_9582 构建，git/cmake/gcc/numactl
齐 ⇒ 可作阶段 1 的 docker 替代路径。runbook 新增「1b docker 变体」
（pull + 设备/驱动//dev/uburma//usr/lib64 挂载清单 + 容器内版本核验
四行），pingpong §K2 加补充节。镜像内 torch/torch-npu 版本待绿区
pip show 回传留档；KVAF binding 同环境源码编译，ABI 自洽。无执行数据。

## §K2 补充 2：docker 镜像双 tag（2026-10-21，蓝区）（非测量轮）

用户提出第二个候选 tag。蓝区核 manifest/config：
`quay.io/ascend/vllm-ascend:v0.27.1rc1-a5-openeuler` 存在 arm64 变体，
CANN 9.1.0 toolkit + 编译链 + python 3.12.13 + ascend950dt_9582 构建，
与 v0.23.0.post1 底座一致；差别仅在 vLLM 层（v0.27.1rc1，本测试不用）。
runbook 1b 改为 IMAGE 变量双 tag 任选，docker run 引用 $IMAGE。无执行数据。

## §K2 补充 3：KVAF 供给方式明确化（2026-10-21，蓝区）（非测量轮）

绿区反馈卡点：bench 仍依赖 KVAF 仓产物（NPU binding / 两个 kernel .o /
kvaf_cpu_service）——蓝区确认该依赖不可约（被测对象即 KVAF 引擎本身；
「自包含」仅去掉 0903 仓/vLLM/DSA 算子/docker 四样）。runbook 阶段 2 改写
为三选一供给：A=源码 tar 包（开发机 /data/projects/KVAF ak_mtp_yq 打包、
目标机现编，推荐）；B=产物 tar 包（build-npu/bin + build-npu/python +
build-cpu/runtime，限开发机与目标机环境一致，可跳过构建）；C=gitcode
凭据经私有渠道传递（禁入公开仓）。无执行数据。

## §K2 交付 1：BatchPut 全核失败——产物-环境不匹配证据链（2026-10-22，绿区）（卡点：待蓝区补发 KVAF 源码/凭据）

绿区执行 §K2 阶段 5（runbook 五阶段自包含版）卡在 KVAF NpuRuntime link_to 内部
EID-pair RMA probe：32/32 核 AIV `BATCH_PUT_DEVICE_ERROR result=8 cq_status=2
cq_sub_status=2 completed_batches=0` + `BATCH_PUT_EXECUTION_ERROR result=-5` +
`PEER_LINK_EID_PAIR_FAILED`。CPU service 侧零错误（124 通道全建链、REGION_ALLOCATED
4786176B 与 bench ddr_bytes 一致）。已排除：bench 调用（KVAF_M 自带 perf 测试同错）、
设备选择（pin udmac0d1e6 后仍失败）、EID 配对（reverse 编码匹配 candidate0）、
DDR 分配（一致）。根因指向 KVAF_M 预构建产物（跨机构建：CMakeCache 指向
/home/x00965276/third_party/umdk，kernel .o clang 2026-07-21 编译）与当前环境
（CANN 9.1.0/驱动 25.6.rc2/UMDK br_UMDK_24.12.0_LTS）不匹配。按 runbook 纪律报错
停步不猜修。数据出处：/tmp/urma_bench_run.log、/tmp/kvaf_perf_run2.log、
/tmp/kvaf_cpu_service3.log（不入库）。请求蓝区按阶段 2 方式 A（源码包）或 C（凭据）
补发 KVAF。

## §K2 交付 1 判读（2026-10-22，蓝区）

绿区交付（commit e5faf7a）：阶段 5 BatchPut 全核失败（32/32 核 AIV
result=8/cq_status=2，link_to 内 EID-pair RMA probe 阶段），零带宽数据。
蓝区裁决：**无效测量（供给问题），非阴性**。根因=方式 B 预构建产物跨机
不匹配（kernel .o 2026-07-21 clang 15.0.5 他机编译 vs 目标机 CANN 9.1.0/
驱动 25.6.rc2）；排除链成立（KVAF 官方 perf 脚本同错 ⇒ 非 bench 问题；
service 124 通道全成链 ⇒ CPU 侧无罪）。环境留档：90.96.17.111（8×
950DT_9582、UB 候选 26、liburma 0.0.3）+ 镜像 v0.30.0rc2-a5-openeuler
（torch 2.10.0+cpu/torch_npu 2.10.0.post4）记为已验证底座。下一步：用户
按方式 A 补发 KVAF 源码包（或方式 C 凭据），绿区收包后重跑阶段 3-5，
判据不变。方式 B（产物包）自此标记为已证伪路径。

## §K2 供给核查与绿区自查指引（2026-10-22，蓝区）（非测量轮）

用户转述供方「只有编译产物、没有源码包」。蓝区核查：本机无 KVAF
checkout（0903 仓 third_party/KVAF 不存在）；gitcode 本机 keychain 凭据
（fangjijia）对 CacheOS/KVAF 无读权限（ls-remote: can not read project）
⇒ 蓝区无法直接供包。注意到绿区交付中 KVAF_M tarball 顶层含
build.sh/CMakeLists.txt/docs/tests——疑似完整源码树带产物而非纯产物包，
已在 pingpong §K2 判读追加绿区零成本自查命令（find 源码文件 → 有则本机
现编等价方式 A；无则维持等用户方式 A/C）。无执行数据。

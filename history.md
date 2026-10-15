# History

蓝绿协作轮次档案。只追加，不修改。每轮至少记录：派单 commit、执行环境、原始数据出处、判读结论与置信度。

## 轮次记录格式

```
## §R<n> <标题>（<日期>）

**派单**（commit <id>）：<一句话任务 + 判读通过标准>
**交付**（commit <id>）：<一句话结果 + 数据出处>
**判读**（蓝区）：<阳性/阴性/无效 + 依据 + 下一步>
```

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

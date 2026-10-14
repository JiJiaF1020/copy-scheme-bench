# Pingpong

## Protocol

- 本文件是蓝区 ↔ 绿区的唯一通信面；`history.md` 是只追加的轮次档案。
- **蓝区**（可外部 AI 侧）写全部代码、做全部判读决策；**绿区**（隔离执行侧）按任务书执行并回写交付，不改代码。
- 每次 commit 必须同时包含代码 + `pingpong.md` + `history.md`；pull 用 `--ff-only`；绝不 force-push。
- Current owner: **绿区**。Status: R4 派单已发出（R3 判读完成，见 §R3 判读节），等待交付。

## 0. 目标与口径

**唯一目标**：在 A5（Ascend 950）上判定离散 C8 token 的 DRAM→HBM 回搬最优路径——
NPU kernel 直读（基线）/ CPU gather + 大块 H2D / 两者混合分流——产出可用于
vLLM 集成决策的带宽对比数据。

**锚点**：

- 蓝图仓 `nanovllm-scatter_copy`，分支 `scatter_copy_a5_c8`，origin tip `bb062d2`
  （"Unify scatter bandwidth test CLI and six-column results"）。
- 蓝图仓必须叠加本仓 `side_blueprint/blueprint_wip_queue8_numa.patch`
  （内容：kernel `QUEUE_DEPTH` 2→8 + runner 的 NUMA 绑定支持；蓝区已验证
  `git apply --check` 干净）。历史上已测的 C8 带宽曲线对应 depth=8。
- payload 口径：每 token 656 字节（C8 packed）；BLOCK=128；COPY_CAP=16384。

**测量口径（写死，不移动）**：

- 带宽 = `payload_bytes / avg_us`，十进制 GB/s；`payload_bytes = copied_tokens × 656`。
- 多 die 带宽 = 各 die 速率之和（不用 mean/max 反推）；延迟列给 `avg_us_mean` / `avg_us_max`。
- `npu` 方案 `avg_us` 是 NPU Event 包 iters 次异步 launch 的流水吞吐（与蓝图既有
  数字同口径，可直接对表）；其 `performance.avg_us_host_synced` 是逐迭代同步墙钟。
- `cpu`/`hybrid` 方案 `avg_us` 是逐迭代 host 墙钟（每迭代末 sync），相位分解在
  `performance.phases`。
- 对比只在**同机、同轮、同 cards/bs/copy 坐标**之间有效；跨机器/跨会话绝对值不可比。
- 正确性门槛先于性能：任何 case 的 correctness 非全 true，该 case 数据无效。

---

## §R4 派单：hybrid 细 frac 扫描 + pretouch/THP 查 gather 相位成分（2026-10-15，蓝区）

### 目标

R3 判读：host 压减有效（超预期），S1 翻正未达成（w16 cpu/npu 0.88~0.89x），
S2 重开候选成立（hybrid cf0.5 于 cards4/8 < min(npu, w16 cpu)）。本轮两件事：

1. **hybrid 细 frac 扫描**（w16，overlap，cards4/8，cf∈{0.1,0.25,0.4,0.6}）：
   找最优分流点 cf*，看最优 cf 能否过同轮 npu 锚点（S2 阳性裁决）。
2. **pretouch / THP 查 w16 cpu gather 相位（28.3µs）的成分**：缺页（pretouch
   可消）？TLB miss（THP 可消）？还是纯带宽 bound（两者皆不动）？

队列深度（npu 侧余量）顺延 R5 候选。本轮无代码改动，纯测量。

### 前置核验

1. 本仓 `git pull --ff-only` 后 `git log --oneline -1` 标题为
   "R4: §R4 派单（hybrid 细 frac 扫描 + pretouch/THP 查 gather 成分）"。
2. 蓝图仓不变：`git -C ../nanovllm-scatter_copy log --oneline -1` = `bb062d2`；
   `QUEUE_DEPTH = 8`；**不需要重编**。
3. 环境变量无残留（同 §R1 前置核验第 5 条）。

### 执行命令

逐字执行（工作目录 /home/h2d_test/copy-scheme-bench）：

```bash
git pull --ff-only && git log --oneline -1
cd tests && python3 test_scheme_tools.py && cd ..
# A: hybrid 细 frac 扫描（48 case）
bash run_scheme_sweep.sh --schemes hybrid --cpu-fracs 0.1 0.25 0.4 0.6 \
  --hybrid-modes overlap --cards 4 8 --batch-size 24 --copy-count 0 100 300 \
  --window 16 --repeat 2 --results-dir results/r4/frac
# B: cpu + pretouch（24 case）
bash run_scheme_sweep.sh --schemes cpu --cards 1 2 4 8 --batch-size 24 \
  --copy-count 0 100 300 --window 16 --pretouch --repeat 2 \
  --results-dir results/r4/pretouch
# C: THP=always + pretouch（24 case）；自记录原值、自恢复
THP_EN_ORIG=$(sed 's/.*\[\(.*\)\].*/\1/' /sys/kernel/mm/transparent_hugepage/enabled)
THP_DE_ORIG=$(sed 's/.*\[\(.*\)\].*/\1/' /sys/kernel/mm/transparent_hugepage/defrag)
echo "orig: enabled=$THP_EN_ORIG defrag=$THP_DE_ORIG"
echo always > /sys/kernel/mm/transparent_hugepage/enabled
echo always > /sys/kernel/mm/transparent_hugepage/defrag
cat /sys/kernel/mm/transparent_hugepage/enabled /sys/kernel/mm/transparent_hugepage/defrag
bash run_scheme_sweep.sh --schemes cpu --cards 1 2 4 8 --batch-size 24 \
  --copy-count 0 100 300 --window 16 --pretouch --repeat 2 \
  --results-dir results/r4/pretouch_thp
echo "$THP_EN_ORIG" > /sys/kernel/mm/transparent_hugepage/enabled
echo "$THP_DE_ORIG" > /sys/kernel/mm/transparent_hugepage/defrag
cat /sys/kernel/mm/transparent_hugepage/enabled /sys/kernel/mm/transparent_hugepage/defrag
# D: 轮内基线 cpu w16（8 case；B/C 的比较基准，防跨轮漂移）
bash run_scheme_sweep.sh --schemes cpu --cards 1 8 --batch-size 24 \
  --copy-count 0 300 --window 16 --repeat 2 --results-dir results/r4/base
# E: npu 漂移哨兵（2 case；S2 判据的同轮 npu 值）
bash run_scheme_sweep.sh --schemes npu --cards 8 --batch-size 24 \
  --copy-count 300 --window 16 --repeat 2 --results-dir results/r4/anchor
```

共 106 case（蓝区 dry-run 已核验各组 case 数 48/24/24/8/2）。若 C 组 THP
节点不存在或无权限：原样记录报错，跳过 C 组，其余组照常执行（不算整轮失败）。

### 通过标准

- R4-G1：自检末两行 `Ran 39 tests` / `OK`。
- R4-G2：五个 manifest 全 `status=="passed"`；106 个 case JSON 全 passed、
  correctness 全 true；全部 case JSON `config.window==16`；pretouch/pretouch_thp
  两组 `config.pretouch==true`、base 组 `==false`（防串组）。
- R4-G3：C 组三次 cat 输出回传——「orig」行记录原值；设置后那次
  enabled/defrag 均显示 `[always]`；收尾那次恢复原值（与 orig 一致）。
- R4-G4（跨轮一致性，非门槛）：D 组 vs §R3 w16 同坐标（cpu cards1/8
  copy0/300）偏差 ≤15%；超出原样回传注明。

### 回传格式

同 §R3：交付模板 + 五个目录的 `copy_scheme_timing_summary.md` 全文 +
五个 manifest 全文 + 4 个 case JSON 全文——B/C/D 组 cpu cards1 copy100 各一
（看 gather 相位成分）、A 组 hybrid cards8 copy300 cf0.25 一个（看最优区
phases）+ C 组三次 cat 输出原文。

### 判读预案（派单时写死）

- 比较口径：同轮同坐标，avg_us_mean 用 repeat 折叠值；`p99/p50 > 2` 的坐标
  标注「波动大，证据弱」。
- **S2 阳性**：A 组最优 cf 的 hybrid copy300 cards8 带宽 ≥ 同轮 E 组 npu
  anchor ⇒ S2 阳性，转入生产形态评估（vLLM 集成形态）。
- frac 曲线：给出 cards4/8 各 copy 档的最优分流点 cf*；若曲线在边界取最优
  （无内点极小），如实记录并标注「边界最优」。
- **缺页实锤**：B 组 cpu_gather_us 较 D 组同坐标降 >15%。
- **TLB 实锤**：C 组 cpu_gather_us 较 B 组同坐标再降 >10%。
- B、C 均无明显下降 ⇒ gather 相位为纯带宽 bound，CPU 侧无更多可压空间，
  资源转 R5（队列深度）或集合层方向。
- 顺带回填 breakeven 模型：用 w16 实测 T0_cpu（5.1~6.6µs）重算交叉点 ρ*
  表，对照 drafts/breakeven_r2_preview.md 的预测（copy300 档 0.64→0.37）。
- 任何 case correctness 失败 ⇒ 该 case 无效（不影响其他坐标判读）。

---

## §R3-旧 派单：窗口化流水压 host 开销 + cpu/hybrid 同坐标复试（2026-10-15，蓝区）

### 目标

R2 判读 S1 阴性（host 开销主导：cpu 未归类 host 开销 34.9%>30%，copy0 纯固定
开销 56.9~119.8µs 随 die 数上涨）。本轮验证写死分支的下一步：worker 新增
`--window N`（每窗口 N 次迭代共享一次同步，每迭代独占 staging slot），
**window=16（吞吐模式）vs window=1（R2 语义，轮内基线）**同轮对比。

### 前置核验

1. 本仓 `git pull --ff-only` 后 `git log --oneline -1` 标题为
   "R3: §R3 派单（host 压减复试 window 1 vs 16）+ drafts 状态更新"。
2. 蓝图仓不变：`git -C ../nanovllm-scatter_copy log --oneline -1` = `bb062d2`；
   `QUEUE_DEPTH = 8`；**不需要重编**。
3. 环境变量无残留（同 §R1 前置核验第 5 条）。

### 执行命令

逐字执行（工作目录 /home/h2d_test/copy-scheme-bench）：

```bash
git pull --ff-only && git log --oneline -1
cd tests && python3 test_scheme_tools.py && cd ..
# A: window=1 轮内基线（与 R2 同语义，48 case）
bash run_scheme_sweep.sh --schemes cpu hybrid --cpu-fracs 0.5 --hybrid-modes overlap \
  --cards 1 2 4 8 --batch-size 24 --copy-count 0 100 300 --repeat 2 \
  --results-dir results/r3/w1
# B: window=16 吞吐模式（48 case）
bash run_scheme_sweep.sh --schemes cpu hybrid --cpu-fracs 0.5 --hybrid-modes overlap \
  --cards 1 2 4 8 --batch-size 24 --copy-count 0 100 300 --repeat 2 --window 16 \
  --results-dir results/r3/w16
# C: npu 锚点（12 case；window 对 npu 无影响，只作轮内对照）
bash run_scheme_sweep.sh --schemes npu --cards 1 4 8 --batch-size 24 \
  --copy-count 0 300 --repeat 2 --results-dir results/r3/anchor
```

### 通过标准

- R3-G1：自检末两行 `Ran 38 tests` / `OK`。
- R3-G2：三个 manifest 全 `status=="passed"`；108 个 case JSON 全 passed、
  correctness 全 true；`w16` 目录 case JSON 的 `config.window==16`，
  `w1` 目录 `==1`（防窗口串组）。
- R3-G3（跨轮一致性，非门槛）：w1 的 cpu/hybrid 坐标与 §R2 交付 summary 同
  坐标偏差 ≤15%；超出原样回传注明。

### 回传格式

同 §R2：交付模板 + 三个目录的 `copy_scheme_timing_summary.md` 全文 +
manifest 全文 + 4 个 JSON 全文（cpu cards1 copy100 的 w1/w16 各一、hybrid
cards1 copy100 的 w1/w16 各一，看 phases 用）。

### 判读预案（派单时写死）

- 比较口径：同轮同坐标，avg_us_mean 用 repeat 折叠值；引用分位数时用 p50；
  `p99/p50 > 2` 的坐标标注「波动大，证据弱」。
- 若 w16 cpu 的未归类 host 开销（= avg_us − cpu_gather_us − device_wall_us）
  占 avg_us 从 w1 的 ~35% 降到 <10% ⇒ **host 压减有效**。
- 若 w16 cpu 在 copy300 的 cards4/cards8 坐标 ≥ 同轮 npu 锚点带宽 ⇒
  **S1 翻正（窗口化形态）**，下一轮做生产形态评估（流水线化集成）。
- 若 w16 未归类占比仍 >30% ⇒ host 开销不是同步主导（是 Python/torch 调用
  本身），cpu 路径判死，资源转集合层方向（churn 工具链已就绪）。
- 若 w16 hybrid < 同坐标 min(npu, w16 cpu) ⇒ S2 重开候选，下轮扫细 frac。
- 任何 case correctness 失败 ⇒ 该 case 无效；窗口化破坏正确性（如
  assert_copied 失败集中出现在 w16）⇒ 窗口实现有竞态，蓝区修复后重派。

### 交付（§R3，2026-10-15，绿区）

**执行环境**：机器 work21（141.61.33.21）openEuler aarch64；8× Ascend950DT_9572（可见设备 0-7）；宿主 root；CANN 9.2.0（/usr/local/Ascend/ascend-toolkit/latest）；时间 2026-10-14T17:56:27Z–18:18:29Z（A w1 17:56:27–18:06:14Z、B w16 18:06:14–18:15:57Z、C npu 锚点 18:15:57–18:18:29Z）。
**前置核验**：逐条实际值——
1. 本仓 `git log --oneline -1` = `0bb950d R3: §R3 派单（host 压减复试 window 1 vs 16）+ drafts 状态更新` ✓
2. 蓝图仓 `git -C ../nanovllm-scatter_copy log --oneline -1` = `bb062d2` ✓；`QUEUE_DEPTH = 8` 计数 1 ✓；`_custom_opp_c8/` 构建产物仍在 ✓；**未重编**（派单注明不需要）✓
3. 环境变量无残留：ASCEND_CUSTOM_OPP_PATH/PYTHONPATH/ASCEND_AICPU_PATH 空，LD_LIBRARY_PATH 仅 driver 基础路径 ✓
**执行**：命令逐字执行，无偏差。自检 `test_scheme_tools.py` 38 tests OK；A `--window` 缺省=1（w1 轮内基线）48 case；B `--window 16`（w16 吞吐模式）48 case；C npu 锚点 12 case；均 `--repeat 2` iters=1000 默认。三组 manifest 全 passed。
**通过标准命中**：
- R3-G1 ✓：`Ran 38 tests` / `OK`，RC=0。
- R3-G2 ✓：三个 manifest（w1/w16/anchor）全 `status=="passed"`；108 case JSON 全 passed、correctness 全 true（脚本逐 case 核验，bad=0）；window 分档正确——w1 目录 48×window=1、w16 目录 48×window=16、anchor 12×window=1（防串组）✓。
- R3-G3 ✓（跨轮一致性，非门槛）：w1 cpu/hybrid 24 坐标 vs §R2 交付 summary 同坐标（cf0.5）偏差最大 14.77%（hybrid cards8 copy100），全部 ≤15%，未触发超限。逐坐标偏差见下表（观察节）。
**原始数据**：

`results/r3/w1/copy_scheme_timing_summary.md` 全文：

```
| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 0 | 69.195 | 69.195 | 0.000 |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 100 | 191.005 | 191.005 | 8.262 |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 300 | 272.334 | 272.334 | 17.344 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 0 | 74.827 | 77.288 | 0.000 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 100 | 205.370 | 208.145 | 15.335 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 300 | 303.942 | 305.154 | 31.102 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 0 | 92.351 | 99.582 | 0.000 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 100 | 246.993 | 267.213 | 25.744 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 300 | 361.316 | 371.806 | 52.872 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 0 | 114.162 | 134.178 | 0.000 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 100 | 236.409 | 248.794 | 53.384 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 300 | 356.267 | 382.240 | 106.944 |
| hybrid | 0 | 0.5 | overlap | 1 | 24 | 0 | 111.906 | 111.906 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 1 | 24 | 100 | 263.792 | 263.792 | 5.969 |
| hybrid | 0 | 0.5 | overlap | 1 | 24 | 300 | 277.943 | 277.943 | 17.001 |
| hybrid | 0 | 0.5 | overlap | 2 | 24 | 0 | 117.609 | 119.623 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 2 | 24 | 100 | 271.237 | 285.175 | 11.668 |
| hybrid | 0 | 0.5 | overlap | 2 | 24 | 300 | 317.671 | 326.270 | 29.776 |
| hybrid | 0 | 0.5 | overlap | 4 | 24 | 0 | 121.440 | 125.782 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 4 | 24 | 100 | 296.753 | 314.578 | 21.280 |
| hybrid | 0 | 0.5 | overlap | 4 | 24 | 300 | 399.800 | 422.604 | 47.729 |
| hybrid | 0 | 0.5 | overlap | 8 | 24 | 0 | 145.630 | 164.356 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 8 | 24 | 100 | 302.638 | 349.403 | 41.914 |
| hybrid | 0 | 0.5 | overlap | 8 | 24 | 300 | 419.553 | 453.436 | 90.441 |
```

`results/r3/w16/copy_scheme_timing_summary.md` 全文：

```
| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 0 | 5.053 | 5.053 | 0.000 |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 100 | 89.672 | 89.672 | 17.576 |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 300 | 202.924 | 202.924 | 23.326 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 0 | 5.216 | 5.330 | 0.000 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 100 | 99.417 | 107.567 | 31.948 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 300 | 199.888 | 200.237 | 47.259 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 0 | 5.941 | 6.626 | 0.000 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 100 | 123.758 | 137.662 | 51.195 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 300 | 290.081 | 324.430 | 67.380 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 0 | 6.561 | 7.084 | 0.000 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 100 | 92.090 | 108.910 | 138.021 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 300 | 263.169 | 297.314 | 151.735 |
| hybrid | 0 | 0.5 | overlap | 1 | 24 | 0 | 32.354 | 32.354 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 1 | 24 | 100 | 162.861 | 162.861 | 9.668 |
| hybrid | 0 | 0.5 | overlap | 1 | 24 | 300 | 177.072 | 177.072 | 26.674 |
| hybrid | 0 | 0.5 | overlap | 2 | 24 | 0 | 33.604 | 34.679 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 2 | 24 | 100 | 168.225 | 170.275 | 18.721 |
| hybrid | 0 | 0.5 | overlap | 2 | 24 | 300 | 246.809 | 260.858 | 38.478 |
| hybrid | 0 | 0.5 | overlap | 4 | 24 | 0 | 37.337 | 48.561 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 4 | 24 | 100 | 193.934 | 198.821 | 32.485 |
| hybrid | 0 | 0.5 | overlap | 4 | 24 | 300 | 359.362 | 377.229 | 52.657 |
| hybrid | 0 | 0.5 | overlap | 8 | 24 | 0 | 34.972 | 36.379 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 8 | 24 | 100 | 162.180 | 175.098 | 77.846 |
| hybrid | 0 | 0.5 | overlap | 8 | 24 | 300 | 275.195 | 319.800 | 144.464 |
```

`results/r3/anchor/copy_scheme_timing_summary.md` 全文：

```
| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| npu | 0 | 0.5 | overlap | 1 | 24 | 0 | 11.007 | 11.007 | 0.000 |
| npu | 0 | 0.5 | overlap | 1 | 24 | 300 | 138.970 | 138.970 | 33.987 |
| npu | 0 | 0.5 | overlap | 4 | 24 | 0 | 11.033 | 11.468 | 0.000 |
| npu | 0 | 0.5 | overlap | 4 | 24 | 300 | 256.536 | 278.526 | 76.696 |
| npu | 0 | 0.5 | overlap | 8 | 24 | 0 | 11.574 | 16.890 | 0.000 |
| npu | 0 | 0.5 | overlap | 8 | 24 | 300 | 222.595 | 238.419 | 170.740 |
```

三目录 `copy_scheme_run_manifest.json` 全文：

```json
w1: {"schema_version":2,"status":"passed","dtype":"c8","timestamp_utc":"2026-10-14T17:56:27.697103+00:00","visible_devices":"0,1,2,3,4,5,6,7","queue_depth":"default","case_files":[<48 files: cpu/hybrid × cards1,2,4,8 × copy0,100,300 × _r1,_r2>]}
w16: {"schema_version":2,"status":"passed","dtype":"c8","timestamp_utc":"2026-10-14T18:06:14.246201+00:00","visible_devices":"0,1,2,3,4,5,6,7","queue_depth":"default","case_files":[<48 files: 同 w1 命名>]}
anchor: {"schema_version":2,"status":"passed","dtype":"c8","timestamp_utc":"2026-10-14T18:15:57.596503+00:00","visible_devices":"0,1,2,3,4,5,6,7","queue_depth":"default","case_files":[<12 files: npu × cards1,4,8 × copy0,300 × _r1,_r2>]}
```

（manifest case_files 完整 48/48/12 清单见仓库 `results/r3/{w1,w16,anchor}/copy_scheme_run_manifest.json`，gitignore 不入库；文件名模式：w1/w16 为 `{cpu,hybrid}_cards{c}_bs24_copy{k}_rf0p0[_cf0p5_overlap]_r{r}.json`，anchor 为 `npu_cards{c}_bs24_copy{k}_rf0p0_r{r}.json`。）

4 个 case JSON 全文（看 phases 用）：

`results/r3/w1/cpu_cards1_bs24_copy100_rf0p0_r1.json`：

```json
{
  "schema_version": 2, "test": "a5_kvcache_copy_scheme_multiprocess", "status": "passed",
  "timestamp_utc": "2026-10-14T17:56:58.129522+00:00", "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1, "devices": [0], "same_seed": true,
  "config": {
    "dtype": "c8", "row_bytes": 656, "batch_size": 24, "source_len": 65536, "hbm_slots": 8192,
    "copy_min": 100, "copy_max": 100, "copy_cap": 16384, "warmup": 10, "iters": 1000, "seed": 7,
    "allow_non_a5": false, "scheme": "cpu", "run_frac": 0.0, "cpu_frac": 0.5, "hybrid_mode": "overlap",
    "cpu_threads": 8, "pretouch": false, "window": 1, "numa_nodes": ""
  },
  "summary": {"avg_us_mean": 181.7163899999999, "avg_us_max": 181.7163899999999,
    "avg_bandwidth": 8.664050612055417, "total_payload_bytes_per_iteration": 1574400,
    "copied_tokens_sum_per_iteration": 2400, "all_correct": true},
  "per_device": [
    {
      "schema_version": 2, "test": "a5_kvcache_copy_scheme_singlecard", "status": "passed",
      "timestamp_utc": "2026-10-14T17:56:55.335847+00:00", "device_count": 1,
      "config": {
        "device": "npu:0", "device_name": "Ascend950DT_9572", "dtype": "c8", "row_bytes": 656,
        "batch_size": 24, "source_len": 65536, "hbm_slots": 8192, "copy_min": 100, "copy_max": 100,
        "copy_cap": 16384, "warmup": 10, "iters": 1000, "seed": 7, "scheme": "cpu", "run_frac": 0.0,
        "cpu_frac": 0.5, "hybrid_mode": "overlap", "cpu_threads": 8, "pretouch": false,
        "staging_pinned": true, "window": 1, "queue_depth": 8
      },
      "workload": {"copy_counts": [100×24], "copied_tokens": 2400, "cpu_tokens": 0,
        "payload_bytes_per_iteration": 1574400},
      "correctness": {"data_exact": true, "guard_unchanged": true},
      "summary": {"cards": 1, "batch_size": 24, "copy_count": 100,
        "avg_us_mean": 181.7163899999999, "avg_us_max": 181.7163899999999,
        "avg_bandwidth": 8.664050612055417},
      "performance": {"timer": "perf_counter", "avg_us": 181.7163899999999, "avg_us_host_synced": null,
        "latency_us": {"mean": 181.7163899999999, "p50": 179.45, "p90": 196.57, "p99": 229.67,
          "min": 154.38, "max": 647.53, "n": 1000},
        "window": 1,
        "phases": {"cpu_gather_us": 46.09559999999996, "device_wall_us": 135.6207900000002,
          "device_event_us": 76.81902299076319, "device_overhead_us": 58.801767009237025}},
      "rank": 0, "logical_device_index": 0
    }
  ]
}
```

`results/r3/w16/cpu_cards1_bs24_copy100_rf0p0_r1.json`：

```json
{
  "schema_version": 2, "test": "a5_kvcache_copy_scheme_multiprocess", "status": "passed",
  "timestamp_utc": "2026-10-14T18:06:47.565361+00:00", "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1, "devices": [0], "same_seed": true,
  "config": {
    "dtype": "c8", "row_bytes": 656, "batch_size": 24, "source_len": 65536, "hbm_slots": 8192,
    "copy_min": 100, "copy_max": 100, "copy_cap": 16384, "warmup": 10, "iters": 1000, "seed": 7,
    "allow_non_a5": false, "scheme": "cpu", "run_frac": 0.0, "cpu_frac": 0.5, "hybrid_mode": "overlap",
    "cpu_threads": 8, "pretouch": false, "window": 16, "numa_nodes": ""
  },
  "summary": {"avg_us_mean": 86.71812000000014, "avg_us_max": 86.71812000000014,
    "avg_bandwidth": 18.155375139590173, "total_payload_bytes_per_iteration": 1574400,
    "copied_tokens_sum_per_iteration": 2400, "all_correct": true},
  "per_device": [
    {
      "schema_version": 2, "test": "a5_kvcache_copy_scheme_singlecard", "status": "passed",
      "timestamp_utc": "2026-10-14T18:06:44.721865+00:00", "device_count": 1,
      "config": {
        "device": "npu:0", "device_name": "Ascend950DT_9572", "dtype": "c8", "row_bytes": 656,
        "batch_size": 24, "source_len": 65536, "hbm_slots": 8192, "copy_min": 100, "copy_max": 100,
        "copy_cap": 16384, "warmup": 10, "iters": 1000, "seed": 7, "scheme": "cpu", "run_frac": 0.0,
        "cpu_frac": 0.5, "hybrid_mode": "overlap", "cpu_threads": 8, "pretouch": false,
        "staging_pinned": true, "window": 16, "queue_depth": 8
      },
      "workload": {"copy_counts": [100×24], "copied_tokens": 2400, "cpu_tokens": 0,
        "payload_bytes_per_iteration": 1574400},
      "correctness": {"data_exact": true, "guard_unchanged": true},
      "summary": {"cards": 1, "batch_size": 24, "copy_count": 100,
        "avg_us_mean": 86.71812000000014, "avg_us_max": 86.71812000000014,
        "avg_bandwidth": 18.155375139590173},
      "performance": {"timer": "perf_counter", "avg_us": 86.71812000000014, "avg_us_host_synced": null,
        "latency_us": {"mean": 86.71811999999981, "p50": 86.75125, "p90": 91.89875, "p99": 135.565,
          "min": 78.430625, "max": 135.565, "n": 1000},
        "window": 16,
        "phases": {"cpu_gather_us": 28.264360000000003, "device_wall_us": 58.45375999999999,
          "device_event_us": 52.43560868501663, "device_overhead_us": 6.018151314983355}},
      "rank": 0, "logical_device_index": 0
    }
  ]
}
```

`results/r3/w1/hybrid_cards1_bs24_copy100_rf0p0_cf0p5_overlap_r1.json`：

```json
{
  "schema_version": 2, "test": "a5_kvcache_copy_scheme_multiprocess", "status": "passed",
  "timestamp_utc": "2026-10-14T18:01:44.560236+00:00", "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1, "devices": [0], "same_seed": true,
  "config": {
    "dtype": "c8", "row_bytes": 656, "batch_size": 24, "source_len": 65536, "hbm_slots": 8192,
    "copy_min": 100, "copy_max": 100, "copy_cap": 16384, "warmup": 10, "iters": 1000, "seed": 7,
    "allow_non_a5": false, "scheme": "hybrid", "run_frac": 0.0, "cpu_frac": 0.5, "hybrid_mode": "overlap",
    "cpu_threads": 8, "pretouch": false, "window": 1, "numa_nodes": ""
  },
  "summary": {"avg_us_mean": 266.2583300000001, "avg_us_max": 266.2583300000001,
    "avg_bandwidth": 5.913054438522164, "total_payload_bytes_per_iteration": 1574400,
    "copied_tokens_sum_per_iteration": 2400, "all_correct": true},
  "per_device": [
    {
      "schema_version": 2, "test": "a5_kvcache_copy_scheme_singlecard", "status": "passed",
      "timestamp_utc": "2026-10-14T18:01:41.553346+00:00", "device_count": 1,
      "config": {
        "device": "npu:0", "device_name": "Ascend950DT_9572", "dtype": "c8", "row_bytes": 656,
        "batch_size": 24, "source_len": 65536, "hbm_slots": 8192, "copy_min": 100, "copy_max": 100,
        "copy_cap": 16384, "warmup": 10, "iters": 1000, "seed": 7, "scheme": "hybrid", "run_frac": 0.0,
        "cpu_frac": 0.5, "hybrid_mode": "overlap", "cpu_threads": 8, "pretouch": false,
        "staging_pinned": true, "window": 1, "queue_depth": 8
      },
      "workload": {"copy_counts": [100×24], "copied_tokens": 2400, "cpu_tokens": 1200,
        "payload_bytes_per_iteration": 1574400},
      "correctness": {"data_exact": true, "guard_unchanged": true, "zero_count_unchanged": true,
        "first_fill_capacity": true, "metadata_unchanged": true},
      "summary": {"cards": 1, "batch_size": 24, "copy_count": 100,
        "avg_us_mean": 266.2583300000001, "avg_us_max": 266.2583300000001,
        "avg_bandwidth": 5.913054438522164},
      "performance": {"timer": "perf_counter", "avg_us": 266.2583300000001, "avg_us_host_synced": null,
        "latency_us": {"mean": 266.2583300000002, "p50": 264.44, "p90": 280.36, "p99": 311.09,
          "min": 220.4, "max": 683.04, "n": 1000},
        "window": 1,
        "phases": {"launch_to_gather_done_us": 183.00110999999995, "h2d_scatter_tail_us": 83.25722000000016,
          "kernel_event_us": 182.72431115806103}},
      "rank": 0, "logical_device_index": 0
    }
  ]
}
```

`results/r3/w16/hybrid_cards1_bs24_copy100_rf0p0_cf0p5_overlap_r1.json`：

```json
{
  "schema_version": 2, "test": "a5_kvcache_copy_scheme_multiprocess", "status": "passed",
  "timestamp_utc": "2026-10-14T18:11:31.452317+00:00", "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1, "devices": [0], "same_seed": true,
  "config": {
    "dtype": "c8", "row_bytes": 656, "batch_size": 24, "source_len": 65536, "hbm_slots": 8192,
    "copy_min": 100, "copy_max": 100, "copy_cap": 16384, "warmup": 10, "iters": 1000, "seed": 7,
    "allow_non_a5": false, "scheme": "hybrid", "run_frac": 0.0, "cpu_frac": 0.5, "hybrid_mode": "overlap",
    "cpu_threads": 8, "pretouch": false, "window": 16, "numa_nodes": ""
  },
  "summary": {"avg_us_mean": 161.67691999999928, "avg_us_max": 161.67691999999928,
    "avg_bandwidth": 9.737939094831884, "total_payload_bytes_per_iteration": 1574400,
    "copied_tokens_sum_per_iteration": 2400, "all_correct": true},
  "per_device": [
    {
      "schema_version": 2, "test": "a5_kvcache_copy_scheme_singlecard", "status": "passed",
      "timestamp_utc": "2026-10-14T18:11:28.333248+00:00", "device_count": 1,
      "config": {
        "device": "npu:0", "device_name": "Ascend950DT_9572", "dtype": "c8", "row_bytes": 656,
        "batch_size": 24, "source_len": 65536, "hbm_slots": 8192, "copy_min": 100, "copy_max": 100,
        "copy_cap": 16384, "warmup": 10, "iters": 1000, "seed": 7, "scheme": "hybrid", "run_frac": 0.0,
        "cpu_frac": 0.5, "hybrid_mode": "overlap", "cpu_threads": 8, "pretouch": false,
        "staging_pinned": true, "window": 16, "queue_depth": 8
      },
      "workload": {"copy_counts": [100×24], "copied_tokens": 2400, "cpu_tokens": 1200,
        "payload_bytes_per_iteration": 1574400},
      "correctness": {"data_exact": true, "guard_unchanged": true, "zero_count_unchanged": true,
        "first_fill_capacity": true, "metadata_unchanged": true},
      "summary": {"cards": 1, "batch_size": 24, "copy_count": 100,
        "avg_us_mean": 161.67691999999928, "avg_us_max": 161.67691999999928,
        "avg_bandwidth": 9.737939094831884},
      "performance": {"timer": "perf_counter", "avg_us": 161.67691999999928, "avg_us_host_synced": null,
        "latency_us": {"mean": 161.67691999999892, "p50": 160.945625, "p90": 165.375625, "p99": 194.01625,
          "min": 153.176875, "max": 194.01625, "n": 1000},
        "window": 16,
        "phases": {"launch_to_gather_done_us": 156.25639999999999, "h2d_scatter_tail_us": 5.420520000000001,
          "kernel_event_us": 156.0201358795166}},
      "rank": 0, "logical_device_index": 0
    }
  ]
}
```

**结果文件**：宿主机 21 `/home/h2d_test/copy-scheme-bench/results/r3/{w1,w16,anchor}/`（各含 48/48/12 case JSON + manifest + summary + timing_summary.csv/md + 逐 case .log）；`results/` gitignore 未提交入库。
**观察**（只事实、不结论）：
- 主键对比（同坐标 avg_us_mean/带宽，repeat 折叠值，均 cards1/bs24/copy100 起算）：
  - cpu w1→w16：copy100 181.716→86.718µs（8.664→18.155 GB/s）；copy300 272.334→202.924µs（17.344→23.326 GB/s）；copy0 69.195→5.053µs。
  - cpu w16 带宽全坐标 > w1（cards8 copy100 53.384→138.021、copy300 106.944→151.735 GB/s）。
  - hybrid w1→w16：copy100 263.792→162.861µs（5.969→9.668 GB/s）；copy300 277.943→177.072µs（17.001→26.674 GB/s）；copy0 111.906→32.354µs。
- phases（cpu copy100 cards1，看 host 开销口径）：w1 cpu_gather 46.096µs + device_wall 135.621µs（其中 device_event 76.819、device_overhead 58.802）；w16 cpu_gather 28.264µs + device_wall 58.454µs（device_event 52.436、device_overhead 6.018）。未归类 host 开销（= avg_us − cpu_gather − device_wall）：w1 ≈ 0.000µs（0.0%）、w16 ≈ 0.000µs（0.0%）。
- hybrid phases（copy100 cards1）：w1 launch_to_gather_done 183.001µs + h2d_scatter_tail 83.257µs；w16 156.256µs + 5.421µs。
- R3-G3 逐坐标偏差（w1 vs §R2 cf0.5，%）：cpu cards1 -3.60/0.17/4.71、cards2 0.79/-2.75/11.18、cards4 8.28/13.42/5.17、cards8 -4.73/-1.28/3.30（copy0/100/300）；hybrid cards1 0.01/8.45/2.11、cards2 -2.57/6.77/-7.75、cards4 -1.69/-3.49/-5.77、cards8 -4.77/14.77/5.24。最大 14.77%。
- npu 锚点（同轮）：copy300 cards1 33.987/cards4 76.696/cards8 170.740 GB/s；copy0 11.0-11.6µs。
**异常**：无。

### 判读（§R3，2026-10-15，蓝区）

对照 §R3「判读预案」（派单时写死）逐条裁决（除注明外均为绿区**实测值**，
repeat 折叠后均值）：

**门槛**：R3-G1 ✓（38 项 OK）/ R3-G2 ✓（108 case 全 passed、correctness 全
true、window 分档正确）/ R3-G3 ✓（w1 对 R2 同坐标最大偏差 14.77% ≤15%）。

**口径修正（蓝区自我纠偏）**：§R2 判读备注的相位映射 `h2d_scatter_us ≡
device_wall_us` 不准确。R2 数据的数值证据给出正确映射：`h2d_scatter_us
(75.6) ≈ device_event_us (76.8)`（同坐标 w1，差 1.6%），`R2 未归类开销
(65.4) ≈ device_overhead_us (58.8)`（同一量级）——旧口径的「未归类」
主体是逐迭代同步等待，新口径已并入 device_wall 并以 device_overhead
单列（实测值互洽，非口径游戏）。

**裁决 1：host 压减有效（写死判据命中，超预期）**

- 判据「w16 未归类 host 开销占比 <10%」：w16 cpu cards1 copy100 的
  device_overhead=6.0µs，占 avg 86.7µs 的 **6.9% < 10%** ✓（w1 为
  58.8/181.7=32.4%）。
- copy0 纯固定开销（实测）：cpu 69.2/74.8/92.4/114.2µs（w1，cards1/2/4/8）
  → **5.1/5.2/5.9/6.6µs（w16）**，压缩 ~94%，已低于 npu launch 量级（~11µs）。
- 附带效应：gather 相位 46.1→28.3µs（w1→w16，同坐标）——去掉交错同步后
  host 侧 gather 本身也提速 ~39%（实测值；机制推测为线程调度/缓存连续性，
  标注为**推测**）。
- 延迟分布健康：w16 p99/p50=1.56（cpu copy100 cards1），无长尾恶化。

**裁决 2：S1 翻正未达成，但差距收敛到 0.88~0.89x**

- 写死判据「w16 cpu ≥ 同轮 npu 锚点（copy300, cards4/8）」：cards4
  67.4 < 76.7 GB/s（0.88x）；cards8 151.7 < 170.7 GB/s（0.89x）⇒ **未翻正**。
- 注意 cards4 锚点本轮 76.7 vs R2 65.7 vs R1 82.0 GB/s——cards4 档连续
  两轮漂移，该坐标证据弱；cards8 锚点稳定（168.5→170.7）。
- 趋势（实测）：w1→w16 后 cpu/npu 比从 0.53~0.84x 收敛到 0.88~0.89x；
  剩余差距主要在 device_event（H2D+scatter 实传段，52.4µs vs npu kernel
  全程 ~48.5µs/同 tokens 档——cpu 路径的 PCIe 大包 DMA + 设备侧 scatter
  两次写 vs kernel 直写一次，结构性多一遍）。

**裁决 3：S2 重开候选成立（cards4/8）**

- 写死判据「w16 hybrid < 同坐标 min(npu, w16 cpu)」（copy300）：cards1
  26.7 > 23.3 ✗；cards4 52.7 < 67.4 ✓；cards8 144.5 < 151.7 ✓ ⇒
  **候选成立（2/3 坐标）**，且 hybrid w16 的 h2d_scatter_tail 相位仅
  5.4µs（cards1 copy100）——overlap 在窗口化下真正藏住了 CPU 段。
- 按预案「下轮扫细 frac」执行，见 §R4。

**下一步**：R4 = hybrid 细 frac 扫描（w16，找最优分流点+能否过 npu）
+ pretouch/THP 查 w16 cpu gather 相位（28.3µs）的缺页/TLB 成分。
队列深度（npu 侧余量）顺延为 R5 候选。

---

## §R2-旧 派单：修复后重跑主矩阵（2026-10-15，蓝区）

### 目标

拿到 npu / cpu / hybrid 同轮完整的 60 case 主矩阵，支撑 S1/S2 裁决
（判据沿用 §R1「判读预案」，未移动）。

### 背景（蓝区已做的修复）

R1 崩溃根因：`copy=0` 时 staging 未分配但 `cpu_gather` 无条件使用（NoneType）。
修复：`cpu_gather` / `cpu_device_pass` 对本方案份额为空（`numel()==0`）时直接
返回；新增 stdlib 回归测试 `test_copy_zero_rows_are_empty_everywhere`。
蓝图仓不需要任何改动，**不需要重新 clone / apply / build**。

### 前置核验

1. 本仓 `git pull --ff-only` 后 `git log --oneline -1` 标题为
   "R2: 修复 cpu/hybrid 空份额崩溃 + §R1 判读 + §R2 派单"。
2. 蓝图仓保持 R1 状态：`git -C ../nanovllm-scatter_copy log --oneline -1` = `bb062d2`；
   工作区两个 M 文件仍在；`QUEUE_DEPTH = 8`；`_custom_opp_c8/` 构建产物仍在。
3. 环境变量无残留（同 §R1 前置核验第 5 条）。

### 执行命令

逐字执行（工作目录任意，脚本自定位；回归结果目录相对 cwd 解析）：

```bash
cd /home/h2d_test/copy-scheme-bench
git pull --ff-only && git log --oneline -1
cd tests && python3 test_scheme_tools.py && cd ..
# 定点回归：copy=0 在 cpu/hybrid 下必须不再崩溃（4 个 case）
bash run_scheme_sweep.sh --cards 1 --batch-size 24 --copy-count 0 100 \
  --schemes cpu hybrid --cpu-fracs 0.5 --iters 200 \
  --results-dir results/r2_regression
# 全量主矩阵（60 case；npu 12 坐标兼作跨轮一致性检查）
bash run_scheme_sweep.sh
```

### 通过标准

- R2-G1：自检末两行 `Ran 22 tests` / `OK`。
- R2-G2：回归 manifest `status=="passed"`；4 个 case JSON 全部 passed 且
  correctness 全 true；`cpu_cards1_bs24_copy0_rf0p0.log` 无 `AttributeError`。
- R2-G3：主矩阵 manifest `status=="passed"`，`copy_scheme_summary.json`
  `case_count==60`，每个 case JSON correctness 全 true。
- R2-G4（跨轮一致性，非验收门槛）：npu 12 坐标与同坐标 R1 值（见 §R1 交付
  附表）偏差 ≤15%；超出则原样回传并注明，不自行重跑调参。

### 回传格式

同 §R1：AGENTS.md 交付模板 + `copy_scheme_timing_summary.md` 全文 + manifest
全文 + 回归 4 个 JSON 全文；任何一步失败：日志末 30 行原文，停止后续步骤照常交付。

### 判读预案（派单时写死）

- S1/S2 判据沿用 §R1「判读预案」，逐字不变。
- R2-G2 失败 ⇒ 修复不完整，蓝区继续修；绿区只回传日志，不改代码。
- R2-G4 失败 ⇒ 环境漂移：npu 基线跨轮不可比，一切对比以 R2 轮内坐标为准。
- 补充裁决（由 R1 冒烟信号引出，写死）：若 `cpu` 全坐标 < `npu`，且
  `phases` 中既非 `cpu_gather_us` 也非 `h2d_scatter_us` 的未归类 host 开销
  （= avg_us − 两相位之和）占 `avg_us` >30% ⇒ 记 **S1 阴性（host 开销主导）**，
  下一步是先压 host 开销（减少 launch 次数/图捕获）再复试一次，
  而不是直接判 CPU 路径死刑。

### 交付（§R2，2026-10-15，绿区）

**执行环境**：机器 work21（141.61.33.21）openEuler aarch64；8× Ascend950DT_9572（可见设备 0-7）；宿主 root；CANN 9.2.0（/usr/local/Ascend/ascend-toolkit/latest）；时间 2026-10-14T16:5x–17:0xZ（回归 17:04Z、主矩阵 17:05Z 起）。
**前置核验**：逐条实际值——
1. 本仓 `git log --oneline -1` = `2d77dab R2: 修复 cpu/hybrid 空份额崩溃 + §R1 判读 + §R2 派单` ✓
2. 蓝图仓 `git -C ../nanovllm-scatter_copy log --oneline -1` = `bb062d2` ✓；工作区两 M 文件仍在 ✓；`QUEUE_DEPTH = 8` 计数 1 ✓；`_custom_opp_c8/` 构建产物（_custom_opp_c8/vendors 等）仍在 ✓
3. 环境变量无残留：四变量 grep 无匹配（RC=1）✓
**执行**：命令逐字执行，无偏差。`git pull --ff-only` 已是最新 `2d77dab`；自检 `test_scheme_tools.py` 22 tests OK；定点回归 `run_scheme_sweep.sh --cards 1 --batch-size 24 --copy-count 0 100 --schemes cpu hybrid --cpu-fracs 0.5 --iters 200 --results-dir results/r2_regression` 4 case 全 passed；全量主矩阵 `bash run_scheme_sweep.sh`（iters=1000 默认）60 case 全 passed。
**通过标准命中**：
- R2-G1 ✓：`Ran 22 tests` / `OK`，RC=0。
- R2-G2 ✓：回归 manifest `status=="passed"`；4 case JSON 全部 passed 且 correctness 全 true（cpu 两 case 合法字段集 {data_exact, guard_unchanged} 全 true；hybrid 两 case 5 字段全 true）；`cpu_cards1_bs24_copy0_rf0p0.log` 无 `AttributeError`。
- R2-G3 ✓：主矩阵 manifest `status=="passed"`；`copy_scheme_summary.json` `case_count==60`；60 case JSON 全部 passed、correctness 全 true（bad cases 0）。
- R2-G4 ✗（环境漂移，非验收门槛，未自行重跑调参）：npu 12 坐标对 §R1 交付附表偏差——cards1 copy100 32.493（0.48%）、copy300 33.997（0.16%）；cards2 63.563（2.59%）、65.515（3.72%）；cards4 **copy100 66.662（25.01%）**、**copy300 65.714（19.89%）**；cards8 179.363（0.41%）、168.492（3.70%）；copy0 全 0。cards4 档超 15% 阈值 ⇒ 按预案记环境漂移，npu 基线跨轮不可比，一切对比以 R2 轮内坐标为准。
**原始数据**：

`copy_scheme_timing_summary.md` 全文：

```
| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 0 | 71.781 | 71.781 | 0.000 |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 100 | 190.685 | 190.685 | 8.257 |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 300 | 260.077 | 260.077 | 18.161 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 0 | 74.243 | 76.745 | 0.000 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 100 | 211.170 | 234.148 | 15.090 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 300 | 273.383 | 280.955 | 34.580 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 0 | 85.293 | 94.960 | 0.000 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 100 | 217.762 | 240.631 | 29.155 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 300 | 343.550 | 359.708 | 55.117 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 0 | 119.826 | 134.134 | 0.000 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 100 | 239.464 | 257.474 | 52.732 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 300 | 344.895 | 385.145 | 109.785 |
| hybrid | 0 | 0.25 | overlap | 1 | 24 | 0 | 107.145 | 107.145 | 0.000 |
| hybrid | 0 | 0.25 | overlap | 1 | 24 | 100 | 246.618 | 246.618 | 6.384 |
| hybrid | 0 | 0.25 | overlap | 1 | 24 | 300 | 246.763 | 246.763 | 19.141 |
| hybrid | 0 | 0.25 | overlap | 2 | 24 | 0 | 120.630 | 120.822 | 0.000 |
| hybrid | 0 | 0.25 | overlap | 2 | 24 | 100 | 234.544 | 247.660 | 13.467 |
| hybrid | 0 | 0.25 | overlap | 2 | 24 | 300 | 293.843 | 303.706 | 32.184 |
| hybrid | 0 | 0.25 | overlap | 4 | 24 | 0 | 122.324 | 124.675 | 0.000 |
| hybrid | 0 | 0.25 | overlap | 4 | 24 | 100 | 282.981 | 285.975 | 22.257 |
| hybrid | 0 | 0.25 | overlap | 4 | 24 | 300 | 336.862 | 374.488 | 57.278 |
| hybrid | 0 | 0.25 | overlap | 8 | 24 | 0 | 136.938 | 145.796 | 0.000 |
| hybrid | 0 | 0.25 | overlap | 8 | 24 | 100 | 269.347 | 304.514 | 46.940 |
| hybrid | 0 | 0.25 | overlap | 8 | 24 | 300 | 395.060 | 417.433 | 95.921 |
| hybrid | 0 | 0.5 | overlap | 1 | 24 | 0 | 111.891 | 111.891 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 1 | 24 | 100 | 243.247 | 243.247 | 6.472 |
| hybrid | 0 | 0.5 | overlap | 1 | 24 | 300 | 272.193 | 272.193 | 17.352 |
| hybrid | 0 | 0.5 | overlap | 2 | 24 | 0 | 120.706 | 121.577 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 2 | 24 | 100 | 254.040 | 262.082 | 12.407 |
| hybrid | 0 | 0.5 | overlap | 2 | 24 | 300 | 344.361 | 360.606 | 27.493 |
| hybrid | 0 | 0.5 | overlap | 4 | 24 | 0 | 123.525 | 132.205 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 4 | 24 | 100 | 307.483 | 315.025 | 20.495 |
| hybrid | 0 | 0.5 | overlap | 4 | 24 | 300 | 424.295 | 476.019 | 44.742 |
| hybrid | 0 | 0.5 | overlap | 8 | 24 | 0 | 152.927 | 184.405 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 8 | 24 | 100 | 263.691 | 279.450 | 47.812 |
| hybrid | 0 | 0.5 | overlap | 8 | 24 | 300 | 398.678 | 423.074 | 95.088 |
| hybrid | 0 | 0.75 | overlap | 1 | 24 | 0 | 116.221 | 116.221 | 0.000 |
| hybrid | 0 | 0.75 | overlap | 1 | 24 | 100 | 254.717 | 254.717 | 6.181 |
| hybrid | 0 | 0.75 | overlap | 1 | 24 | 300 | 259.914 | 259.914 | 18.172 |
| hybrid | 0 | 0.75 | overlap | 2 | 24 | 0 | 120.895 | 126.559 | 0.000 |
| hybrid | 0 | 0.75 | overlap | 2 | 24 | 100 | 259.088 | 267.802 | 12.167 |
| hybrid | 0 | 0.75 | overlap | 2 | 24 | 300 | 338.421 | 340.603 | 27.914 |
| hybrid | 0 | 0.75 | overlap | 4 | 24 | 0 | 142.223 | 171.494 | 0.000 |
| hybrid | 0 | 0.75 | overlap | 4 | 24 | 100 | 274.167 | 289.801 | 23.037 |
| hybrid | 0 | 0.75 | overlap | 4 | 24 | 300 | 425.837 | 444.694 | 44.402 |
| hybrid | 0 | 0.75 | overlap | 8 | 24 | 0 | 151.150 | 164.536 | 0.000 |
| hybrid | 0 | 0.75 | overlap | 8 | 24 | 100 | 275.477 | 303.979 | 45.859 |
| hybrid | 0 | 0.75 | overlap | 8 | 24 | 300 | 406.986 | 445.485 | 93.451 |
| npu | 0 | 0.5 | overlap | 1 | 24 | 0 | 11.183 | 11.183 | 0.000 |
| npu | 0 | 0.5 | overlap | 1 | 24 | 100 | 48.454 | 48.454 | 32.493 |
| npu | 0 | 0.5 | overlap | 1 | 24 | 300 | 138.930 | 138.930 | 33.997 |
| npu | 0 | 0.5 | overlap | 2 | 24 | 0 | 9.720 | 11.436 | 0.000 |
| npu | 0 | 0.5 | overlap | 2 | 24 | 100 | 49.538 | 49.543 | 63.563 |
| npu | 0 | 0.5 | overlap | 2 | 24 | 300 | 144.189 | 144.742 | 65.515 |
| npu | 0 | 0.5 | overlap | 4 | 24 | 0 | 10.930 | 11.591 | 0.000 |
| npu | 0 | 0.5 | overlap | 4 | 24 | 100 | 97.069 | 105.666 | 66.662 |
| npu | 0 | 0.5 | overlap | 4 | 24 | 300 | 296.185 | 323.833 | 65.714 |
| npu | 0 | 0.5 | overlap | 8 | 24 | 0 | 10.876 | 11.952 | 0.000 |
| npu | 0 | 0.5 | overlap | 8 | 24 | 100 | 70.257 | 72.149 | 179.363 |
| npu | 0 | 0.5 | overlap | 8 | 24 | 300 | 224.450 | 236.431 | 168.492 |
```

主矩阵 `copy_scheme_run_manifest.json` 全文：

```json
{
  "schema_version": 2,
  "status": "passed",
  "dtype": "c8",
  "timestamp_utc": "2026-10-14T17:05:41.312631+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "queue_depth": "default",
  "case_files": [
    "npu_cards1_bs24_copy0_rf0p0.json",
    "npu_cards1_bs24_copy100_rf0p0.json",
    "npu_cards1_bs24_copy300_rf0p0.json",
    "npu_cards2_bs24_copy0_rf0p0.json",
    "npu_cards2_bs24_copy100_rf0p0.json",
    "npu_cards2_bs24_copy300_rf0p0.json",
    "npu_cards4_bs24_copy0_rf0p0.json",
    "npu_cards4_bs24_copy100_rf0p0.json",
    "npu_cards4_bs24_copy300_rf0p0.json",
    "npu_cards8_bs24_copy0_rf0p0.json",
    "npu_cards8_bs24_copy100_rf0p0.json",
    "npu_cards8_bs24_copy300_rf0p0.json",
    "cpu_cards1_bs24_copy0_rf0p0.json",
    "cpu_cards1_bs24_copy100_rf0p0.json",
    "cpu_cards1_bs24_copy300_rf0p0.json",
    "cpu_cards2_bs24_copy0_rf0p0.json",
    "cpu_cards2_bs24_copy100_rf0p0.json",
    "cpu_cards2_bs24_copy300_rf0p0.json",
    "cpu_cards4_bs24_copy0_rf0p0.json",
    "cpu_cards4_bs24_copy100_rf0p0.json",
    "cpu_cards4_bs24_copy300_rf0p0.json",
    "cpu_cards8_bs24_copy0_rf0p0.json",
    "cpu_cards8_bs24_copy100_rf0p0.json",
    "cpu_cards8_bs24_copy300_rf0p0.json",
    "hybrid_cards1_bs24_copy0_rf0p0_cf0p25_overlap.json",
    "hybrid_cards1_bs24_copy100_rf0p0_cf0p25_overlap.json",
    "hybrid_cards1_bs24_copy300_rf0p0_cf0p25_overlap.json",
    "hybrid_cards2_bs24_copy0_rf0p0_cf0p25_overlap.json",
    "hybrid_cards2_bs24_copy100_rf0p0_cf0p25_overlap.json",
    "hybrid_cards2_bs24_copy300_rf0p0_cf0p25_overlap.json",
    "hybrid_cards4_bs24_copy0_rf0p0_cf0p25_overlap.json",
    "hybrid_cards4_bs24_copy100_rf0p0_cf0p25_overlap.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p25_overlap.json",
    "hybrid_cards8_bs24_copy0_rf0p0_cf0p25_overlap.json",
    "hybrid_cards8_bs24_copy100_rf0p0_cf0p25_overlap.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p25_overlap.json",
    "hybrid_cards1_bs24_copy0_rf0p0_cf0p5_overlap.json",
    "hybrid_cards1_bs24_copy100_rf0p0_cf0p5_overlap.json",
    "hybrid_cards1_bs24_copy300_rf0p0_cf0p5_overlap.json",
    "hybrid_cards2_bs24_copy0_rf0p0_cf0p5_overlap.json",
    "hybrid_cards2_bs24_copy100_rf0p0_cf0p5_overlap.json",
    "hybrid_cards2_bs24_copy300_rf0p0_cf0p5_overlap.json",
    "hybrid_cards4_bs24_copy0_rf0p0_cf0p5_overlap.json",
    "hybrid_cards4_bs24_copy100_rf0p0_cf0p5_overlap.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p5_overlap.json",
    "hybrid_cards8_bs24_copy0_rf0p0_cf0p5_overlap.json",
    "hybrid_cards8_bs24_copy100_rf0p0_cf0p5_overlap.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p5_overlap.json",
    "hybrid_cards1_bs24_copy0_rf0p0_cf0p75_overlap.json",
    "hybrid_cards1_bs24_copy100_rf0p0_cf0p75_overlap.json",
    "hybrid_cards1_bs24_copy300_rf0p0_cf0p75_overlap.json",
    "hybrid_cards2_bs24_copy0_rf0p0_cf0p75_overlap.json",
    "hybrid_cards2_bs24_copy100_rf0p0_cf0p75_overlap.json",
    "hybrid_cards2_bs24_copy300_rf0p0_cf0p75_overlap.json",
    "hybrid_cards4_bs24_copy0_rf0p0_cf0p75_overlap.json",
    "hybrid_cards4_bs24_copy100_rf0p0_cf0p75_overlap.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p75_overlap.json",
    "hybrid_cards8_bs24_copy0_rf0p0_cf0p75_overlap.json",
    "hybrid_cards8_bs24_copy100_rf0p0_cf0p75_overlap.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p75_overlap.json"
  ]
}
```

回归 4 case JSON 全文：

`results/r2_regression/cpu_cards1_bs24_copy0_rf0p0.json`：

```json
{
  "schema_version": 2, "test": "a5_kvcache_copy_scheme_multiprocess", "status": "passed",
  "timestamp_utc": "2026-10-14T17:04:10.182857+00:00", "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1, "devices": [0], "same_seed": true,
  "config": {
    "dtype": "c8", "row_bytes": 656, "batch_size": 24, "source_len": 65536, "hbm_slots": 8192,
    "copy_min": 0, "copy_max": 0, "copy_cap": 16384, "warmup": 10, "iters": 200, "seed": 7,
    "allow_non_a5": false, "scheme": "cpu", "run_frac": 0.0, "cpu_frac": 0.5, "hybrid_mode": "overlap",
    "cpu_threads": 8, "pretouch": false, "numa_nodes": ""
  },
  "summary": {"avg_us_mean": 68.50475, "avg_us_max": 68.50475, "avg_bandwidth": 0.0,
    "total_payload_bytes_per_iteration": 0, "copied_tokens_sum_per_iteration": 0, "all_correct": true},
  "per_device": [
    {
      "schema_version": 2, "test": "a5_kvcache_copy_scheme_singlecard", "status": "passed",
      "timestamp_utc": "2026-10-14T17:04:08.166364+00:00", "device_count": 1,
      "config": {
        "device": "npu:0", "device_name": "Ascend950DT_9572", "dtype": "c8", "row_bytes": 656,
        "batch_size": 24, "source_len": 65536, "hbm_slots": 8192, "copy_min": 0, "copy_max": 0,
        "copy_cap": 16384, "warmup": 10, "iters": 200, "seed": 7, "scheme": "cpu", "run_frac": 0.0,
        "cpu_frac": 0.5, "hybrid_mode": "overlap", "cpu_threads": 8, "pretouch": false,
        "staging_pinned": false, "queue_depth": 8
      },
      "workload": {"copy_counts": [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        "copied_tokens": 0, "cpu_tokens": 0, "payload_bytes_per_iteration": 0},
      "correctness": {"data_exact": true, "guard_unchanged": true},
      "summary": {"cards": 1, "batch_size": 24, "copy_count": 0,
        "avg_us_mean": 68.50475, "avg_us_max": 68.50475, "avg_bandwidth": 0.0},
      "performance": {"timer": "perf_counter", "avg_us": 68.50475, "avg_us_host_synced": null,
        "phases": {"cpu_gather_us": 0.2672, "h2d_scatter_us": 11.325885022524744}},
      "rank": 0, "logical_device_index": 0
    }
  ]
}
```

`results/r2_regression/cpu_cards1_bs24_copy100_rf0p0.json`：

```json
{
  "schema_version": 2, "test": "a5_kvcache_copy_scheme_multiprocess", "status": "passed",
  "timestamp_utc": "2026-10-14T17:04:21.608988+00:00", "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1, "devices": [0], "same_seed": true,
  "config": {
    "dtype": "c8", "row_bytes": 656, "batch_size": 24, "source_len": 65536, "hbm_slots": 8192,
    "copy_min": 100, "copy_max": 100, "copy_cap": 16384, "warmup": 10, "iters": 200, "seed": 7,
    "allow_non_a5": false, "scheme": "cpu", "run_frac": 0.0, "cpu_frac": 0.5, "hybrid_mode": "overlap",
    "cpu_threads": 8, "pretouch": false, "numa_nodes": ""
  },
  "summary": {"avg_us_mean": 187.58935, "avg_us_max": 187.58935, "avg_bandwidth": 8.392800550777537,
    "total_payload_bytes_per_iteration": 1574400, "copied_tokens_sum_per_iteration": 2400, "all_correct": true},
  "per_device": [
    {
      "schema_version": 2, "test": "a5_kvcache_copy_scheme_singlecard", "status": "passed",
      "timestamp_utc": "2026-10-14T17:04:18.616613+00:00", "device_count": 1,
      "config": {
        "device": "npu:0", "device_name": "Ascend950DT_9572", "dtype": "c8", "row_bytes": 656,
        "batch_size": 24, "source_len": 65536, "hbm_slots": 8192, "copy_min": 100, "copy_max": 100,
        "copy_cap": 16384, "warmup": 10, "iters": 200, "seed": 7, "scheme": "cpu", "run_frac": 0.0,
        "cpu_frac": 0.5, "hybrid_mode": "overlap", "cpu_threads": 8, "pretouch": false,
        "staging_pinned": true, "queue_depth": 8
      },
      "workload": {"copy_counts": [100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100],
        "copied_tokens": 2400, "cpu_tokens": 0, "payload_bytes_per_iteration": 1574400},
      "correctness": {"data_exact": true, "guard_unchanged": true},
      "summary": {"cards": 1, "batch_size": 24, "copy_count": 100,
        "avg_us_mean": 187.58935, "avg_us_max": 187.58935, "avg_bandwidth": 8.392800550777537},
      "performance": {"timer": "perf_counter", "avg_us": 187.58935, "avg_us_host_synced": null,
        "phases": {"cpu_gather_us": 46.533449999999995, "h2d_scatter_us": 75.64373468980193}},
      "rank": 0, "logical_device_index": 0
    }
  ]
}
```

`results/r2_regression/hybrid_cards1_bs24_copy0_rf0p0_cf0p5_overlap.json`：

```json
{
  "schema_version": 2, "test": "a5_kvcache_copy_scheme_multiprocess", "status": "passed",
  "timestamp_utc": "2026-10-14T17:04:33.057827+00:00", "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1, "devices": [0], "same_seed": true,
  "config": {
    "dtype": "c8", "row_bytes": 656, "batch_size": 24, "source_len": 65536, "hbm_slots": 8192,
    "copy_min": 0, "copy_max": 0, "copy_cap": 16384, "warmup": 10, "iters": 200, "seed": 7,
    "allow_non_a5": false, "scheme": "hybrid", "run_frac": 0.0, "cpu_frac": 0.5, "hybrid_mode": "overlap",
    "cpu_threads": 8, "pretouch": false, "numa_nodes": ""
  },
  "summary": {"avg_us_mean": 109.968, "avg_us_max": 109.968, "avg_bandwidth": 0.0,
    "total_payload_bytes_per_iteration": 0, "copied_tokens_sum_per_iteration": 0, "all_correct": true},
  "per_device": [
    {
      "schema_version": 2, "test": "a5_kvcache_copy_scheme_singlecard", "status": "passed",
      "timestamp_utc": "2026-10-14T17:04:30.749097+00:00", "device_count": 1,
      "config": {
        "device": "npu:0", "device_name": "Ascend950DT_9572", "dtype": "c8", "row_bytes": 656,
        "batch_size": 24, "source_len": 65536, "hbm_slots": 8192, "copy_min": 0, "copy_max": 0,
        "copy_cap": 16384, "warmup": 10, "iters": 200, "seed": 7, "scheme": "hybrid", "run_frac": 0.0,
        "cpu_frac": 0.5, "hybrid_mode": "overlap", "cpu_threads": 8, "pretouch": false,
        "staging_pinned": false, "queue_depth": 8
      },
      "workload": {"copy_counts": [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        "copied_tokens": 0, "cpu_tokens": 0, "payload_bytes_per_iteration": 0},
      "correctness": {"data_exact": true, "guard_unchanged": true,
        "zero_count_unchanged": true, "first_fill_capacity": true, "metadata_unchanged": true},
      "summary": {"cards": 1, "batch_size": 24, "copy_count": 0,
        "avg_us_mean": 109.968, "avg_us_max": 109.968, "avg_bandwidth": 0.0},
      "performance": {"timer": "perf_counter", "avg_us": 109.968, "avg_us_host_synced": null,
        "phases": {"launch_to_gather_done_us": 30.65945, "kernel_event_us": 43.357339981012046}},
      "rank": 0, "logical_device_index": 0
    }
  ]
}
```

`results/r2_regression/hybrid_cards1_bs24_copy100_rf0p0_cf0p5_overlap.json`：

```json
{
  "schema_version": 2, "test": "a5_kvcache_copy_scheme_multiprocess", "status": "passed",
  "timestamp_utc": "2026-10-14T17:04:44.497010+00:00", "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1, "devices": [0], "same_seed": true,
  "config": {
    "dtype": "c8", "row_bytes": 656, "batch_size": 24, "source_len": 65536, "hbm_slots": 8192,
    "copy_min": 100, "copy_max": 100, "copy_cap": 16384, "warmup": 10, "iters": 200, "seed": 7,
    "allow_non_a5": false, "scheme": "hybrid", "run_frac": 0.0, "cpu_frac": 0.5, "hybrid_mode": "overlap",
    "cpu_threads": 8, "pretouch": false, "numa_nodes": ""
  },
  "summary": {"avg_us_mean": 257.27655, "avg_us_max": 257.27655, "avg_bandwidth": 6.119485044400665,
    "total_payload_bytes_per_iteration": 1574400, "copied_tokens_sum_per_iteration": 2400, "all_correct": true},
  "per_device": [
    {
      "schema_version": 2, "test": "a5_kvcache_copy_scheme_singlecard", "status": "passed",
      "timestamp_utc": "2026-10-14T17:04:42.268927+00:00", "device_count": 1,
      "config": {
        "device": "npu:0", "device_name": "Ascend950DT_9572", "dtype": "c8", "row_bytes": 656,
        "batch_size": 24, "source_len": 65536, "hbm_slots": 8192, "copy_min": 100, "copy_max": 100,
        "copy_cap": 16384, "warmup": 10, "iters": 200, "seed": 7, "scheme": "hybrid", "run_frac": 0.0,
        "cpu_frac": 0.5, "hybrid_mode": "overlap", "cpu_threads": 8, "pretouch": false,
        "staging_pinned": true, "queue_depth": 8
      },
      "workload": {"copy_counts": [100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100],
        "copied_tokens": 2400, "cpu_tokens": 1200, "payload_bytes_per_iteration": 1574400},
      "correctness": {"data_exact": true, "guard_unchanged": true,
        "zero_count_unchanged": true, "first_fill_capacity": true, "metadata_unchanged": true},
      "summary": {"cards": 1, "batch_size": 24, "copy_count": 100,
        "avg_us_mean": 257.27655, "avg_us_max": 257.27655, "avg_bandwidth": 6.119485044400665},
      "performance": {"timer": "perf_counter", "avg_us": 257.27655, "avg_us_host_synced": null,
        "phases": {"launch_to_gather_done_us": 86.87589999999999, "kernel_event_us": 175.21119460463524}},
      "rank": 0, "logical_device_index": 0
    }
  ]
}
```

**结果文件**：`results/copy_scheme_a5_c8/`（主矩阵 60 case + manifest + summary + timing_summary.csv/md）与 `results/r2_regression/`（回归 4 case + manifest + summary + csv）均在宿主机 21；`results/` 已 gitignore，未提交入库。
**观察**（只事实、不结论）：
- 主矩阵 60 case 全 passed、correctness 全 true，含此前 §R1 崩溃的 cpu×copy0 坐标（修复后不再 AttributeError）。
- npu 档 cards1/2/8 与 §R1 偏差 ≤3.72%，cards4 档偏差 25.01%/19.89% 超 15%（见 R2-G4）。
- cpu 档 copy100/copy300 单卡 8.257/18.161 GB/s；cards8 52.732/109.785 GB/s。hybrid 档 cf 三档单卡 6.2-6.5/17.4-19.1 GB/s。
- 回归 cpu copy0：avg_us 68.505µs，phases cpu_gather 0.267µs + h2d_scatter 11.326µs，未归类 host 开销 ≈ 68.505 − 0.267 − 11.326 = 56.912µs（占 83.1%）；cpu copy100：avg_us 187.589µs，cpu_gather 46.533µs + h2d_scatter 75.644µs，未归类 host 开销 ≈ 65.412µs（占 34.9%）。
**异常**：无。

### 判读（§R2，2026-10-15，蓝区）

对照 §R1「判读预案」与 §R2「判读预案」逐条裁决（除注明外均为绿区**实测值**）：

**门槛**

- R2-G1 ✓ / R2-G2 ✓ / R2-G3 ✓：自检、回归（含 R1 崩溃坐标 cpu×copy0，
  修复生效）、主矩阵 60 case 全 passed、correctness 全 true。
- R2-G4 ✗（非门槛）：npu cards4 两坐标偏差 25.01%/19.89% > 15% ⇒ 按预案记
  **环境漂移**，npu 基线跨轮不可比，一切对比以 R2 轮内坐标为准；cards1/2/8
  偏差 ≤3.72%，与 R1 互洽。

**S1 裁决：阴性（host 开销主导）——按预案不判死刑，先压 host 开销再复试**

- cpu 在 copy300 全 cards 坐标 < npu（GB/s，轮内实测）：cards1 18.2/34.0、
  cards2 34.6/65.5、cards4 55.1/65.7、cards8 109.8/168.5。S1 阳性条件不满足。
- 分支判据命中「host 开销主导」（§R2 补充判据）：回归同坐标（cards1/bs24）
  cpu copy100 的未归类 host 开销 = 187.6 − 46.5(gather) − 75.6(h2d) ≈
  **65.4µs，占 34.9% > 30%**；copy0 时 avg=68.5µs 中未归类 **56.9µs（83.1%）**
  ——零负载下仍存在的纯固定开销，与 R1 冒烟估算（~72µs/37%）互洽。
- 固定开销随 die 数上涨（主矩阵 cpu copy0：71.8/74.2/85.3/119.8µs，
  cards1/2/4/8；npu copy0 ≈11µs 不涨）⇒ 开销主体是每迭代 host 侧
  launch/sync 串行成本，不是搬运本身。
- 边际成本（模型反推值，(T(copy)−T0)/tokens）：cpu 26.2/27.7/35.9/31.3
  ns/token，npu 17.7/18.7/39.6/29.7（cards1/2/4/8）——**cards4/8 时两者
  边际已持平**，cpu 的净输在固定开销。压掉固定开销后 cpu 路径在高 die 数
  坐标有翻正可能，这正是复试要验证的。

**S2 裁决：阳性候选不成立**

- hybrid(overlap) 无任何坐标 < min(npu, cpu)（copy300 最好坐标
  cards4/cf0.25=336.9µs vs 同坐标 npu 296.2µs）；多数坐标 hybrid 甚至
  差于两个父方案（如 cards2 copy300：293.8 vs cpu 273.4）。
- hybrid copy0 固定开销 107~152µs，高于 cpu 的 68~120µs——双流结构本身
  再加一层 host 开销。结论：当前实现形态下 overlap 不藏反伤；host 开销
  压减后是否复测 hybrid 由复试数据决定。

**下一步（按 §R2 预案写死的分支执行）**

S1 阴性（host 开销主导）⇒ R3 = **压 host 开销（窗口化流水：每窗口 N 次
迭代共享一次同步，消除每迭代全设备同步）+ cpu/hybrid 同坐标复试**。
判读口径备忘：R2 数据相位名 `h2d_scatter_us` ≡ 合并后代码的
`device_wall_us`；跨轮比较只对 R2 轮内坐标做。

---

## §R1-旧 派单：A5 首轮主矩阵（2026-10-14，蓝区）

### 目标

回答"离散 token 回搬走哪条路径最快"，并校准本 bench 在 A5 上可运行：先自检与
双方案冒烟，过了再跑默认主矩阵（npu / cpu / hybrid×{0.25,0.5,0.75}）。

### 前置核验

1. 两个仓并排克隆在同一父目录下（`_bootstrap` 依赖 `../nanovllm-scatter_copy` 相对路径）：
   - 蓝图仓：分支 `scatter_copy_a5_c8`，`git log --oneline -1` = `bb062d2`；
   - 本仓：分支 `main`，`git log --oneline -1` 标题为
     "init: copy-scheme-bench + 蓝绿 pingpong + §R1 派单"（单 commit 即全部）。
2. 蓝图仓补丁已贴：`git -C nanovllm-scatter_copy status -s` 显示两个 M 文件
   （kernel + multiprocess runner），且
   `grep "QUEUE_DEPTH =" nanovllm-scatter_copy/csrc/src/kvcache_scatter_copy_c8/op_kernel/vllm_a5_kvcache_scatter_copy_c8.cpp`
   输出 `constexpr uint32_t QUEUE_DEPTH = 8;`。
3. CANN 环境可 source：`/usr/local/Ascend/ascend-toolkit/latest/set_env.sh` 存在。
4. `npu-smi info` 可见 8 个 die；`python3 -c "import torch, torch_npu"` 无报错。
5. 环境无残留：`ASCEND_CUSTOM_OPP_PATH` / `NANOVLLM_A5_INSTALL_OPP_PATH` /
   `NANOVLLM_CUST_OPAPI_LIB` / `SCATTER_C8_NUMA_NODES` 均未设置（env 输出为空）。

### 执行命令

逐字执行（`<PARENT>` = 两仓的共同父目录）：

```bash
cd <PARENT>
git clone -b scatter_copy_a5_c8 https://github.com/xieqiang-hw/nanovllm-DSA-offload_scatter_copy.git nanovllm-scatter_copy
git clone -b main git@github.com:JiJiaF1020/copy-scheme-bench.git copy-scheme-bench
cd nanovllm-scatter_copy
git apply --check ../copy-scheme-bench/side_blueprint/blueprint_wip_queue8_numa.patch
git apply ../copy-scheme-bench/side_blueprint/blueprint_wip_queue8_numa.patch
grep "QUEUE_DEPTH =" csrc/src/kvcache_scatter_copy_c8/op_kernel/vllm_a5_kvcache_scatter_copy_c8.cpp
bash build_c8.sh
cd <PARENT>
cd copy-scheme-bench/tests && python3 test_scheme_tools.py && cd <PARENT>
# 冒烟：单 die、双方案、短迭代
bash copy-scheme-bench/run_scheme_sweep.sh --cards 1 --batch-size 24 --copy-count 100 \
  --schemes npu cpu --iters 200 --results-dir copy-scheme-bench/results/smoke
# 主矩阵（默认 schemes="npu cpu hybrid"、cpu-fracs 0.25/0.5/0.75、cards 1/2/4/8、copy 0/100/300）
bash copy-scheme-bench/run_scheme_sweep.sh
```

### 通过标准

- G1：`build_c8.sh` 退出码 0，输出含 `[c8_build] torch extension import: OK`。
- G2：前置核验第 2 条的 grep 输出为 `QUEUE_DEPTH = 8`。
- G3：`test_scheme_tools.py` 末两行输出 `Ran 21 tests` 与 `OK`。
- G4：冒烟 2 个 case JSON（`results/smoke/npu_*.json`、`cpu_*.json`）
  `status=="passed"` 且 `correctness` 全 true。
- G5：主矩阵 `results/copy_scheme_a5_c8/copy_scheme_run_manifest.json`
  `status=="passed"`；`copy_scheme_summary.json` 存在且 `case_count==60`
  （4 cards × 3 copy × [npu + cpu + hybrid×3]）；每个 case JSON correctness 全 true。
- G6（sanity，非验收门槛）：`npu` 方案 cards1/bs24/copy100 的 `avg_bandwidth`
  与该机历史 C8 带宽曲线同量级；偏差 >30% 时原样回传并注明，由蓝区判断环境
  是否有问题（不自行重跑调参）。

### 回传格式

按根目录 `AGENTS.md` 的交付模板写回本文件 §R1 下方，并原样附上：

1. `copy_scheme_timing_summary.md` 全文（主矩阵六列+方案坐标表）；
2. `copy_scheme_run_manifest.json` 全文；
3. 冒烟两个 case JSON 全文；
4. 若任何一步失败：该步 stderr/日志末 30 行原文，停止后续步骤照常交付。
5. 结果目录在 `.gitignore` 内不入库；只回写 `pingpong.md`（和 `history.md` 追加一行）。

### 判读预案（派单时写死）

- 若 `cpu` 方案 `avg_bandwidth` 在 copy=300 的全部 cards 坐标上 ≥ 同坐标 `npu`
  ⇒ **S1 阳性**：CPU gather+H2D 路径成立，下一轮做 hybrid 细分与生产集成评估。
- 若 `cpu` 全坐标 < `npu`，且其 `phases.cpu_gather_us` 占 `avg_us` 主导
  ⇒ **S1 阴性**：瓶颈在 CPU 侧 gather，该方向收摊，下一轮转 S4（队列深度）。
- 若 `cpu` < `npu` 但 `cpu_gather_us` 占比小、`h2d_scatter_us` 主导
  ⇒ 瓶颈在 DMA/H2D 段：方向是减小 H2D 量（hybrid 小 frac），不是换路径。
- 若 `hybrid`（overlap）`avg_us` < 同坐标 min(npu, cpu) ⇒ 两条 PCIe 路径可并发，
  记 **S2 阳性候选**，下一轮扫更细 frac。
- 任一 case correctness 失败 ⇒ 该 case 无效（不影响其他坐标判读）；
  G1–G3 任一失败 ⇒ **整轮无效**，蓝区诊断后重新派单。

---

（新轮次从这里往下追加：蓝区写「派单」节，绿区写「交付」节，蓝区写「判读」节。最新一轮在最上面，旧轮次标题加「-旧」标记。）

### 交付（§R1，2026-10-15，绿区）

**执行环境**：机器/机型 141.61.33.21 (work21) / Ascend950DT_9572 ×8；设备 8 die（visible 0-7）；容器/宿主 宿主 root；时间 2026-10-14T15:52Z ~ 2026-10-15T00:01Z。
**前置核验**：1) 蓝图仓 `nanovllm-scatter_copy`@`bb062d2`（分支 scatter_copy_a5_c8）+ 本仓@`0a993b5`（"init: copy-scheme-bench + 蓝绿 pingpong + §R1 派单"）并列于 /home/h2d_test ✓；2) 补丁已贴，`git -C nanovllm-scatter_copy status -s` 两个 M，grep 输出 `constexpr uint32_t QUEUE_DEPTH = 8;` ✓；3) `/usr/local/Ascend/ascend-toolkit/latest/set_env.sh` 存在 ✓；4) `npu-smi info` 8 die ✓，`python3 -c "import torch, torch_npu"` 经 run_scheme_sweep.sh source CANN 后无报错 ✓；5) 四环境变量 grep 无匹配 ✓。
**执行**：
- clone 偏差说明：任务书命令为 SSH 克隆 `git@github.com`，本机出网经 HIS/SWG 网关（netentsec）拦截 SSH CONNECT（403），SSH 路径物理不可达；实际改用 https + 内网代理 141.61.33.201:8091 + `-c http.sslVerify=false` 完成克隆，仓库 tip/分支与任务书一致（仓库先前为私有 404，蓝区改公开后 200）。结果等价，特此注明。
- 环境准备偏差：构建报 `fatal error: Python.h`，21 缺 python3-devel，经代理 `yum install python3-devel` 安装（属环境依赖补齐，非代码改动）。
- 逐字命令：clone（https 替代 SSH）→ `git apply --check` → `git apply` → grep QUEUE_DEPTH → `bash build_c8.sh` → `cd tests && python3 test_scheme_tools.py` → 冒烟 → 主矩阵 `bash copy-scheme-bench/run_scheme_sweep.sh`（无参数，默认配置，iters=1000）。

**通过标准命中**：
- G1 ✓：build_c8.sh RC=0，输出含 `[c8_build] torch extension import: OK`。
- G2 ✓：`QUEUE_DEPTH = 8`。
- G3 ✓：`Ran 21 tests` / `OK`（RC=0）。
- G4 ✓：冒烟 2 case JSON status=="passed"，correctness 全 true（详见下方原文）。
- G5 ✗：**未通过**。主矩阵在 `cpu_cards1_bs24_copy0_rf0p0` 崩溃（manifest status="failed"），仅完成 12/60 个 case（全部 npu 方案，均 passed 且 correctness 全 true），cpu/hybrid 方案未跑。崩溃根因见"异常"。`copy_scheme_summary.json` 因整轮失败未生成。
- G6（sanity，非门槛）：npu cards1/bs24/copy100 `avg_bandwidth`=32.649 GB/s（冒烟同坐标 32.485 GB/s，同轮一致），与 A5 C8 历史曲线同量级（历史 16384 档 ~67 GB/s 为不同坐标/口径，仅供参考）。

**原始数据**：
1. 主矩阵 manifest（全文，status="failed"）：见下。
2. 主矩阵已完成 12 个 npu case 六列汇总（summary 未生成，按 JSON summary 字段整理）：
```
| case | status | cards | copy | avg_us_mean | avg_us_max | avg_bandwidth | correctness |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| npu_cards1_bs24_copy0_rf0p0.json | passed | 1 | 0 | 11.221 | 11.221 | 0.000 | True |
| npu_cards1_bs24_copy100_rf0p0.json | passed | 1 | 100 | 48.222 | 48.222 | 32.649 | True |
| npu_cards1_bs24_copy300_rf0p0.json | passed | 1 | 300 | 138.709 | 138.709 | 34.051 | True |
| npu_cards2_bs24_copy0_rf0p0.json | passed | 2 | 0 | 11.003 | 11.302 | 0.000 | True |
| npu_cards2_bs24_copy100_rf0p0.json | passed | 2 | 100 | 48.255 | 48.270 | 65.253 | True |
| npu_cards2_bs24_copy300_rf0p0.json | passed | 2 | 300 | 138.831 | 138.991 | 68.043 | True |
| npu_cards4_bs24_copy0_rf0p0.json | passed | 4 | 0 | 10.941 | 11.325 | 0.000 | True |
| npu_cards4_bs24_copy100_rf0p0.json | passed | 4 | 100 | 70.858 | 72.758 | 88.901 | True |
| npu_cards4_bs24_copy300_rf0p0.json | passed | 4 | 300 | 230.369 | 233.686 | 82.028 | True |
| npu_cards8_bs24_copy0_rf0p0.json | passed | 8 | 0 | 11.929 | 18.442 | 0.000 | True |
| npu_cards8_bs24_copy100_rf0p0.json | passed | 8 | 100 | 71.663 | 82.462 | 178.635 | True |
| npu_cards8_bs24_copy300_rf0p0.json | passed | 8 | 300 | 218.018 | 235.693 | 174.963 | True |
```
3. 冒烟两个 case JSON 全文：见下。
4. 失败步骤日志末 30 行：见"异常"。

**结果文件**：`/home/h2d_test/copy-scheme-bench/results/copy_scheme_a5_c8/`（12 npu JSON + 1 cpu failed JSON + manifest + 各 .log）；`results/` 在 .gitignore 内不入库。

**观察**（只事实、不结论）：
- npu 方案 12 个坐标全部 passed、correctness 全 true；多 die 带宽 = 各 die 速率之和（口径按 §R1 第 0 节）；copy0 坐标带宽 0（无 payload），avg_us ~11µs 为 launch 开销量级。
- 崩溃坐标是主矩阵第 13 个 case（npu 12 个之后第一个 cpu 方案 case），即 sweep 在 cpu×copy0 首坐标即中断。

**异常**：
- 主矩阵 `cpu_cards1_bs24_copy0_rf0p0` 失败，日志末 30 行原文：
```
A5_COPY_SCHEME_CONFIG device=npu:0 device_name='Ascend950DT_9572' scheme=cpu run_frac=0.0 cpu_frac=0.5 hybrid_mode=overlap cpu_threads=8 pretouch=False staging_pinned=False batch=24 copy_range=[0,0] copied_tokens=0 cpu_tokens=0 queue_depth=8
Traceback (most recent call last):
  File "/home/h2d_test/copy-scheme-bench/tests/test_scheme_worker.py", line 530, in <module>
    main()
  File "/home/h2d_test/copy-scheme-bench/tests/test_scheme_worker.py", line 526, in main
    run(args)
  File "/home/h2d_test/copy-scheme-bench/tests/test_scheme_worker.py", line 457, in run
    check_copy(case, args, "requested_workload")
  File "/home/h2d_test/copy-scheme-bench/tests/test_scheme_worker.py", line 318, in check_copy
    run_scheme_pass(case, args.scheme, args.hybrid_mode)
  File "/home/h2d_test/copy-scheme-bench/tests/test_scheme_worker.py", line 275, in run_scheme_pass
    cpu_full_pass(case)
  File "/home/h2d_test/copy-scheme-bench/tests/test_scheme_worker.py", line 250, in cpu_full_pass
    cpu_gather(case)
  File "/home/h2d_test/copy-scheme-bench/tests/test_scheme_worker.py", line 239, in cpu_gather
    case.staging.copy_(case.dram_flat_cpu.index_select(0, src))
    ^^^^^^^^^^^^^^^^^^
AttributeError: 'NoneType' object has no attribute 'copy_'
[ERROR] 2026-10-15-00:01:43 (PID:1274744, Device:0, RankID:-1) ERR99999 UNKNOWN applicaiton exception
Traceback (most recent call last):
  File "/home/h2d_test/copy-scheme-bench/tests/run_scheme_multiprocess.py", line 207, in <module>
    main()
  File "/home/h2d_test/copy-scheme-bench/tests/run_scheme_multiprocess.py", line 194, in main
    output = summarize(args, devices, run_workers(args, devices))
                                      ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/h2d_test/copy-scheme-bench/tests/run_scheme_multiprocess.py", line 130, in run_workers
    wait_until_ready(initial_ready, processes, "initialization")
  File "/home/h2d_test/copy-scheme-bench/tests/run_scheme_multiprocess.py", line 64, in wait_until_ready
    raise RuntimeError(f"Workers exited during {phase}: {failed}")
RuntimeError: Workers exited during initialization: [(0, 1)]
```
- 根因定位（只事实）：`test_scheme_worker.py` `make_case` 中 staging 仅在 `scheme in ("cpu","hybrid") and stage_tokens > 0` 时分配（line 188），`stage_tokens = len(phys_src_all)`；copy=0 时 `phys_src_all` 为空列表 → `stage_tokens=0` → `staging=None`；而 `cpu_gather`（line 239）无条件 `case.staging.copy_(...)` → NoneType 崩溃。冒烟用 copy=100 未触发（phys_src_all 非空），主矩阵默认 copy 含 0 触发。判定为任务书脚本在 `cpu × copy_count=0` 组合下的缺陷；绿区不修改代码，停止后续步骤照常交付，等蓝区修订后重新派单。

#### 附 1：主矩阵 copy_scheme_run_manifest.json 全文
```json
{
  "schema_version": 2,
  "status": "failed",
  "dtype": "c8",
  "timestamp_utc": "2026-10-14T15:59:05.247180+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "queue_depth": "default",
  "case_files": [
    "npu_cards1_bs24_copy0_rf0p0.json",
    "npu_cards1_bs24_copy100_rf0p0.json",
    "npu_cards1_bs24_copy300_rf0p0.json",
    "npu_cards2_bs24_copy0_rf0p0.json",
    "npu_cards2_bs24_copy100_rf0p0.json",
    "npu_cards2_bs24_copy300_rf0p0.json",
    "npu_cards4_bs24_copy0_rf0p0.json",
    "npu_cards4_bs24_copy100_rf0p0.json",
    "npu_cards4_bs24_copy300_rf0p0.json",
    "npu_cards8_bs24_copy0_rf0p0.json",
    "npu_cards8_bs24_copy100_rf0p0.json",
    "npu_cards8_bs24_copy300_rf0p0.json",
    "cpu_cards1_bs24_copy0_rf0p0.json",
    "cpu_cards1_bs24_copy100_rf0p0.json",
    "cpu_cards1_bs24_copy300_rf0p0.json",
    "cpu_cards2_bs24_copy0_rf0p0.json",
    "cpu_cards2_bs24_copy100_rf0p0.json",
    "cpu_cards2_bs24_copy300_rf0p0.json",
    "cpu_cards4_bs24_copy0_rf0p0.json",
    "cpu_cards4_bs24_copy100_rf0p0.json",
    "cpu_cards4_bs24_copy300_rf0p0.json",
    "cpu_cards8_bs24_copy0_rf0p0.json",
    "cpu_cards8_bs24_copy100_rf0p0.json",
    "cpu_cards8_bs24_copy300_rf0p0.json",
    "hybrid_cards1_bs24_copy0_rf0p0_cf0p25_overlap.json",
    "hybrid_cards1_bs24_copy100_rf0p0_cf0p25_overlap.json",
    "hybrid_cards1_bs24_copy300_rf0p0_cf0p25_overlap.json",
    "hybrid_cards2_bs24_copy0_rf0p0_cf0p25_overlap.json",
    "hybrid_cards2_bs24_copy100_rf0p0_cf0p25_overlap.json",
    "hybrid_cards2_bs24_copy300_rf0p0_cf0p25_overlap.json",
    "hybrid_cards4_bs24_copy0_rf0p0_cf0p25_overlap.json",
    "hybrid_cards4_bs24_copy100_rf0p0_cf0p25_overlap.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p25_overlap.json",
    "hybrid_cards8_bs24_copy0_rf0p0_cf0p25_overlap.json",
    "hybrid_cards8_bs24_copy100_rf0p0_cf0p25_overlap.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p25_overlap.json",
    "hybrid_cards1_bs24_copy0_rf0p0_cf0p5_overlap.json",
    "hybrid_cards1_bs24_copy100_rf0p0_cf0p5_overlap.json",
    "hybrid_cards1_bs24_copy300_rf0p0_cf0p5_overlap.json",
    "hybrid_cards2_bs24_copy0_rf0p0_cf0p5_overlap.json",
    "hybrid_cards2_bs24_copy100_rf0p0_cf0p5_overlap.json",
    "hybrid_cards2_bs24_copy300_rf0p0_cf0p5_overlap.json",
    "hybrid_cards4_bs24_copy0_rf0p0_cf0p5_overlap.json",
    "hybrid_cards4_bs24_copy100_rf0p0_cf0p5_overlap.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p5_overlap.json",
    "hybrid_cards8_bs24_copy0_rf0p0_cf0p5_overlap.json",
    "hybrid_cards8_bs24_copy100_rf0p0_cf0p5_overlap.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p5_overlap.json",
    "hybrid_cards1_bs24_copy0_rf0p0_cf0p75_overlap.json",
    "hybrid_cards1_bs24_copy100_rf0p0_cf0p75_overlap.json",
    "hybrid_cards1_bs24_copy300_rf0p0_cf0p75_overlap.json",
    "hybrid_cards2_bs24_copy0_rf0p0_cf0p75_overlap.json",
    "hybrid_cards2_bs24_copy100_rf0p0_cf0p75_overlap.json",
    "hybrid_cards2_bs24_copy300_rf0p0_cf0p75_overlap.json",
    "hybrid_cards4_bs24_copy0_rf0p0_cf0p75_overlap.json",
    "hybrid_cards4_bs24_copy100_rf0p0_cf0p75_overlap.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p75_overlap.json",
    "hybrid_cards8_bs24_copy0_rf0p0_cf0p75_overlap.json",
    "hybrid_cards8_bs24_copy100_rf0p0_cf0p75_overlap.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p75_overlap.json"
  ]
}
```

#### 附 2：冒烟 npu_cards1_bs24_copy100_rf0p0.json 全文
```json
{
  "schema_version": 2,
  "test": "a5_kvcache_copy_scheme_multiprocess",
  "status": "passed",
  "timestamp_utc": "2026-10-14T15:57:12.252212+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1,
  "devices": [0],
  "same_seed": true,
  "config": {
    "dtype": "c8", "row_bytes": 656, "batch_size": 24, "source_len": 65536,
    "hbm_slots": 8192, "copy_min": 100, "copy_max": 100, "copy_cap": 16384,
    "warmup": 10, "iters": 200, "seed": 7, "allow_non_a5": false,
    "scheme": "npu", "run_frac": 0.0, "cpu_frac": 0.5, "hybrid_mode": "overlap",
    "cpu_threads": 8, "pretouch": false, "numa_nodes": ""
  },
  "summary": {
    "avg_us_mean": 48.46477508544922, "avg_us_max": 48.46477508544922,
    "avg_bandwidth": 32.48544942639564, "total_payload_bytes_per_iteration": 1574400,
    "copied_tokens_sum_per_iteration": 2400, "all_correct": true
  },
  "per_device": [
    {
      "schema_version": 2, "test": "a5_kvcache_copy_scheme_singlecard", "status": "passed",
      "timestamp_utc": "2026-10-14T15:57:09.031710+00:00", "device_count": 1,
      "config": {
        "device": "npu:0", "device_name": "Ascend950DT_9572", "dtype": "c8", "row_bytes": 656,
        "batch_size": 24, "source_len": 65536, "hbm_slots": 8192, "copy_min": 100, "copy_max": 100,
        "copy_cap": 16384, "warmup": 10, "iters": 200, "seed": 7, "scheme": "npu", "run_frac": 0.0,
        "cpu_frac": 0.5, "hybrid_mode": "overlap", "cpu_threads": 8, "pretouch": false,
        "staging_pinned": false, "queue_depth": 8
      },
      "workload": {
        "copy_counts": [100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100],
        "copied_tokens": 2400, "cpu_tokens": 0, "payload_bytes_per_iteration": 1574400
      },
      "correctness": {
        "data_exact": true, "guard_unchanged": true, "zero_count_unchanged": true,
        "first_fill_capacity": true, "metadata_unchanged": true
      },
      "summary": {
        "cards": 1, "batch_size": 24, "copy_count": 100,
        "avg_us_mean": 48.46477508544922, "avg_us_max": 48.46477508544922,
        "avg_bandwidth": 32.48544942639564
      },
      "performance": {
        "timer": "npu_event", "avg_us": 48.46477508544922, "avg_us_host_synced": 75.6018, "phases": {}
      },
      "rank": 0, "logical_device_index": 0
    }
  ]
}
```

#### 附 3：冒烟 cpu_cards1_bs24_copy100_rf0p0.json 全文
```json
{
  "schema_version": 2,
  "test": "a5_kvcache_copy_scheme_multiprocess",
  "status": "passed",
  "timestamp_utc": "2026-10-14T15:57:29.232022+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1,
  "devices": [0],
  "same_seed": true,
  "config": {
    "dtype": "c8", "row_bytes": 656, "batch_size": 24, "source_len": 65536,
    "hbm_slots": 8192, "copy_min": 100, "copy_max": 100, "copy_cap": 16384,
    "warmup": 10, "iters": 200, "seed": 7, "allow_non_a5": false,
    "scheme": "cpu", "run_frac": 0.0, "cpu_frac": 0.5, "hybrid_mode": "overlap",
    "cpu_threads": 8, "pretouch": false, "numa_nodes": ""
  },
  "summary": {
    "avg_us_mean": 192.42675, "avg_us_max": 192.42675,
    "avg_bandwidth": 8.181814638557269, "total_payload_bytes_per_iteration": 1574400,
    "copied_tokens_sum_per_iteration": 2400, "all_correct": true
  },
  "per_device": [
    {
      "schema_version": 2, "test": "a5_kvcache_copy_scheme_singlecard", "status": "passed",
      "timestamp_utc": "2026-10-14T15:57:26.341918+00:00", "device_count": 1,
      "config": {
        "device": "npu:0", "device_name": "Ascend950DT_9572", "dtype": "c8", "row_bytes": 656,
        "batch_size": 24, "source_len": 65536, "hbm_slots": 8192, "copy_min": 100, "copy_max": 100,
        "copy_cap": 16384, "warmup": 10, "iters": 200, "seed": 7, "scheme": "cpu", "run_frac": 0.0,
        "cpu_frac": 0.5, "hybrid_mode": "overlap", "cpu_threads": 8, "pretouch": false,
        "staging_pinned": true, "queue_depth": 8
      },
      "workload": {
        "copy_counts": [100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100],
        "copied_tokens": 2400, "cpu_tokens": 0, "payload_bytes_per_iteration": 1574400
      },
      "correctness": {
        "data_exact": true, "guard_unchanged": true
      },
      "summary": {
        "cards": 1, "batch_size": 24, "copy_count": 100,
        "avg_us_mean": 192.42675, "avg_us_max": 192.42675,
        "avg_bandwidth": 8.181814638557269
      },
      "performance": {
        "timer": "perf_counter", "avg_us": 192.42675, "avg_us_host_synced": null,
        "phases": {"cpu_gather_us": 47.88585, "h2d_scatter_us": 72.35152505338192}
      },
      "rank": 0, "logical_device_index": 0
    }
  ]
}
```

### 判读（§R1，2026-10-15，蓝区）

对照 §R1「通过标准」与「判读预案」逐条裁决（数据均为绿区**实测值**）：

- G1 ✓ / G2 ✓ / G3 ✓ / G4 ✓：构建、补丁、自检、冒烟全过（绿区实测，冒烟两
  case 字节级正确性全 true）。冒烟两 case 坐标一致（cards1/bs24/copy100），
  同轮可比。
- G5 ✗ ⇒ 按预案「数据缺失 ⇒ 本轮无效」裁决：**R1 主矩阵目标无效**。根因是
  蓝区脚本缺陷（`cpu_gather`/`cpu_device_pass` 未处理空份额，copy=0 触发
  NoneType），非被测对象问题；修复与回归开关已随 §R2 下发。
- 已完成的 12 个 npu case correctness 全 true、冒烟与主矩阵同坐标一致
  （32.485 vs 32.649 GB/s，偏差 0.5%）、G6 与该机历史曲线同量级
  ⇒ **npu 基线 12 坐标有效落袋**（实测值）：
  cards1 32.6/34.1，cards2 65.3/68.0，cards4 88.9/82.0，cards8 178.6/175.0
  GB/s（copy100/copy300）；copy0 纯 launch 开销 ~11µs。
- S1/S2 主裁决：**顺延至 R2**（cpu/hybrid 本轮无数据，不裁决）。

观察（事实，非裁决，供 R2 后对照）：

- 多 die 聚合亚线性：1→2 die 线性（32.6→65.3 GB/s），2→4 die 仅 1.36×，
  单 die 速率从 34 跌至 ~21 GB/s（copy300）⇒ ≥4 die 时共享链路出现竞争
  （实测值）。这强化了换路径/分流的动机；R2 中 cpu/hybrid 在 cards4/8 的
  表现是最关键坐标。
- 冒烟同坐标：cpu 192.4µs vs npu 48.5µs（event）/ 75.6µs（synced 墙钟）。
  cpu 的 `cpu_gather_us`=47.9µs/2400 行 ≈ 20.0ns/行，与 npu kernel 的
  20.2ns/行持平；差距在 `h2d_scatter_us`=72.4µs 与未归类 host 开销 ~72µs
  （占 avg_us 的 37%）（实测值；host 开销为 avg_us 减两相位的**模型反推值**）。
  ⇒ §R2 判读预案已补充「host 开销主导」分支。

# R5 噪声归因分析报告：hybrid cards8 repeat 极差 43~63% 是什么

> 蓝区，2026-10-15。数据全部来自绿区实测交付（R4 `da22c6c` / R5 `83d5507`，
> 原文在 pingpong.md 各轮交付节）。结论分级：**实测** / **排除（有反证）** /
> **推测（待 R6 裁决）**。

## 1. 现象（实测）

R5 同轮同机（work21，8×Ascend950DT_9572），cards8 copy300：

| 组 | 方案 | 6 次 repeat 带宽极差 (max-min)/min |
| --- | --- | ---: |
| confirm8 cf0.1 | hybrid | 43.05% |
| confirm8 cf0.15 | hybrid | 47.81% |
| confirm8 cf0.3 | hybrid | 63.24% |
| confirm8 cf0.4 | hybrid | 58.83% |
| **anchor8** | **npu** | **3.96%** |

cf0.4 逐 run 带宽（GB/s）：**216.04 / 182.23 / 136.79 / 217.27 / 178.16 /
138.56**——不是连续分布，呈三簇 {~217, ~180, ~137}，相邻 run 可差 1.6 倍。
anchor8 逐 run：171.78 / 170.64 / 174.48 / 171.76 / 171.57 / 167.83——平稳。

## 2. 排除项（每条有反证）

- **不是机器整体漂移**：同轮 npu anchor 稳（3.96%）；跨轮 anchor
  171.264（R4）→ 171.343（R5），偏差 0.05%。
- **不是卡间 PCIe/链路竞争**：竞争会均匀拖慢全部 8 个 die 且同样作用于
  npu 路径；实测 npu 稳、hybrid 摆，且 R4 的 per-device 数据呈快慢两簇
  （下节）而非均匀劣化。卡间竞争是真实存在的，但它是 **npu 路径聚合
  亚线性**（单 die 34→21 GB/s，R1 起跨轮一致）的原因，不是本次 run 级
  噪声的原因——两件事，别混。
- **不是迭代内波动**：42 个 case 的 p99/p50 全部 <2（最大 1.48），迭代级
  分布健康；噪声发生在 **run 级**（每次进程重启后整 run 偏移）。
- **不是 THP**：基线 THP=madvise（R4 C 组实测 always 反而有害 +31.7%，
  已排除并弃用）。
- **不是 CPU 降频/热**：同轮 npu anchor 的 host 同步墙钟同样经过 CPU，
  若 CPU 降频 anchor 也会摆——没有。

## 3. 证据链 → NUMA 落点抽签（推测，三方互洽）

1. **R4 per-device 双峰**（A 组 cf0.25 cards8 copy300 的 gather 相位）：
   die3=167.1µs、die7=155.4µs，其余六 die ≈273~286µs——**快档比慢档快
   1.74x**。gather 是 hybrid/cpu 路径中唯一访问 host DRAM 池的相位。
2. **噪声只在含 CPU gather 的方案出现**：npu（纯 kernel，不经 host DRAM）
   稳；hybrid（10~40% 流量走 CPU gather）摆。摆幅与 cf 正相关的方向也
   对得上（cf0.3/0.4 极差大于 cf0.1）。
3. **run 级而非迭代级**：worker 进程每次 run 重新 spawn，DRAM 池镜像
   （数 GB）重新分配。Linux first-touch 策略下，池页落在**执行分配的
   线程当时所在的 NUMA 节点**；8 个 worker 的 CPU 落点由调度器每次
   重新决定——这就是「抽签」：池页节点 × worker 落点的组合每 run 不同，
   同节点=快档（本地访存），跨节点=慢档（走互连）。run 内落点不变 ⇒
   整 run 偏移、迭代内平稳——与观测完全吻合。

**一个诚实的补充**：慢档不只是延迟问题。若池页集中在单节点，8 个 worker
跨节点读同一节点的内存控制器，该节点带宽被 8 路共享——这可能同时压低
慢档的绝对值。这意味着 **interleave（池页均匀铺到所有节点）可能比
bind（worker 绑到池节点）更优**：前者把负载摊到全部节点的控制器。
R6 先验绑定（实验简单），interleave 作为后续候选（要改 worker 分配代码）。

## 4. 数学后果（模型外推，标注推测）

cf0.4 折叠均值 178.18 GB/s 是三簇混合的均值。若归置修复后每 run 稳定
落在高簇（~217 GB/s），对同轮 npu anchor（171.34）的收益：

```
217.27 / 171.34 = 1.268   →  +26.8%（修复后上限估计）
178.18 / 171.34 = 1.040   →  +4.0%（当前噪声现状）
```

即：**不修 NUMA，hybrid 只有 +4% 且不可复现；修好 NUMA，上限 +26%**。
这就是 R6 要裁决的事。

## 5. 裁决实验（§R6 在飞，因 numactl 缺失阻塞，§R6b 修订后重派）

- `numactl -H` + `lscpu` + `/proc/sys/kernel/numa_balancing`：拓扑取证。
- cpu / hybrid（cf0.1）cards8 copy300，绑定 vs 不绑定同轮对比
  （sweep 内建双跑）：
  - 绑定态极差 ≤10% 且不绑定态照旧 >15% ⇒ 落点抽签**实锤**；
  - 绑定态均值 ≥ 不绑定态 ⇒ 绑定=修复，纳入正式配置；
  - 绑定无效应 ⇒ NUMA 归因证伪，转查调度迁移/中断等备选。
- die 双峰的配对疑点（die3+die7 非整 socket 配对）由拓扑输出一并裁决。

## 6. 附：关键数据出处

- R5 逐 run 明细与极差：pingpong.md §R5 交付节「判读预案输入」表。
- R4 per-device gather 双峰：pingpong.md §R4 交付节 A/frac case JSON
  （drafts/die_bimodality_r4.md 有专门分析）。
- npu 亚线性（34→21 GB/s）：R1/R3/R5 各轮 anchor 表，跨轮一致。

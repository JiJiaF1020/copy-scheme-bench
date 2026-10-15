# 生产形态设计稿：hybrid 分流嵌入 vLLM DSA-offload 层间流水（蓝区，2026-10-15）

> 状态：**已解冻（R6c 判：S2 强阳性，2026-10-15）**。R5 冻结口径：最优
> cf0.4 +3.99% 未达 ×1.05、repeat 极差 43~63% 不可复现。R6c（21 原坐标、
> NUMA 绑定形态）：hybrid cf0.1 cards8 绑定态折叠 180.019 GB/s ≥
> 同轮 anchor8 168.512×1.05=176.938（×1.068，+6.82%），绑定态极差
> 0.99% ⇒ **强阳性，本稿进入集成实施评估**。注意：稳态实得 +6.8%，
> R5 高簇外推的 +26% 未兑现（成因未明，开放问题）；生产三件套：
> cf=0.1 + pretouch + NUMA 绑定（sched_setaffinity/numactl 任一）。
>
> 证据链：R1（基线+亚线性）→ R2（S1 阴性，host 开销主导）→ R3（window=16
> 压 host 开销 -94%，S2 重开）→ R4（S2 弱阳性、缺页实锤 cards8、THP 有害、
> ρ* 0.25/0.20）→ R5（弱阳性维持、噪声收窄 NUMA）→ R6b（NUMA 实锤 cards4
> +12%）→ R6c（抽签原坐标实锤 + S2 强阳性）。全部数值见 pingpong.md 各轮
> 判读节，本文不复制实测表。

## 1. 集成点（vLLM-ascend-DSA 现状映射）

生产链路与 bench 方案的对应关系：

| bench 方案 | 生产算子/路径（vllm_ascend/dsa_offload/ops.py） |
| --- | --- |
| npu（S0 基线） | `a5_kvcache_scatter_copy_c8`（纯回搬 kernel，:283）或其融合形态 `a5_fused_copy_sfa_copy_stage`（:304）/ `fused_copy_sfa_c8`（:518，copy+MTP QSFA 单次 MIX launch） |
| cpu（S1） | 无对应——生产当前没有 CPU gather 路径；本稿即提案 |
| hybrid（S2） | copy plan 行级切分：前 1-cf 行走 kernel（融合 copy stage），尾 cf 行走 CPU gather→大块 H2D→设备侧 scatter，旁流并发 |

层间上下文：`DSALayerOffloadContext`（runtime.py:854）逐层执行
`execute_decode_selection`（lightning indexer top-k 选出回搬 token）→
copy stage → `execute_sparse_attention`。hybrid 只改 copy stage 的内部
实现，对上（selection）对下（SFA）接口不变。

## 2. 分流设计（copy plan 行级切分）

- **切分点**：copy plan（`copy_src_ids/dst_slots/copy_counts`，语义与
  bench 完全一致：BLOCK=128、COPY_CAP=16384、-1 填充）按行切两段——
  前 `ceil(rows×(1-cf))` 行走 kernel，尾部走 CPU。切分在 host 侧
  metadata 组装时完成，零设备端改动。
- **集成面已核实**（2026-10-15 读码，vLLM-ascend-DSA）：runtime 当前全部
  copy 走独立 kernel `a5_kvcache_scatter_copy_c8`，**仅两处调用点**
  （runtime.py:944 `execute_decode_selection`、runtime.py:1044
  `execute_shared_decode_selection`），参数同为三件套
  `(topk_index, topk_slots, miss_count)`——hybrid 切分 = 三件套用同一
  行界 K 切片，K 按 `copy_counts` 累计值反解使 CPU 份额 ≈cf（bench
  scheme_workload.py 的 hybrid 切分即此逻辑）。**融合算子
  `fused_copy_sfa_c8` 已注册但尚无生产调用点**（仅 ops.py 定义 +
  contracts.py 注释提及），故本稿的集成目标是独立 kernel 路径，
  无 MIX 核内资源配比问题（见 §5.4 的残留风险）。
- **cf 推荐值**：**0.1（静态）**。依据 R4：延迟口径 cf0.1 全档最稳
  （avg_us_mean 212.06 / avg_us_max 219.55，max/mean 仅 1.04；cf0.4 吞吐
  略高但 max/mean 1.22 有长尾）。生产 decode 对尾延迟敏感，取稳不取尖。
- **CPU 段形态**（即 bench S1 路径的生产化）：CPU 多线程从 DRAM 池镜像
  gather 到 pinned staging → 一次大块 H2D → 设备侧 index_copy 散到目标槽。
  staging 复用、每 4K 页 pretouch（见 §4）。
- **旁流并发**（overlap 语义）：kernel 在主流，H2D+scatter 在旁流；
  R3 实测 w16 下 hybrid 的 h2d_scatter_tail 仅 5.4µs，CPU 段基本被
  kernel 段藏住——这是 hybrid 能翻正的机制（实测，非推测）。

## 3. 层间流水（window 语义的生产映射）

bench 的 `--window 16`（每窗口 16 迭代共享一次同步，每迭代独占 staging
slot）压掉了 host 固定开销（copy0 69~114µs→5~7µs，-94%，R3 实测）。
生产映射不是「16 层共享同步」，而是：

- decode 每层一次 copy stage launch；**同步点放在 attention 之后、下一层
  selection 之前**（生产本来就有的层间依赖点），copy stage 的 launch →
  完成事件全部异步化，host 不逐层 sync。
- staging slot 数 = 在飞层数上限（≥2 即可流水，bench 用 16 是压测极端
  化；生产取 2~4 双/四缓冲即可，待 R6+ 实测标定）。
- 与 `fused_copy_sfa_c8` 的关系：融合 kernel 把 copy+QSFA 并成一次 MIX
  launch，层间流水点随之移到「融合 kernel launch 之后」。hybrid 的 CPU
  段仍可旁流先行（它不依赖融合 kernel），两段汇合于 attention 输入。

## 4. 系统配置（R4 实测写死）

- **pretouch 纳入默认**：DRAM 池镜像 + staging 在 worker 启动时全量摸页
  （R4 cards8 缺页实锤：cpu_gather -46.2%；小池无效应但无害）。生产中池
  是常驻的，pretouch 成本只付一次（启动期），稳态净赚。
- **THP 维持 madvise，严禁 always**（R4：THP=always 使 cards8 gather
  +31.7%、总时 +25.1%，显著有害）。
- **NUMA**：S5 未测，R6+ 候选（cpu_threads=8 的 NUMA 绑定收益未知，
  蓝图 runner 已支持 `--numa-nodes`）。

## 5. 风险与开放问题

1. **收益存疑**（最大风险）：R4 边际 +4.2~4.5% 与 run 噪声同量级，R5
   确认跑若翻回阴性，本稿整体不采用。
2. **cards4 不成立**：hybrid 优势目前仅 cards8 实测成立；cards4 未过锚
   （跨轮+漂移史）。生产部署若卡数 ≠8 需重新标定 cf。
3. **cards8 长尾**：copy300 档 avg_us_max/mean 最高 1.29（D 组），hybrid
   cf0.1 档最稳但也有 1.04→极端 run 的尾延迟行为未表征（R5 的 repeat 6
   会给 6 点分布）。
4. **融合 kernel 的切分代价未知（已降级为残留风险）**：读码确认融合算子
   尚无生产调用点，故独立 kernel 路径的 hybrid 集成不触及 MIX 形态问题；
   但若未来切到 `fused_copy_sfa_c8`，切分后 kernel 侧 rows 减 10% 对 MIX
   形态（copy 与 attention 的核内资源配比）的影响仍未测——届时需要一轮
   融合形态实测。
5. **ρ 敏感性**：breakeven 模型 ρ*（copy300）=0.25/0.20（cards1/8）——
   hybrid 收益前提是回搬量占池子的比例 ρ 足够低或 churn 稳态驻留够高；
   若业务 ρ 形态剧变（长上下文整体换入换出），结论需重估。

## 6. 验证路线（派单队列）

- R5（在途）：S2 弱阳性同轮高重复确认。
- R6 候选 a（R5 强阳性时）：vLLM 仓内独立 kernel 路径集成实测——
  两处调用点（runtime.py:944/:1044）接入行级切分（cf=0.1），e2e decode
  延迟对比不切分基线——生产化判决性实验。
- R6 候选 b（R5 翻回阴性时）：队列深度扫描（drafts/R5_queue_depth.md
  改编号）查 npu 侧余量。
- R6 候选 c（任意分支都可叠加）：pretouch 纳入默认配置后的复测 +
  NUMA 扫描（S5）。

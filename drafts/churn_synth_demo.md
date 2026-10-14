# churn 合成 trace 端到端演示（2026-10-15 蓝区）

> 性质：**合成数据**（tools/churn_synth.py，seed 固定可复现），用于验证
> 分析链路与探索参数敏感性，非实测。工具链：
> `churn_synth.py`（生成 jsonl）→ `churn_analysis.py`（ρ / LRU 驻留 /
> block 统计）→ `breakeven.py`（ρ → 时间收益，输入为 R1 实测值）。

## 场景 A：稳态漂移（keep=0.85, k=2048, hot_pool=16384, 500 步）

```text
adjacent-step overlap rho: mean=0.853 min=0.851 max=0.858
hot buffer 1x (cap 2048): hit_rate=0.451
hot buffer 1.5x (cap 3072): hit_rate=0.861
hot buffer 2x (cap 4096): hit_rate=0.872
hot buffer 3x (cap 6144): hit_rate=0.891
hot buffer 4x (cap 8192): hit_rate=0.912
blocks/step=128.0 tokens/touched-block=16.00
```

**发现 1（驻留容量非线性）**：相邻步 ρ=0.85，但 LRU 在 1x 容量只有
0.451 命中——按集合顺序处理的访问流下，LRU 在容量恰好等于 k 时会系统
性驱逐「本步还没访问到的幸存者」（级联 miss）。**1.5x 容量即恢复
0.861≈ρ**。含义：热池容量按 1.5~2x top-K 起配，1x 是病点；若有集合级
pin 机制（pin 当前步集合），可绕过该效应。这与 HiSparse 报告里
「热池 2~4×top-K 甜点」的方向一致（kvcache_report_tiered_hisparse.md）。

## 场景 B：相变（keep=0.9, hot_pool=8192, 每 200 步跳区, 1000 步）

```text
adjacent-step overlap rho: mean=0.900 min=0.000 max=0.907
hot buffer 1x (cap 2048): hit_rate=0.478
hot buffer 1.5x (cap 3072): hit_rate=0.913
hot buffer 2x (cap 4096): hit_rate=0.929
hot buffer 3x (cap 6144): hit_rate=0.958
hot buffer 4x (cap 8192): hit_rate=0.980
blocks/step=64.0 tokens/touched-block=32.00
```

**发现 2（相变只伤 min 不伤 mean）**：跳区步 ρ 瞬跌到 0（min=0.000），
但 1000 步里 5 次相变对 mean 几乎无感（0.900）。含义：驻留+增量方案
**必须带「低重叠步回退全量」的检测分支**（如 ρ_t < 阈值当步全量），
否则相变步会出现尾延迟尖刺；稳态收益不受相变频率的显著影响。

**发现 3（block 碎片度跟踪热池紧致性）**：hot_pool 8192→64 blocks/step
（32 tokens/block），16384→128 blocks/step（16 tokens/block）。若按
block（128 tokens）粒度抓取，抓取放大系数 = 128/tokens_per_block：
紧致热池（32/block）放大 4x，松散（16/block）放大 8x。这是
「按 token 增量 vs 按 block 增量」的成本轴。

## 与盈亏模型串联（合成 ρ → R1 实测参数）

ρ=0.85~0.9 落在 breakeven_r1_preview.md 的 ρ=0.8~0.9 区间：npu copy300
坐标预测加速 3.8~7.0x（模型反推值）。完整论证链已闭环：
合成/真实 trace → ρ 与驻留容量 → 拷贝时间收益。缺的真实输入仍是
**真实 indexer 的逐步 top-K dump**（向用户/绿区索取，jsonl 格式即
churn_analysis.py 的输入格式）。

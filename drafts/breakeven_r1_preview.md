# 盈亏模型预览（基于 R1 实测值，2026-10-15 蓝区）

> 性质标注：输入是 R1 交付附表的 **npu 实测 avg_us_mean**（12 坐标，
> 逐值转写为合成 case JSON，/tmp/r1_breakeven/，不入库）；输出全部为
> **模型反推值**（一阶线性模型，非实测）。cpu/hybrid 行待 R2 数据补齐
> （R1 主矩阵 cpu 侧崩溃无数据），交叉点 ρ* 暂缺。
>
> 模型：T_delta(ρ) = T0 + (1−ρ)(T_full − T0)，T0 = 同坐标 copy0 实测值
> （≈11µs 纯 launch 开销），假设节省量与被省 token 数严格成比例。

## 读数要点（全部为模型反推值）

- 单 die 边际成本 15.4~17.7 ns/token；cards≥4 跳到 24.9~30.5 ns/token
  ——聚合亚线性以「每 token 边际成本随 die 数上升」的形式显形，
  与共享链路竞争假设一致（R1 判读节观察）。
- copy300 坐标 ρ=0.9 时加速比 5.8×（cards1/2）~7.0×（cards4）；ρ=0.95
  达 8~10.5×。即驻留+增量路线即使只在 npu 路径上落地，高重叠下收益巨大。
- copy100 坐标同 ρ 下加速比明显更低（3.2~4.2×）：小 copy 数时 T0 固定
  开销占比大，驻留路线的相对收益被摊薄 —— 真实业务若 top-K 较小，
  收益预期要按 copy100 行而非 copy300 行估。
- 注意：本模型不含「集合层ρ真实分布」输入；ρ 的实际值要靠 churn 工具
  对真实/合成 trace 测量（tools/churn_analysis.py），两者合起来才是
  完整论证链。

## 工具输出原文

```text
cards1 bs24 npu copy100: T0=11.2us T_full=48.2us marginal=15.42ns/token
    rho=0.0  T_delta=    48.2us  speedup_vs_full= 1.00x
    rho=0.2  T_delta=    40.8us  speedup_vs_full= 1.18x
    rho=0.4  T_delta=    33.4us  speedup_vs_full= 1.44x
    rho=0.6  T_delta=    26.0us  speedup_vs_full= 1.85x
    rho=0.8  T_delta=    18.6us  speedup_vs_full= 2.59x
    rho=0.9  T_delta=    14.9us  speedup_vs_full= 3.23x
    rho=0.95 T_delta=    13.1us  speedup_vs_full= 3.69x
cards1 bs24 npu copy300: T0=11.2us T_full=138.7us marginal=17.71ns/token
    rho=0.0  T_delta=   138.7us  speedup_vs_full= 1.00x
    rho=0.2  T_delta=   113.2us  speedup_vs_full= 1.23x
    rho=0.4  T_delta=    87.7us  speedup_vs_full= 1.58x
    rho=0.6  T_delta=    62.2us  speedup_vs_full= 2.23x
    rho=0.8  T_delta=    36.7us  speedup_vs_full= 3.78x
    rho=0.9  T_delta=    24.0us  speedup_vs_full= 5.79x
    rho=0.95 T_delta=    17.6us  speedup_vs_full= 7.88x
cards2 bs24 npu copy100: T0=11.0us T_full=48.3us marginal=15.52ns/token
    rho=0.0  T_delta=    48.3us  speedup_vs_full= 1.00x
    rho=0.2  T_delta=    40.8us  speedup_vs_full= 1.18x
    rho=0.4  T_delta=    33.4us  speedup_vs_full= 1.45x
    rho=0.6  T_delta=    25.9us  speedup_vs_full= 1.86x
    rho=0.8  T_delta=    18.5us  speedup_vs_full= 2.61x
    rho=0.9  T_delta=    14.7us  speedup_vs_full= 3.28x
    rho=0.95 T_delta=    12.9us  speedup_vs_full= 3.75x
cards2 bs24 npu copy300: T0=11.0us T_full=138.8us marginal=17.75ns/token
    rho=0.0  T_delta=   138.8us  speedup_vs_full= 1.00x
    rho=0.2  T_delta=   113.3us  speedup_vs_full= 1.23x
    rho=0.4  T_delta=    87.7us  speedup_vs_full= 1.58x
    rho=0.6  T_delta=    62.1us  speedup_vs_full= 2.23x
    rho=0.8  T_delta=    36.6us  speedup_vs_full= 3.80x
    rho=0.9  T_delta=    23.8us  speedup_vs_full= 5.84x
    rho=0.95 T_delta=    17.4us  speedup_vs_full= 7.98x
cards4 bs24 npu copy100: T0=10.9us T_full=70.9us marginal=24.97ns/token
    rho=0.0  T_delta=    70.9us  speedup_vs_full= 1.00x
    rho=0.2  T_delta=    58.9us  speedup_vs_full= 1.20x
    rho=0.4  T_delta=    46.9us  speedup_vs_full= 1.51x
    rho=0.6  T_delta=    34.9us  speedup_vs_full= 2.03x
    rho=0.8  T_delta=    22.9us  speedup_vs_full= 3.09x
    rho=0.9  T_delta=    16.9us  speedup_vs_full= 4.18x
    rho=0.95 T_delta=    13.9us  speedup_vs_full= 5.08x
cards4 bs24 npu copy300: T0=10.9us T_full=230.4us marginal=30.48ns/token
    rho=0.0  T_delta=   230.4us  speedup_vs_full= 1.00x
    rho=0.2  T_delta=   186.5us  speedup_vs_full= 1.24x
    rho=0.4  T_delta=   142.6us  speedup_vs_full= 1.62x
    rho=0.6  T_delta=    98.7us  speedup_vs_full= 2.33x
    rho=0.8  T_delta=    54.8us  speedup_vs_full= 4.20x
    rho=0.9  T_delta=    32.9us  speedup_vs_full= 7.01x
    rho=0.95 T_delta=    21.9us  speedup_vs_full=10.51x
cards8 bs24 npu copy100: T0=11.9us T_full=71.7us marginal=24.89ns/token
    rho=0.0  T_delta=    71.7us  speedup_vs_full= 1.00x
    rho=0.2  T_delta=    59.7us  speedup_vs_full= 1.20x
    rho=0.4  T_delta=    47.8us  speedup_vs_full= 1.50x
    rho=0.6  T_delta=    35.8us  speedup_vs_full= 2.00x
    rho=0.8  T_delta=    23.9us  speedup_vs_full= 3.00x
    rho=0.9  T_delta=    17.9us  speedup_vs_full= 4.00x
    rho=0.95 T_delta=    14.9us  speedup_vs_full= 4.80x
cards8 bs24 npu copy300: T0=11.9us T_full=218.0us marginal=28.62ns/token
    rho=0.0  T_delta=   218.0us  speedup_vs_full= 1.00x
    rho=0.2  T_delta=   176.8us  speedup_vs_full= 1.23x
    rho=0.4  T_delta=   135.6us  speedup_vs_full= 1.61x
    rho=0.6  T_delta=    94.4us  speedup_vs_full= 2.31x
    rho=0.8  T_delta=    53.1us  speedup_vs_full= 4.10x
    rho=0.9  T_delta=    32.5us  speedup_vs_full= 6.70x
    rho=0.95 T_delta=    22.2us  speedup_vs_full= 9.81x
```

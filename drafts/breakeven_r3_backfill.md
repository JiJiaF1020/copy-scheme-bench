# 盈亏模型回填 v3（基于 R3 w16 实测值，2026-10-15 蓝区）

> 性质：输入为 R3 交付的 w16（cpu）+ anchor（npu）summary 表（pingpong.md
> §R3，**实测值**，经 tools/breakeven_table.py 解析）；输出为**模型反推值**。
> 本稿是 drafts/breakeven_r2_preview.md 末节「R3 后预测」的回填验证。

## 交叉点 ρ*（cpu-delta vs npu-full，w16 实测参数）

| cards | copy300（R2 实测 → R2 预测 w16 → **R3 实测**） |
|---|---|
| 1 | 0.64 → 0.37 → **0.32** |
| 4 | 0.18（漂移）→ — → **0.12**（cards4 档漂移仍在，证据弱） |
| 8 | 0.54 → — → **0.16** |

读法（模型反推值）：

- **预测方向兑现且优于预期**：R2 预览假设 w16 把 T0_cpu 压到 ~20µs（cards1）
  得 ρ*=0.37；实测 T0_cpu=5.1µs（w16 窗口化超预期），ρ*=0.32。churn 合成
  演示的稳态重叠区间 ρ=0.85~0.9 远超 ρ*，驻留+增量路线在 copy300 档的
  盈亏余量进一步扩大（R2 形态下余量 0.2~0.35，w16 形态 0.5~0.7）。
- **copy100 档从「结构性不胜」变为可胜**：R2 形态 cards1/2/8 均 ρ*>1；
  w16 形态 T0_cpu 5.1~6.6µs 已远低于 npu-full。本轮 anchor 无 copy100
  坐标，用 R2 的 npu copy100 值（跨轮，证据弱）估算：cards1 ρ*≈0.49、
  cards8 ρ*≈0.26（npu-full 48.5/70.3µs，span 84.6/85.5µs）。严格同轮值
  待 R5 补 copy100 锚点。注意这是 **delta 形态**的结论；cpu-full（ρ=0）
  仍输 npu-full（S1 未翻正不变）。
- 边际成本（实测，ns/token，copy300）：cpu w16 27.5/27.0/39.5/35.6
  （cards1/2/4/8），npu 17.8/—/34.1/29.3——cpu 边际仍高于 npu，
  盈亏优势完全来自 T0 差（5~7µs vs 11µs）与驻留省去的重复搬运。

## 工具修复记录

本轮回填暴露 tools/breakeven.py 的交叉点配对缺陷：`zip(sorted(npu_rows),
sorted(cpu_rows))` 在两方案 copy 集合不对称时错配（R3 锚点只有 copy300，
cpu 有 copy100+300，npu copy300 被配上 cpu copy100 的 span）。已改为按
copy_count 精确配对，回归测试 `test_breakeven_crossover_pairs_by_copy_count`
覆盖（自检 40 项全绿）。R2 预览的 ρ* 表不受影响（R2 两方案 copy 集合对称）。

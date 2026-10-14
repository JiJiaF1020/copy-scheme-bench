# §R6 派单候选稿（三分支，按 R5 判读选定其一，2026-10-15 蓝区）

> 状态：**候选，未派**。R5（S2 弱阳性确认跑）交付后按 §R5 判读预案的
> 三分支选定本稿之一派出。三稿共用前置核验与通过标准骨架，差异在命令
> 与判读预案。

## 共用前置核验（三分支通用）

1. 本仓 `git pull --ff-only` 后 `git log --oneline -1` 标题含「R6: §R6 派单」。
2. 蓝图仓 `git -C ../nanovllm-scatter_copy log --oneline -1` = `bb062d2`；
   `grep "QUEUE_DEPTH = " .../vllm_a5_kvcache_scatter_copy_c8.cpp` 显示 `= 8`
   （分支 C 例外，见该节）；未重编。
3. 四环境变量 grep 无匹配。

---

## 分支 A：R5 强阳性 ⇒ pretouch 组合正式配置复测

**目标**：R5 确认 S2 后，把 R4 实锤的 pretouch 收益叠加进 hybrid 正式
配置，产出「hybrid cf0.1 + w16 + pretouch」的正式配置数字（同轮 npu
anchor 对比），供生产形态设计稿（drafts/production_form_hybrid.md）
定稿引用。

```bash
cd /home/h2d_test/copy-scheme-bench && git pull --ff-only
cd tests && python3 test_scheme_tools.py && cd ..

bash run_scheme_sweep.sh --schemes hybrid --cpu-fracs 0.1 --hybrid-modes overlap \
  --cards 8 4 1 --batch-size 24 --copy-count 300 --window 16 --pretouch \
  --repeat 6 --results-dir results/r6/combo

bash run_scheme_sweep.sh --schemes npu --cards 8 4 1 --batch-size 24 \
  --copy-count 300 --window 16 --repeat 6 --results-dir results/r6/anchor

python3 tools/repeat_spread.py results/r6/combo results/r6/anchor \
  results/r5/confirm8 results/r5/confirm4 results/r5/anchor8 results/r5/anchor4
```

case 数：3×6 + 3×6 = 36（dry-run 派出前核验）。判读预案（派出时写死）：
combo cards8 ≥ 同轮 anchor×1.05 且 repeat_spread 无 UNSTABLE ⇒ 正式配置
成立，设计稿定稿；combo < anchor ⇒ pretouch 与 hybrid 叠加有干扰，
回退为「pretouch 仅 cpu 路径默认」。

## 分支 B：R5 弱阳性维持 ⇒ 累积证据 + NUMA 扫描（S5 首开）

**目标**：收益存疑状态下不加码生产投入，转两个低成本信息增益：
(a) hybrid cf0.1 cards8 copy300 再跑 repeat 8 累积分布证据；
(b) NUMA 绑定扫描（S5 从未测过）：`--numa-nodes` 提供后 sweep 自动对
每个 case 跑不绑定/绑定两遍（命名带 `_numa` 后缀），查 CPU 路径 DRAM
访问是否跨 NUMA 掉速。worker 侧绑定命令为
`numactl --cpunodebind=<node> --membind=<node>`（按 rank 取节点号，
run_scheme_multiprocess.py:124-126）。

```bash
cd /home/h2d_test/copy-scheme-bench && git pull --ff-only
cd tests && python3 test_scheme_tools.py && cd ..

numactl -H

bash run_scheme_sweep.sh --schemes hybrid --cpu-fracs 0.1 --hybrid-modes overlap \
  --cards 8 --batch-size 24 --copy-count 300 --window 16 --repeat 8 \
  --results-dir results/r6/accum8

# "<NODES>" = 上一步 numactl -H 输出的节点清单（单个引号字符串，空格分隔，
# 如 "0 1 2 3 4 5 6 7"——argparse 单参数，引号不可省）；
# 节点数必须 >= 8（max cards），不足则把 --cards 降为不超过节点数的最大值并在交付中注明
bash run_scheme_sweep.sh --schemes cpu --cards 8 1 --batch-size 24 \
  --copy-count 300 --window 16 --numa-nodes "<NODES>" --repeat 3 \
  --results-dir results/r6/numa

python3 tools/repeat_spread.py results/r6/accum8 results/r5/confirm8
```

case 数：8 + (2 cards × 2 绑定态 × 3) = 20（dry-run 派出前核验）。
判读预案（派出时写死）：accum8 与 R5 confirm8 同坐标合并后 cf0.1 分布
的均值/极差是否过 anchor×1.05 ⇒ 升级/维持弱阳性；numa 组同坐标
`_numa` vs 不绑定偏差 >10% ⇒ NUMA 实锤，纳入正式配置。

## 分支 C：R5 翻回阴性 ⇒ 队列深度扫描（drafts/R5_queue_depth.md 改编号派出）

**目标**：S2 证伪后回到 npu 侧余量——QUEUE_DEPTH ∈ {4, 8, 16} ×
cards{1,4,8} × copy{100,300} × repeat 3，54 case。命令、判读预案全文
已在 drafts/R5_queue_depth.md 定稿平铺（自检项数派出时刷新为当时实际
值、results 前缀改 r6、蓝图仓前置核验改为「按 build_queue_depth.sh
流程逐组重编」）。

---

## 公共回传要求（三分支都加）

除常规模板外：每组跑完附 `python3 tools/repeat_spread.py <本组目录>`
输出原文（repeat 极差是 R5 起判读的一等公民）。

# §R3 派单草稿：pretouch × THP 二因素实验（host 内存路径调优）

> 状态：**草稿，未派**。合 main 前按 R2 实测数据定稿坐标（`[定稿]` 处），
> 写进 pingpong.md 才算生效；本文件只作蓝区工作底稿。
>
> 依赖：worker/sweep/runner 的 `--pretouch` 已全链路就绪（wip-r3-prep
> commit 9e34ff8）；`--repeat N` 提供 run 级波动控制；worker 输出迭代级
> 分位数（p50/p90/p99），三者都在本轮自检覆盖（30 项绿）。

## 目标

判定 cpu 路径的 host 侧成本里，**缺页/TLB 未命中**占多大份额；若显著，
THP+pretouch 是零侵入修复，直接改变 S1 裁决的结论强度。

## 背景与假设（蓝区推理，绿区不评判）

- R1 冒烟（cards1/bs24/copy100）：cpu avg 192.4µs 中 cpu_gather=47.9µs
  （≈20ns/行）、h2d_scatter=72.4µs、**未归类 host 开销 ~72µs（37%）**。
- H1（缺页）：DRAM 池每 die ~1GiB，首次访问的 minor fault 若落在计时区
  内会抬高均值与尾部。warmup 应已消化，但未归类开销来源未证实。
  pretouch（每 4K 页一次读写）把 fault 移出计时区。
- H2（TLB）：随机行访问 1GiB 池 = 26 万个 4K 页的 TLB 足迹；THP(2M) 后
  仅 512 个表项。gather 相位（20ns/行）若有 TLB 成分，THP 应直接压低。
- H0（对照）：npu 方案不吃 host 页属性，若 npu 坐标随 THP 漂移说明
  测量被系统设置污染 ⇒ 本轮 THP 数据作废（写死）。

## 设计（2×2，全部同轮跑，跨轮不对比）

| 组 | pretouch | THP(enabled/defrag) | 结果目录 |
|----|----------|---------------------|----------|
| A  | 否       | 保持原值             | results/r3/a_base |
| B  | 是       | 保持原值             | results/r3/b_pretouch |
| C  | 否       | always/always        | results/r3/c_thp |
| D  | 是       | always/always        | results/r3/d_both |

- 坐标 `[定稿：默认 cards∈{1,8} × bs24 × copy∈{0,300} × schemes∈{npu,cpu}，
  --iters 200 --repeat 3；R2 落地后若差距最大坐标不同则替换]`。
  copy=0 提供 T0（固定开销锚点），copy=300 是负载坐标；npu 作 H0 对照。
- 每组 2×1×2×2×3 = 24 case，四组共 96 case-run。
- hybrid 本轮不测（先看纯 cpu 能不能救，再决定 hybrid 值不值得复试）。

## 执行命令（定稿时逐字化，绿区逐字执行）

```bash
cd /home/h2d_test/copy-scheme-bench && git pull --ff-only
cd tests && python3 test_scheme_tools.py && cd ..   # 30 项 OK

# 记录 THP 原值（回传）
cat /sys/kernel/mm/transparent_hugepage/enabled
cat /sys/kernel/mm/transparent_hugepage/defrag

COMMON="--cards 1 8 --batch-size 24 --copy-count 0 300 --schemes npu cpu --iters 200 --repeat 3"

bash run_scheme_sweep.sh $COMMON --results-dir results/r3/a_base
bash run_scheme_sweep.sh $COMMON --pretouch --results-dir results/r3/b_pretouch

echo always > /sys/kernel/mm/transparent_hugepage/enabled
echo always > /sys/kernel/mm/transparent_hugepage/defrag
cat /sys/kernel/mm/transparent_hugepage/enabled    # 回传确认

bash run_scheme_sweep.sh $COMMON --results-dir results/r3/c_thp
bash run_scheme_sweep.sh $COMMON --pretouch --results-dir results/r3/d_both

# 恢复原值（按上面 cat 出的原样写回，例：）
echo madvise > /sys/kernel/mm/transparent_hugepage/enabled   # 或原值
echo madvise > /sys/kernel/mm/transparent_hugepage/defrag    # 或原值
```

注：绿区为宿主 root，直接写 /sys 即可；若写 /sys 被拒（容器映射只读），
原样回传报错，本轮改为只跑 A/B 两组并在交付中注明。

## 通过标准（草稿）

- R3-G1：自检 30 项 OK。
- R3-G2：四个 manifest 全 passed，96 个 case JSON correctness 全 true。
- R3-G3：THP 切换的两条 cat 回传与设置一致（C/D 组期间确实是 always）。
- R3-G4（对照）：npu 坐标四组间带宽偏差 ≤5%；超出 ⇒ THP 数据作废（H0 触发）。

## 判读预案（草稿，派单时写死）

- cpu_gather 相位在 C/D 组相对 A 组下降 >10% ⇒ **TLB 成分实锤**，THP 列入
  正式方案配置；未归类 host 开销在 B/D 组下降 >30% ⇒ 缺页成分实锤，
  pretouch 列入正式配置。
- 两者都无变化 ⇒ host 开销既非缺页也非 TLB，转向 H3（launch/同步次数）
  ⇒ R4 走 host 开销压减（合并 launch、图捕获）而非队列深度。
- npu 对照漂移 ⇒ 只信 A/B（不动 /sys 的两组）。
- 所有比较用同轮分位数（p50）与 run 级 std，不看单点均值；std/均值 >10%
  的坐标在结论中标注「波动大，证据弱」。

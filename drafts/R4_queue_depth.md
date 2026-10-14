# §R4 派单草稿：kernel 队列深度扫描（npu 路径，QUEUE_DEPTH 4/8/16）

> 状态：**草稿，未派**。R4 的实际内容取决于 R2/R3 判读，存在三个候选方向
> （见末节「方向分支」）；本稿写死的是「队列深度扫描」这个候选的执行细节。
> 合 main 前按最新一轮数据定稿，写进 pingpong.md 才算生效。

## 目标

判定 npu 路径在 ≥4 die 的聚合亚线性（R1 实测：1→2 die 线性，
2→4 die 仅 1.36×，单 die 34→21 GB/s）是否与 kernel 内队列深度相关；
若相关，QUEUE_DEPTH=16 是零成本增益。

## 背景

- 蓝图 kernel `QUEUE_DEPTH` 当前 = 8（side_blueprint 补丁从 2 改到 8，
  构建产物在绿区 `_custom_opp_c8/`）。
- `tools/build_queue_depth.sh <D>`：sed 改常量 → 重跑蓝图 `build_c8.sh`
  → 提示 `export SCATTER_C8_QUEUE_DEPTH=<D>`（结果 JSON 与 manifest 都会
  带上该 tag，跨组可溯源）。
- 蓝区已知（macOS 静态检查）：`build_queue_depth.sh` 的 sed 锚点是
  `constexpr uint32_t QUEUE_DEPTH = <n>;`，前置核验用 grep 验证。

## 设计（单因素三水平，同轮顺序执行）

- D ∈ {4, 16}，与存量 8（R1/R2 已测，但**仍需本轮重测一次 8 作锚点**，
  跨轮不对比）共三组。
- 坐标 `[定稿：默认 cards∈{1,4,8} × bs24 × copy∈{100,300} × schemes=npu，
  --iters 200 --repeat 3]`（cards4/8 是亚线性事发坐标；cards1 验证
  单 die 不受队列深度影响——若单 die 也动，说明改的是 kernel 本身行为
  而非并发深度）。
- 每组 3×1×2×3 = 18 case，三组共 54 case-run。
- 全部跑完后恢复 QUEUE_DEPTH=8 并重编（收尾命令写进任务书）。

## 执行命令（定稿时逐字化）

```bash
cd /home/h2d_test/copy-scheme-bench && git pull --ff-only
cd tests && python3 test_scheme_tools.py && cd ..

for D in 4 8 16; do
  tools/build_queue_depth.sh $D            # 内部：改常量+重编+grep 校验
  export SCATTER_C8_QUEUE_DEPTH=$D
  bash run_scheme_sweep.sh --cards 1 4 8 --batch-size 24 \
    --copy-count 100 300 --schemes npu --iters 200 --repeat 3 \
    --results-dir results/r4/qd$D
done

tools/build_queue_depth.sh 8               # 恢复
unset SCATTER_C8_QUEUE_DEPTH
```

（`for` 循环若不合「逐字执行」纪律，定稿时展开成三组平铺命令。）

## 通过标准（草稿）

- R4-G1：自检 30 项 OK；每次 build_queue_depth.sh 后 grep 输出
  `QUEUE_DEPTH = <D>` 与目标一致。
- R4-G2：三个 manifest 全 passed，54 个 case correctness 全 true，
  每个 JSON 的 `queue_depth` 字段与组一致（防 tag 串组）。
- R4-G3：D=8 锚点组与 R2 同坐标偏差 ≤15%（跨轮一致性，非门槛）。

## 判读预案（草稿，派单时写死）

- cards8/copy300：qd16 相对 qd8 提升 >5% 且 qd4 相对 qd8 下降 >5%
  ⇒ **队列深度敏感实锤**，取 16 为正式配置，并可再派 24/32 探顶。
- 三者两两偏差 ≤5% ⇒ 队列不敏感，亚线性归因转向 die 间共享链路竞争，
  npu 路径优化空间到顶，资源转投 cpu/hybrid 路径或集合层（churn）方向。
- 单 die（cards1）也随 D 显著变化 ⇒ kernel 行为被常量改变，结论降级为
  「kernel 内部行为变化」，不与并发深度挂钩。

## 方向分支（R4 派什么，由 R3 判读决定，优先级从高到低）

1. **R3 host 压减无效（w16 未归类仍 >30%）** ⇒ cpu 路径判死，R4 转集合层：
   churn 轴负载（`tools/churn_synth.py` 已就绪，演示见
   `drafts/churn_synth_demo.md`）+ 盈亏模型定 ρ*。
2. **R3 host 压减有效但仍 < npu** ⇒ R4 = 本稿（队列深度 4/8/16，查 npu 侧
   还能挖多少）或 pretouch×THP（`drafts/R3_pretouch_thp.md`，查 gather
   相位的 TLB/缺页成分）。
3. **R3 S1 翻正（w16 cpu ≥ npu at cards4/8）** ⇒ R4 = 生产形态评估：
   窗口化流水如何嵌入 vLLM 层间流水（蓝区先出设计稿，非纯 bench）。

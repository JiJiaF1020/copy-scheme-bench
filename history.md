# History

蓝绿协作轮次档案。只追加，不修改。每轮至少记录：派单 commit、执行环境、原始数据出处、判读结论与置信度。

## 轮次记录格式

```
## §R<n> <标题>（<日期>）

**派单**（commit <id>）：<一句话任务 + 判读通过标准>
**交付**（commit <id>）：<一句话结果 + 数据出处>
**判读**（蓝区）：<阳性/阴性/无效 + 依据 + 下一步>
```

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
**交付**（commit 本轮 push 后回填）：R2-G1 自检 22 tests OK；R2-G2 定点回归 4 case 全 passed（cpu copy0=68.505µs / copy100=187.589µs=8.393 GB/s；hybrid copy0=109.968µs / copy100=257.277µs=6.119 GB/s，correctness 全 true，cpu×copy0 无 AttributeError）；R2-G3 主矩阵 60 case 全 passed（manifest passed、case_count=60、correctness 全 true）；R2-G4 npu 12 坐标 vs §R1 附表偏差——cards1/2/8 ≤3.72%，cards4 档 copy100=66.662(25.01%)/copy300=65.714(19.89%) 超 15% ⇒ 环境漂移，npu 基线跨轮不可比，一切对比以 R2 轮内坐标为准。数据出处：results/r2_regression/ + results/copy_scheme_a5_c8/（gitignore 不入库）。
**判读**：待交付后蓝区填写。

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

# copy-scheme-bench — DRAM→HBM 离散搬运方案对比测试

以 `nanovllm-scatter_copy/tests/` 的多进程带宽测试为蓝本，回答一个问题：
**离散 token 的 DRAM→HBM 回搬，走哪条路径最快？**

被测对象：C8 packed KV cache，每 token 656 字节，`src_ids/dst_slots/copy_counts`
元数据语义与蓝图完全一致（BLOCK=128、COPY_CAP=16384、-1 填充、row0/row1 钉住
copy_min/max、私有目标块 + 1 守卫块、POISON 全字节校验、零拷贝校验、元数据只读校验）。

## 方案矩阵

| 编号 | 方案 | 实现 | 想验证什么 |
| --- | --- | --- | --- |
| S0 | NPU 直读（基线） | 现有 `kvcache_scatter_copy_c8` kernel，深度 8 MTE2 队列，每行一次 PCIe 随机读 | 基线；蓝图同口径数字可直接对比 |
| S1 | CPU gather | CPU 从 DRAM 池镜像多线程 gather 到 pinned 连续 buffer → 一次大块 H2D → 设备侧 `index_copy_` 散到目标槽 | CPU 读 DRAM 不过 PCIe；把 N 次 PCIe 小包换成 1 次大块顺序 H2D |
| S2 | 混合分流 | 每行前 `1-cpu_frac` 走 kernel、尾部走 CPU 路径；`overlap` 模式下 kernel 在主流、H2D+scatter 在旁流并发 | PCIe 小包（kernel）与 DMA 大包（H2D）能否互相藏起来 |
| S3 | 连续性扫描 | 同一 kernel，`--run-frac` 控制源 token 相邻对比例 | 离散负载有多少性能是"局部性差"罚掉的；上限在哪 |
| S4 | 队列深度 | `tools/build_queue_depth.sh N` 重编 kernel（4/8/16） | MTE2 在飞读数是否瓶颈 |
| S5 | NUMA | `--numa-nodes` 对每个 case 跑绑定/不绑定两遍 | CPU 路径的 DRAM 访问是否跨 NUMA 掉速 |
| S6 | 预热 | `--pretouch` 提前摸 DRAM 镜像与 staging 每一页 | 缺页/TLB 对 CPU 路径的影响 |

S0 的计时与蓝图完全兼容（NPU Event 包住 iters 次异步 launch），并额外记录
每次 launch 后同步的 host 墙钟 `avg_us_host_synced`；S1/S2 用
`perf_counter` 测端到端（gather / H2D+scatter 相位分解在 JSON 的
`performance.phases` 里）。对比时请注意：S0 的 event 数字是流水化吞吐，
S1/S2 是逐迭代串行延迟——两者都给出，判读时先说口径再下结论。

## 目录

```
copy-scheme-bench/
├── run_scheme_sweep.sh          # A5 入口：source CANN + 调用 sweep
├── tools/build_queue_depth.sh   # S4：改 QUEUE_DEPTH 重编蓝图 kernel
├── tools/churn_analysis.py      # 集合层：top-K trace 的 ρ/LRU 驻留/block 统计
├── tools/churn_synth.py         # 集合层：合成 top-K trace 生成器（ρ/热池/相变/层数）
├── tools/breakeven.py           # 盈亏模型：T_delta(ρ) 与 cpu-delta vs npu-full 交叉点
├── tools/breakeven_table.py     # 盈亏模型的 md 汇总表直读前端（交付判读用）
├── tools/repeat_spread.py       # repeat 极差表：逐坐标 (max-min)/min，>10% 标 UNSTABLE（可回溯分析历史结果目录）
└── tests/
    ├── _bootstrap.py            # 定位蓝图仓（SCATTER_ROOT），复用其六列口径
    ├── scheme_config.py         # 测试名/方案名/环境变量名
    ├── scheme_workload.py       # 纯 stdlib：负载生成(run-frac)、物理行解析、参考 gather、hybrid 切分
    ├── scheme_churn.py          # 纯 stdlib：trace 解析、相邻步重叠、LRU 驻留模拟
    ├── scheme_churn_synth.py    # 纯 stdlib：合成 trace（几何漂移 + 相变跳区 + 多层）
    ├── scheme_report.py         # 带 scheme 列的归一化与汇总；重复坐标折叠（mean + n_runs + std）
    ├── test_scheme_worker.py    # 单卡 worker：npu/cpu/hybrid 三方案，迭代级分位数（torch 延迟导入）
    ├── run_scheme_multiprocess.py  # 多 die runner：两阶段文件握手，NUMA 绑定
    ├── run_scheme_sweep.py      # 矩阵 sweep：dry-run 免 NPU；--repeat N 做 run 级波动控制
    └── test_scheme_tools.py     # macOS 自检（47 项，无 torch 依赖）
```

口径单一来源：六列数学、`validate_workload`、常量全部 import 自蓝图仓
（`SCATTER_ROOT` 指向，默认 `../nanovllm-scatter_copy`），本仓不复制。

## 开发机自检（macOS，无 NPU）

```bash
cd copy-scheme-bench/tests && python3 test_scheme_tools.py
bash ../run_scheme_sweep.sh --dry-run --cards 1 2 --batch-size 24 --copy-count 0 300
```

## A5 上机一把跑

前置（只需一次）：

```bash
# 两个仓并排放在同一目录下
bash nanovllm-scatter_copy/build_c8.sh          # 出 _custom_opp_c8 与 vllm_dsa_a5
cd copy-scheme-bench/tests && python3 test_scheme_tools.py   # 冒烟：纯 CPU 自检
```

1) 主矩阵（S0 vs S1 vs S2，含 cpu_frac 0.25/0.5/0.75）：

```bash
bash copy-scheme-bench/run_scheme_sweep.sh
# 默认：schemes="npu cpu hybrid"，cards≤可见die数，bs=24，copy=0/100/300
```

2) 连续性扫描（S3，测局部性上限）：

```bash
bash copy-scheme-bench/run_scheme_sweep.sh \
  --schemes npu --run-fracs 0 0.3 0.6 0.9 1.0 --cards 1 2 4 8
```

3) NUMA（S5，每个 case 自动跑绑定/不绑定两遍）：

```bash
lscpu | grep -i numa     # 先确认节点数，例如 4 节点
bash copy-scheme-bench/run_scheme_sweep.sh --numa-nodes "0 1 2 3" --schemes npu cpu
```

4) 队列深度（S4，需要重编 kernel；深度间不能并行，想并行就开两份蓝图仓）：

```bash
SCATTER_C8_QUEUE_DEPTH=8  copy-scheme-bench/tools/build_queue_depth.sh 8
bash copy-scheme-bench/run_scheme_sweep.sh --schemes npu --results-dir results/qd8
export SCATTER_C8_QUEUE_DEPTH=16   # 之后的 sweep 结果都会带上这个 tag
copy-scheme-bench/tools/build_queue_depth.sh 16
bash copy-scheme-bench/run_scheme_sweep.sh --schemes npu --results-dir results/qd16
copy-scheme-bench/tools/build_queue_depth.sh 8   # 用完恢复
```

5) 预热（S6）：任意命令追加 `--pretouch`。

结果：`results/copy_scheme_a5_c8/` 下每个 case 一个 JSON + 日志，sweep 结束自动
产出 `copy_scheme_timing_summary.{csv,md}` 和 `copy_scheme_summary.json`，列为
`scheme run_frac cpu_frac hybrid_mode cards batch_size copy_count avg_us_mean avg_us_max avg_bandwidth`
（带宽口径与蓝图相同：十进制 GB/s，多 die 为各 die 速率之和）。

## 判读表

| 观察 | 结论 |
| --- | --- |
| S1(cpu) 端到端 ≥ S0(npu) | 瓶颈在"每行一次 PCIe 小包往返"，kernel 微优化（S4）空间也有限 |
| S1 的 `cpu_gather_us` 占比极小、`device_wall_us` 接近理论 H2D 带宽 | CPU gather 假设成立，值得往 vLLM 侧集成 |
| S1 gather 慢 | CPU 侧是瓶颈：加 `--cpu-threads`、开 S5 NUMA、开 S6 pretouch 再测 |
| S2 overlap < 两条路径各自的串行时间之和 | 两条 PCIe 路径能并发，生产上按负载动态分流 |
| S3 run_frac 越高带宽越陡 | 性能对局部性敏感；若业务真有局部性（连续段），值得在模式层聚合 |
| S3 曲线平 | 纯 PCIe 小包延迟受限，聚合也没用，方向只剩换路径（S1/S2） |
| S4 depth 16 明显快于 8 | MTE2 在飞读数是瓶颈，kernel 还有一段免费空间 |
| S5 绑定后 CPU 路径变快 | 生产部署必须做 NUMA 绑定 |

## 实测结论（2026-10-15，A5 / 8×Ascend950DT）

- **S2 hybrid 在甜区成立**：cards8、bs24~32、每请求 miss ≥300 token 时，
  cf=0.1 + window16 + pretouch + NUMA 绑定形态较纯 kernel 稳定 **+6.8~10.5%**
  （repeat 极差 ≤1%，字节级校验全过）。甜区外必须回退纯 kernel：copy100
  档 hybrid 只有 kernel 的 ~57%（overlap 固定开销主导）——集成需按 miss
  数门控，拐点在 200~300 之间。
- **三件套是前提不是锦上添花**：无 window 时 host 固定开销 69~114µs/迭代
  （window16 后 5~7µs）；无 pretouch 时 cards8 gather 段慢 46%；无 NUMA
  绑定时 CPU 路径 run 级极差 29%（绑定后 9.5%，均值 +23%）。THP=always
  有害，维持 madvise。
- **S1 cpu 全量出局**：copy2048 档绑定态也塌到 115 GB/s（kernel 163），
  全量 CPU gather 只适合作对照；cpu-delta（只搬 miss 增量）不受此限。
- **S0 kernel 基线水平**：cards8/bs32 离散 656B 随机读 ≈163~175 GB/s
  （8 卡聚合），与蓝图 `run_scatter_copy_multiprocess.sh` 同坐标差 ≤5%
  （两 harness 互证，无改写回归）。

## 集合层分析（驻留+增量方向）

搬运路径之外的第二个方向：top-K 集合相邻步重叠 ρ 高时，每步只搬差集。
本仓自带纯 stdlib 工具链（无 NPU 依赖）：

```bash
python3 tools/churn_synth.py --steps 500 --k 2048 --keep 0.85 --out trace.jsonl  # 或真实 indexer dump（同格式 jsonl）
python3 tools/churn_analysis.py trace.jsonl        # ρ、LRU 驻留命中率、block 碎片度
python3 tools/breakeven.py results/copy_scheme_a5_c8  # T_delta(ρ) 与 cpu-delta vs npu-full 交叉点
python3 tools/breakeven_table.py summary.md           # 同上，但输入是粘贴的 md 汇总表（交付判读用）
```

结论：LRU@1x 是病点、热池按 1.5~2x top-K 起配、相变步需回退全量。

## 口径与限制

- CPU 路径从 **DRAM 池的 CPU 镜像**（初始化 swapped 池的同一份数据）读取；
  物理访问形态与生产一致（CPU 读本机 DRAM），NUMA 放置由 numactl 显式控制。
- `pin_memory` 失败时 worker 自动退化为普通内存并在 JSON 记
  `staging_pinned=false`（H2D 会慢一截，看结果时先查这个字段）。
- S4 的 queue depth 记录在 case JSON 的 `config.queue_depth`，但同一时刻一台
  机器只有一份 OPP 生效；不同深度的结果务必分目录存放（上面的命令已示范）。
- `--allow-non-a5` 仅供调试，不算验收。

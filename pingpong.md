# Pingpong

## Protocol

- 本文件是蓝区 ↔ 绿区的唯一通信面；`history.md` 是只追加的轮次档案。
- **蓝区**（可外部 AI 侧）写全部代码、做全部判读决策；**绿区**（隔离执行侧）按任务书执行并回写交付，不改代码。
- 每次 commit 必须同时包含代码 + `pingpong.md` + `history.md`；pull 用 `--ff-only`；绝不 force-push。
- Current owner: **绿区**。Status: R1 派单已发出，等待交付。

## 0. 目标与口径

**唯一目标**：在 A5（Ascend 950）上判定离散 C8 token 的 DRAM→HBM 回搬最优路径——
NPU kernel 直读（基线）/ CPU gather + 大块 H2D / 两者混合分流——产出可用于
vLLM 集成决策的带宽对比数据。

**锚点**：

- 蓝图仓 `nanovllm-scatter_copy`，分支 `scatter_copy_a5_c8`，origin tip `bb062d2`
  （"Unify scatter bandwidth test CLI and six-column results"）。
- 蓝图仓必须叠加本仓 `side_blueprint/blueprint_wip_queue8_numa.patch`
  （内容：kernel `QUEUE_DEPTH` 2→8 + runner 的 NUMA 绑定支持；蓝区已验证
  `git apply --check` 干净）。历史上已测的 C8 带宽曲线对应 depth=8。
- payload 口径：每 token 656 字节（C8 packed）；BLOCK=128；COPY_CAP=16384。

**测量口径（写死，不移动）**：

- 带宽 = `payload_bytes / avg_us`，十进制 GB/s；`payload_bytes = copied_tokens × 656`。
- 多 die 带宽 = 各 die 速率之和（不用 mean/max 反推）；延迟列给 `avg_us_mean` / `avg_us_max`。
- `npu` 方案 `avg_us` 是 NPU Event 包 iters 次异步 launch 的流水吞吐（与蓝图既有
  数字同口径，可直接对表）；其 `performance.avg_us_host_synced` 是逐迭代同步墙钟。
- `cpu`/`hybrid` 方案 `avg_us` 是逐迭代 host 墙钟（每迭代末 sync），相位分解在
  `performance.phases`。
- 对比只在**同机、同轮、同 cards/bs/copy 坐标**之间有效；跨机器/跨会话绝对值不可比。
- 正确性门槛先于性能：任何 case 的 correctness 非全 true，该 case 数据无效。

---

## §R1 派单：A5 首轮主矩阵（2026-10-14，蓝区）

### 目标

回答"离散 token 回搬走哪条路径最快"，并校准本 bench 在 A5 上可运行：先自检与
双方案冒烟，过了再跑默认主矩阵（npu / cpu / hybrid×{0.25,0.5,0.75}）。

### 前置核验

1. 两个仓并排克隆在同一父目录下（`_bootstrap` 依赖 `../nanovllm-scatter_copy` 相对路径）：
   - 蓝图仓：分支 `scatter_copy_a5_c8`，`git log --oneline -1` = `bb062d2`；
   - 本仓：分支 `main`，`git log --oneline -1` 标题为
     "init: copy-scheme-bench + 蓝绿 pingpong + §R1 派单"（单 commit 即全部）。
2. 蓝图仓补丁已贴：`git -C nanovllm-scatter_copy status -s` 显示两个 M 文件
   （kernel + multiprocess runner），且
   `grep "QUEUE_DEPTH =" nanovllm-scatter_copy/csrc/src/kvcache_scatter_copy_c8/op_kernel/vllm_a5_kvcache_scatter_copy_c8.cpp`
   输出 `constexpr uint32_t QUEUE_DEPTH = 8;`。
3. CANN 环境可 source：`/usr/local/Ascend/ascend-toolkit/latest/set_env.sh` 存在。
4. `npu-smi info` 可见 8 个 die；`python3 -c "import torch, torch_npu"` 无报错。
5. 环境无残留：`ASCEND_CUSTOM_OPP_PATH` / `NANOVLLM_A5_INSTALL_OPP_PATH` /
   `NANOVLLM_CUST_OPAPI_LIB` / `SCATTER_C8_NUMA_NODES` 均未设置（env 输出为空）。

### 执行命令

逐字执行（`<PARENT>` = 两仓的共同父目录）：

```bash
cd <PARENT>
git clone -b scatter_copy_a5_c8 https://github.com/xieqiang-hw/nanovllm-DSA-offload_scatter_copy.git nanovllm-scatter_copy
git clone -b main git@github.com:JiJiaF1020/copy-scheme-bench.git copy-scheme-bench
cd nanovllm-scatter_copy
git apply --check ../copy-scheme-bench/side_blueprint/blueprint_wip_queue8_numa.patch
git apply ../copy-scheme-bench/side_blueprint/blueprint_wip_queue8_numa.patch
grep "QUEUE_DEPTH =" csrc/src/kvcache_scatter_copy_c8/op_kernel/vllm_a5_kvcache_scatter_copy_c8.cpp
bash build_c8.sh
cd <PARENT>
cd copy-scheme-bench/tests && python3 test_scheme_tools.py && cd <PARENT>
# 冒烟：单 die、双方案、短迭代
bash copy-scheme-bench/run_scheme_sweep.sh --cards 1 --batch-size 24 --copy-count 100 \
  --schemes npu cpu --iters 200 --results-dir copy-scheme-bench/results/smoke
# 主矩阵（默认 schemes="npu cpu hybrid"、cpu-fracs 0.25/0.5/0.75、cards 1/2/4/8、copy 0/100/300）
bash copy-scheme-bench/run_scheme_sweep.sh
```

### 通过标准

- G1：`build_c8.sh` 退出码 0，输出含 `[c8_build] torch extension import: OK`。
- G2：前置核验第 2 条的 grep 输出为 `QUEUE_DEPTH = 8`。
- G3：`test_scheme_tools.py` 末两行输出 `Ran 21 tests` 与 `OK`。
- G4：冒烟 2 个 case JSON（`results/smoke/npu_*.json`、`cpu_*.json`）
  `status=="passed"` 且 `correctness` 全 true。
- G5：主矩阵 `results/copy_scheme_a5_c8/copy_scheme_run_manifest.json`
  `status=="passed"`；`copy_scheme_summary.json` 存在且 `case_count==60`
  （4 cards × 3 copy × [npu + cpu + hybrid×3]）；每个 case JSON correctness 全 true。
- G6（sanity，非验收门槛）：`npu` 方案 cards1/bs24/copy100 的 `avg_bandwidth`
  与该机历史 C8 带宽曲线同量级；偏差 >30% 时原样回传并注明，由蓝区判断环境
  是否有问题（不自行重跑调参）。

### 回传格式

按根目录 `AGENTS.md` 的交付模板写回本文件 §R1 下方，并原样附上：

1. `copy_scheme_timing_summary.md` 全文（主矩阵六列+方案坐标表）；
2. `copy_scheme_run_manifest.json` 全文；
3. 冒烟两个 case JSON 全文；
4. 若任何一步失败：该步 stderr/日志末 30 行原文，停止后续步骤照常交付。
5. 结果目录在 `.gitignore` 内不入库；只回写 `pingpong.md`（和 `history.md` 追加一行）。

### 判读预案（派单时写死）

- 若 `cpu` 方案 `avg_bandwidth` 在 copy=300 的全部 cards 坐标上 ≥ 同坐标 `npu`
  ⇒ **S1 阳性**：CPU gather+H2D 路径成立，下一轮做 hybrid 细分与生产集成评估。
- 若 `cpu` 全坐标 < `npu`，且其 `phases.cpu_gather_us` 占 `avg_us` 主导
  ⇒ **S1 阴性**：瓶颈在 CPU 侧 gather，该方向收摊，下一轮转 S4（队列深度）。
- 若 `cpu` < `npu` 但 `cpu_gather_us` 占比小、`h2d_scatter_us` 主导
  ⇒ 瓶颈在 DMA/H2D 段：方向是减小 H2D 量（hybrid 小 frac），不是换路径。
- 若 `hybrid`（overlap）`avg_us` < 同坐标 min(npu, cpu) ⇒ 两条 PCIe 路径可并发，
  记 **S2 阳性候选**，下一轮扫更细 frac。
- 任一 case correctness 失败 ⇒ 该 case 无效（不影响其他坐标判读）；
  G1–G3 任一失败 ⇒ **整轮无效**，蓝区诊断后重新派单。

---

（新轮次从这里往下追加：蓝区写「派单」节，绿区写「交付」节，蓝区写「判读」节。最新一轮在最上面，旧轮次标题加「-旧」标记。）

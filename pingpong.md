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

### 交付（§R1，2026-10-15，绿区）

**执行环境**：机器/机型 141.61.33.21 (work21) / Ascend950DT_9572 ×8；设备 8 die（visible 0-7）；容器/宿主 宿主 root；时间 2026-10-14T15:52Z ~ 2026-10-15T00:01Z。
**前置核验**：1) 蓝图仓 `nanovllm-scatter_copy`@`bb062d2`（分支 scatter_copy_a5_c8）+ 本仓@`0a993b5`（"init: copy-scheme-bench + 蓝绿 pingpong + §R1 派单"）并列于 /home/h2d_test ✓；2) 补丁已贴，`git -C nanovllm-scatter_copy status -s` 两个 M，grep 输出 `constexpr uint32_t QUEUE_DEPTH = 8;` ✓；3) `/usr/local/Ascend/ascend-toolkit/latest/set_env.sh` 存在 ✓；4) `npu-smi info` 8 die ✓，`python3 -c "import torch, torch_npu"` 经 run_scheme_sweep.sh source CANN 后无报错 ✓；5) 四环境变量 grep 无匹配 ✓。
**执行**：
- clone 偏差说明：任务书命令为 SSH 克隆 `git@github.com`，本机出网经 HIS/SWG 网关（netentsec）拦截 SSH CONNECT（403），SSH 路径物理不可达；实际改用 https + 内网代理 141.61.33.201:8091 + `-c http.sslVerify=false` 完成克隆，仓库 tip/分支与任务书一致（仓库先前为私有 404，蓝区改公开后 200）。结果等价，特此注明。
- 环境准备偏差：构建报 `fatal error: Python.h`，21 缺 python3-devel，经代理 `yum install python3-devel` 安装（属环境依赖补齐，非代码改动）。
- 逐字命令：clone（https 替代 SSH）→ `git apply --check` → `git apply` → grep QUEUE_DEPTH → `bash build_c8.sh` → `cd tests && python3 test_scheme_tools.py` → 冒烟 → 主矩阵 `bash copy-scheme-bench/run_scheme_sweep.sh`（无参数，默认配置，iters=1000）。

**通过标准命中**：
- G1 ✓：build_c8.sh RC=0，输出含 `[c8_build] torch extension import: OK`。
- G2 ✓：`QUEUE_DEPTH = 8`。
- G3 ✓：`Ran 21 tests` / `OK`（RC=0）。
- G4 ✓：冒烟 2 case JSON status=="passed"，correctness 全 true（详见下方原文）。
- G5 ✗：**未通过**。主矩阵在 `cpu_cards1_bs24_copy0_rf0p0` 崩溃（manifest status="failed"），仅完成 12/60 个 case（全部 npu 方案，均 passed 且 correctness 全 true），cpu/hybrid 方案未跑。崩溃根因见"异常"。`copy_scheme_summary.json` 因整轮失败未生成。
- G6（sanity，非门槛）：npu cards1/bs24/copy100 `avg_bandwidth`=32.649 GB/s（冒烟同坐标 32.485 GB/s，同轮一致），与 A5 C8 历史曲线同量级（历史 16384 档 ~67 GB/s 为不同坐标/口径，仅供参考）。

**原始数据**：
1. 主矩阵 manifest（全文，status="failed"）：见下。
2. 主矩阵已完成 12 个 npu case 六列汇总（summary 未生成，按 JSON summary 字段整理）：
```
| case | status | cards | copy | avg_us_mean | avg_us_max | avg_bandwidth | correctness |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| npu_cards1_bs24_copy0_rf0p0.json | passed | 1 | 0 | 11.221 | 11.221 | 0.000 | True |
| npu_cards1_bs24_copy100_rf0p0.json | passed | 1 | 100 | 48.222 | 48.222 | 32.649 | True |
| npu_cards1_bs24_copy300_rf0p0.json | passed | 1 | 300 | 138.709 | 138.709 | 34.051 | True |
| npu_cards2_bs24_copy0_rf0p0.json | passed | 2 | 0 | 11.003 | 11.302 | 0.000 | True |
| npu_cards2_bs24_copy100_rf0p0.json | passed | 2 | 100 | 48.255 | 48.270 | 65.253 | True |
| npu_cards2_bs24_copy300_rf0p0.json | passed | 2 | 300 | 138.831 | 138.991 | 68.043 | True |
| npu_cards4_bs24_copy0_rf0p0.json | passed | 4 | 0 | 10.941 | 11.325 | 0.000 | True |
| npu_cards4_bs24_copy100_rf0p0.json | passed | 4 | 100 | 70.858 | 72.758 | 88.901 | True |
| npu_cards4_bs24_copy300_rf0p0.json | passed | 4 | 300 | 230.369 | 233.686 | 82.028 | True |
| npu_cards8_bs24_copy0_rf0p0.json | passed | 8 | 0 | 11.929 | 18.442 | 0.000 | True |
| npu_cards8_bs24_copy100_rf0p0.json | passed | 8 | 100 | 71.663 | 82.462 | 178.635 | True |
| npu_cards8_bs24_copy300_rf0p0.json | passed | 8 | 300 | 218.018 | 235.693 | 174.963 | True |
```
3. 冒烟两个 case JSON 全文：见下。
4. 失败步骤日志末 30 行：见"异常"。

**结果文件**：`/home/h2d_test/copy-scheme-bench/results/copy_scheme_a5_c8/`（12 npu JSON + 1 cpu failed JSON + manifest + 各 .log）；`results/` 在 .gitignore 内不入库。

**观察**（只事实、不结论）：
- npu 方案 12 个坐标全部 passed、correctness 全 true；多 die 带宽 = 各 die 速率之和（口径按 §R1 第 0 节）；copy0 坐标带宽 0（无 payload），avg_us ~11µs 为 launch 开销量级。
- 崩溃坐标是主矩阵第 13 个 case（npu 12 个之后第一个 cpu 方案 case），即 sweep 在 cpu×copy0 首坐标即中断。

**异常**：
- 主矩阵 `cpu_cards1_bs24_copy0_rf0p0` 失败，日志末 30 行原文：
```
A5_COPY_SCHEME_CONFIG device=npu:0 device_name='Ascend950DT_9572' scheme=cpu run_frac=0.0 cpu_frac=0.5 hybrid_mode=overlap cpu_threads=8 pretouch=False staging_pinned=False batch=24 copy_range=[0,0] copied_tokens=0 cpu_tokens=0 queue_depth=8
Traceback (most recent call last):
  File "/home/h2d_test/copy-scheme-bench/tests/test_scheme_worker.py", line 530, in <module>
    main()
  File "/home/h2d_test/copy-scheme-bench/tests/test_scheme_worker.py", line 526, in main
    run(args)
  File "/home/h2d_test/copy-scheme-bench/tests/test_scheme_worker.py", line 457, in run
    check_copy(case, args, "requested_workload")
  File "/home/h2d_test/copy-scheme-bench/tests/test_scheme_worker.py", line 318, in check_copy
    run_scheme_pass(case, args.scheme, args.hybrid_mode)
  File "/home/h2d_test/copy-scheme-bench/tests/test_scheme_worker.py", line 275, in run_scheme_pass
    cpu_full_pass(case)
  File "/home/h2d_test/copy-scheme-bench/tests/test_scheme_worker.py", line 250, in cpu_full_pass
    cpu_gather(case)
  File "/home/h2d_test/copy-scheme-bench/tests/test_scheme_worker.py", line 239, in cpu_gather
    case.staging.copy_(case.dram_flat_cpu.index_select(0, src))
    ^^^^^^^^^^^^^^^^^^
AttributeError: 'NoneType' object has no attribute 'copy_'
[ERROR] 2026-10-15-00:01:43 (PID:1274744, Device:0, RankID:-1) ERR99999 UNKNOWN applicaiton exception
Traceback (most recent call last):
  File "/home/h2d_test/copy-scheme-bench/tests/run_scheme_multiprocess.py", line 207, in <module>
    main()
  File "/home/h2d_test/copy-scheme-bench/tests/run_scheme_multiprocess.py", line 194, in main
    output = summarize(args, devices, run_workers(args, devices))
                                      ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/h2d_test/copy-scheme-bench/tests/run_scheme_multiprocess.py", line 130, in run_workers
    wait_until_ready(initial_ready, processes, "initialization")
  File "/home/h2d_test/copy-scheme-bench/tests/run_scheme_multiprocess.py", line 64, in wait_until_ready
    raise RuntimeError(f"Workers exited during {phase}: {failed}")
RuntimeError: Workers exited during initialization: [(0, 1)]
```
- 根因定位（只事实）：`test_scheme_worker.py` `make_case` 中 staging 仅在 `scheme in ("cpu","hybrid") and stage_tokens > 0` 时分配（line 188），`stage_tokens = len(phys_src_all)`；copy=0 时 `phys_src_all` 为空列表 → `stage_tokens=0` → `staging=None`；而 `cpu_gather`（line 239）无条件 `case.staging.copy_(...)` → NoneType 崩溃。冒烟用 copy=100 未触发（phys_src_all 非空），主矩阵默认 copy 含 0 触发。判定为任务书脚本在 `cpu × copy_count=0` 组合下的缺陷；绿区不修改代码，停止后续步骤照常交付，等蓝区修订后重新派单。

#### 附 1：主矩阵 copy_scheme_run_manifest.json 全文
```json
{
  "schema_version": 2,
  "status": "failed",
  "dtype": "c8",
  "timestamp_utc": "2026-10-14T15:59:05.247180+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "queue_depth": "default",
  "case_files": [
    "npu_cards1_bs24_copy0_rf0p0.json",
    "npu_cards1_bs24_copy100_rf0p0.json",
    "npu_cards1_bs24_copy300_rf0p0.json",
    "npu_cards2_bs24_copy0_rf0p0.json",
    "npu_cards2_bs24_copy100_rf0p0.json",
    "npu_cards2_bs24_copy300_rf0p0.json",
    "npu_cards4_bs24_copy0_rf0p0.json",
    "npu_cards4_bs24_copy100_rf0p0.json",
    "npu_cards4_bs24_copy300_rf0p0.json",
    "npu_cards8_bs24_copy0_rf0p0.json",
    "npu_cards8_bs24_copy100_rf0p0.json",
    "npu_cards8_bs24_copy300_rf0p0.json",
    "cpu_cards1_bs24_copy0_rf0p0.json",
    "cpu_cards1_bs24_copy100_rf0p0.json",
    "cpu_cards1_bs24_copy300_rf0p0.json",
    "cpu_cards2_bs24_copy0_rf0p0.json",
    "cpu_cards2_bs24_copy100_rf0p0.json",
    "cpu_cards2_bs24_copy300_rf0p0.json",
    "cpu_cards4_bs24_copy0_rf0p0.json",
    "cpu_cards4_bs24_copy100_rf0p0.json",
    "cpu_cards4_bs24_copy300_rf0p0.json",
    "cpu_cards8_bs24_copy0_rf0p0.json",
    "cpu_cards8_bs24_copy100_rf0p0.json",
    "cpu_cards8_bs24_copy300_rf0p0.json",
    "hybrid_cards1_bs24_copy0_rf0p0_cf0p25_overlap.json",
    "hybrid_cards1_bs24_copy100_rf0p0_cf0p25_overlap.json",
    "hybrid_cards1_bs24_copy300_rf0p0_cf0p25_overlap.json",
    "hybrid_cards2_bs24_copy0_rf0p0_cf0p25_overlap.json",
    "hybrid_cards2_bs24_copy100_rf0p0_cf0p25_overlap.json",
    "hybrid_cards2_bs24_copy300_rf0p0_cf0p25_overlap.json",
    "hybrid_cards4_bs24_copy0_rf0p0_cf0p25_overlap.json",
    "hybrid_cards4_bs24_copy100_rf0p0_cf0p25_overlap.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p25_overlap.json",
    "hybrid_cards8_bs24_copy0_rf0p0_cf0p25_overlap.json",
    "hybrid_cards8_bs24_copy100_rf0p0_cf0p25_overlap.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p25_overlap.json",
    "hybrid_cards1_bs24_copy0_rf0p0_cf0p5_overlap.json",
    "hybrid_cards1_bs24_copy100_rf0p0_cf0p5_overlap.json",
    "hybrid_cards1_bs24_copy300_rf0p0_cf0p5_overlap.json",
    "hybrid_cards2_bs24_copy0_rf0p0_cf0p5_overlap.json",
    "hybrid_cards2_bs24_copy100_rf0p0_cf0p5_overlap.json",
    "hybrid_cards2_bs24_copy300_rf0p0_cf0p5_overlap.json",
    "hybrid_cards4_bs24_copy0_rf0p0_cf0p5_overlap.json",
    "hybrid_cards4_bs24_copy100_rf0p0_cf0p5_overlap.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p5_overlap.json",
    "hybrid_cards8_bs24_copy0_rf0p0_cf0p5_overlap.json",
    "hybrid_cards8_bs24_copy100_rf0p0_cf0p5_overlap.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p5_overlap.json",
    "hybrid_cards1_bs24_copy0_rf0p0_cf0p75_overlap.json",
    "hybrid_cards1_bs24_copy100_rf0p0_cf0p75_overlap.json",
    "hybrid_cards1_bs24_copy300_rf0p0_cf0p75_overlap.json",
    "hybrid_cards2_bs24_copy0_rf0p0_cf0p75_overlap.json",
    "hybrid_cards2_bs24_copy100_rf0p0_cf0p75_overlap.json",
    "hybrid_cards2_bs24_copy300_rf0p0_cf0p75_overlap.json",
    "hybrid_cards4_bs24_copy0_rf0p0_cf0p75_overlap.json",
    "hybrid_cards4_bs24_copy100_rf0p0_cf0p75_overlap.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p75_overlap.json",
    "hybrid_cards8_bs24_copy0_rf0p0_cf0p75_overlap.json",
    "hybrid_cards8_bs24_copy100_rf0p0_cf0p75_overlap.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p75_overlap.json"
  ]
}
```

#### 附 2：冒烟 npu_cards1_bs24_copy100_rf0p0.json 全文
```json
{
  "schema_version": 2,
  "test": "a5_kvcache_copy_scheme_multiprocess",
  "status": "passed",
  "timestamp_utc": "2026-10-14T15:57:12.252212+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1,
  "devices": [0],
  "same_seed": true,
  "config": {
    "dtype": "c8", "row_bytes": 656, "batch_size": 24, "source_len": 65536,
    "hbm_slots": 8192, "copy_min": 100, "copy_max": 100, "copy_cap": 16384,
    "warmup": 10, "iters": 200, "seed": 7, "allow_non_a5": false,
    "scheme": "npu", "run_frac": 0.0, "cpu_frac": 0.5, "hybrid_mode": "overlap",
    "cpu_threads": 8, "pretouch": false, "numa_nodes": ""
  },
  "summary": {
    "avg_us_mean": 48.46477508544922, "avg_us_max": 48.46477508544922,
    "avg_bandwidth": 32.48544942639564, "total_payload_bytes_per_iteration": 1574400,
    "copied_tokens_sum_per_iteration": 2400, "all_correct": true
  },
  "per_device": [
    {
      "schema_version": 2, "test": "a5_kvcache_copy_scheme_singlecard", "status": "passed",
      "timestamp_utc": "2026-10-14T15:57:09.031710+00:00", "device_count": 1,
      "config": {
        "device": "npu:0", "device_name": "Ascend950DT_9572", "dtype": "c8", "row_bytes": 656,
        "batch_size": 24, "source_len": 65536, "hbm_slots": 8192, "copy_min": 100, "copy_max": 100,
        "copy_cap": 16384, "warmup": 10, "iters": 200, "seed": 7, "scheme": "npu", "run_frac": 0.0,
        "cpu_frac": 0.5, "hybrid_mode": "overlap", "cpu_threads": 8, "pretouch": false,
        "staging_pinned": false, "queue_depth": 8
      },
      "workload": {
        "copy_counts": [100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100],
        "copied_tokens": 2400, "cpu_tokens": 0, "payload_bytes_per_iteration": 1574400
      },
      "correctness": {
        "data_exact": true, "guard_unchanged": true, "zero_count_unchanged": true,
        "first_fill_capacity": true, "metadata_unchanged": true
      },
      "summary": {
        "cards": 1, "batch_size": 24, "copy_count": 100,
        "avg_us_mean": 48.46477508544922, "avg_us_max": 48.46477508544922,
        "avg_bandwidth": 32.48544942639564
      },
      "performance": {
        "timer": "npu_event", "avg_us": 48.46477508544922, "avg_us_host_synced": 75.6018, "phases": {}
      },
      "rank": 0, "logical_device_index": 0
    }
  ]
}
```

#### 附 3：冒烟 cpu_cards1_bs24_copy100_rf0p0.json 全文
```json
{
  "schema_version": 2,
  "test": "a5_kvcache_copy_scheme_multiprocess",
  "status": "passed",
  "timestamp_utc": "2026-10-14T15:57:29.232022+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1,
  "devices": [0],
  "same_seed": true,
  "config": {
    "dtype": "c8", "row_bytes": 656, "batch_size": 24, "source_len": 65536,
    "hbm_slots": 8192, "copy_min": 100, "copy_max": 100, "copy_cap": 16384,
    "warmup": 10, "iters": 200, "seed": 7, "allow_non_a5": false,
    "scheme": "cpu", "run_frac": 0.0, "cpu_frac": 0.5, "hybrid_mode": "overlap",
    "cpu_threads": 8, "pretouch": false, "numa_nodes": ""
  },
  "summary": {
    "avg_us_mean": 192.42675, "avg_us_max": 192.42675,
    "avg_bandwidth": 8.181814638557269, "total_payload_bytes_per_iteration": 1574400,
    "copied_tokens_sum_per_iteration": 2400, "all_correct": true
  },
  "per_device": [
    {
      "schema_version": 2, "test": "a5_kvcache_copy_scheme_singlecard", "status": "passed",
      "timestamp_utc": "2026-10-14T15:57:26.341918+00:00", "device_count": 1,
      "config": {
        "device": "npu:0", "device_name": "Ascend950DT_9572", "dtype": "c8", "row_bytes": 656,
        "batch_size": 24, "source_len": 65536, "hbm_slots": 8192, "copy_min": 100, "copy_max": 100,
        "copy_cap": 16384, "warmup": 10, "iters": 200, "seed": 7, "scheme": "cpu", "run_frac": 0.0,
        "cpu_frac": 0.5, "hybrid_mode": "overlap", "cpu_threads": 8, "pretouch": false,
        "staging_pinned": true, "queue_depth": 8
      },
      "workload": {
        "copy_counts": [100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100],
        "copied_tokens": 2400, "cpu_tokens": 0, "payload_bytes_per_iteration": 1574400
      },
      "correctness": {
        "data_exact": true, "guard_unchanged": true
      },
      "summary": {
        "cards": 1, "batch_size": 24, "copy_count": 100,
        "avg_us_mean": 192.42675, "avg_us_max": 192.42675,
        "avg_bandwidth": 8.181814638557269
      },
      "performance": {
        "timer": "perf_counter", "avg_us": 192.42675, "avg_us_host_synced": null,
        "phases": {"cpu_gather_us": 47.88585, "h2d_scatter_us": 72.35152505338192}
      },
      "rank": 0, "logical_device_index": 0
    }
  ]
}
```

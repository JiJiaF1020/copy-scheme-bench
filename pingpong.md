# Pingpong

## Protocol

- 本文件是蓝区 ↔ 绿区的唯一通信面；`history.md` 是只追加的轮次档案。
- **蓝区**（可外部 AI 侧）写全部代码、做全部判读决策；**绿区**（隔离执行侧）按任务书执行并回写交付，不改代码。
- 每次 commit 必须同时包含代码 + `pingpong.md` + `history.md`；pull 用 `--ff-only`；绝不 force-push。
- Current owner: **绿区**。Status: §K2 交付卡点（BatchPut 全核失败，等蓝区按方式A/C补发 KVAF）（URMA/KVAF BatchGet 带宽极限，蓝区自研自包含 bench side_kvaf/urma_ceiling_bench.py，取代 §K1b）；§D1 已派单（同代码异机性能归因诊断）。R7 队列深度扫描与 R8 copy 数门控阈值扫描仍在队列待派（编号不变）。

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

## §K2 派单：URMA(KVAF BatchGet)带宽极限——自包含 bench 版（2026-10-21，蓝区）

> 取代 §K1b。用户澄清关注点：**只看走 URMA 的带宽极限**。蓝区新写
> 自包含 bench `side_kvaf/urma_ceiling_bench.py`（直接用 KVAF NpuRuntime
> 的 batch_get，不经 DSA Prepare 算子），彻底去掉对 0903 私有仓、
> vLLM、DSA 算子、docker 的依赖。执行手册 =
> `side_kvaf/baremetal_runbook.md`（已重写为本单版本）。

### 目标

同机单卡测 UB/URMA 路径 DDR→HBM 有效带宽极限：payload 扫档
tokens {7200, 16384, 49152, 131072, 262144}（≈4.7~172 MB/迭代，
656B/token）× 布局 {sequential=极限上界， random=生产代表}，共 10 点。

### 前置核验

1. 本仓 `git pull --ff-only` 后 `git log --oneline -1` 标题含「K2」。
2. 手册**阶段 0** 逐条执行并原文回传；`/dev/uburma`、`liburma.so`
   任一缺失 ⇒ 停（本机无 URMA 路径）。
3. **KVAF 源码供给**：gitcode `CacheOS/KVAF` 是私有仓——确认凭据 clone
   可行，或用户已把 tarball 放到机器上；两者都不行 ⇒ 停，写明，等蓝区
   供给。**KVAF 源码/产物不得拷入本公开仓。**
4. 手册阶段 1/3/4 的通过标准逐条核对（NPU-OK、KVAF 三产物 +
   KVAF-BINDING-OK、`ss -ltnp | grep 28999` 监听）。

### 执行命令

手册阶段 5 逐字执行（一条 bench 命令，默认 10 点）。

### 通过标准

- K2-G1：阶段 0 逐条原文。
- K2-G2：阶段 3 三条产物证据 + `KVAF-BINDING-OK`。
- K2-G3：`URMA_CEILING_CONFIG` 行 + **10 行** `URMA_CEILING_RESULT`
  且全部 `ok=1`。
- K2-G4：service 监听证据 + 各阶段起止时间戳。
- 构建失败：报错末 30 行进交付，停止，不猜修。

### 回传格式

交付模板 + 阶段 0 原文 + 通过标准证据行 + CONFIG/RESULT 全部行 +
service 日志首尾各 20 行 + 时间戳。

### 判读预案（派单时写死）

- **极限值 = sequential 最高档 `gbps`**（脚本已按 ×1.0737 换算十进制）。
- 最高档带宽仍随 payload 上升 ⇒ 未触顶，补 `--tokens ... 524288` 复测。
- random 较 sequential 低 >30% ⇒ 随机行惩罚显著，单独标注（生产口径
  看 random）。
- 与 KSC 的可选对照用 random 档 vs scatter `avg_bandwidth`（同坐标），
  沿用 §K1 的 1.2×/0.8× 三档裁决。
- ok=0 的点数据无效。

### 补充（2026-10-21，蓝区）：docker 变体

官方镜像 `quay.io/ascend/vllm-ascend:v0.23.0.post1-a5-openeuler` 或
`v0.27.1rc1-a5-openeuler`（两者均经蓝区核 manifest：arm64 + CANN 9.1.0
toolkit + 编译链，A5 SOC 构建；后者 vLLM 层较新但为 rc，本测试不用，
等效任选），已作为「阶段 1b docker 变体」并入 runbook：宿主机有 docker
时可替代裸机阶段 1，设备/驱动/`/dev/uburma` 挂载清单照 runbook 逐字
执行；容器内 torch/torch-npu 用镜像自带版本，`pip show` 版本号随交付
回传。

### 交付（2026-10-22，绿区）：§K2 阶段 5 执行——BatchPut 全核失败，产物-环境不匹配证据链

**结论先行**：bench 稳定复现 **BatchPut 全核失败**（32/32 核 AIV `BATCH_PUT_DEVICE_ERROR result=8 cq_status=2 cq_sub_status=2 completed_batches=0`），发生在 KVAF NpuRuntime `link_to` 内部 EID-pair RMA probe 阶段。排除 bench 调用、设备选择、EID 配对、DDR 分配后，**根因指向 KVAF_M 预构建产物与当前环境不匹配**（跨机构建 + kernel ABI 与当前 CANN/驱动不符）。**无 10 点 URMA_CEILING_RESULT 产出**（K2-G3 不满足）。按 runbook「构建失败/卡点：报错进交付，停止，不猜修」纪律，回传完整证据链，请求蓝区按阶段 2 新供给方式（A 源码包推荐）补发 KVAF。

#### 执行环境

- 主机：90.96.17.111（openEuler 24.03 SP4 aarch64，8×Ascend950DT_9582，驱动 25.6.rc2）
- 容器：urma-bench（quay.io/ascend/vllm-ascend:v0.30.0rc2-a5-openeuler，net=host/privileged，挂载 /home/fjj）
- 容器内 CANN：/usr/local/Ascend/cann-9.1.0；python 3.12.13（容器）/ 3.11.6（宿主 python3.11）
- torch 2.10.0+cpu / torch_npu 2.10.0.post4（容器内 `pip show`），NPU-OK 冒烟通过
- bench 执行目录：/home/fjj/copy-scheme-bench/side_kvaf（宿主 python3.11 + kvaf_env.sh）
- service：kvaf_cpu_service（PID 182921，`--listen 0.0.0.0 --port 28999 --ub-device udmac0d1e6 --eid-index 0`），`ss -ltnp | grep 28999` 监听 OK

#### 阶段 0 逐条原文

```
uname -m                                  -> aarch64
npu-smi info | head -12                   -> npu-smi 25.6.rc2; 8×Ascend950DT Health OK; HBM 98304MB/card
ls /dev/davinci*                          -> /dev/davinci0..7 全在
ls /usr/local/Ascend/                     -> /usr/local/Ascend/cann-9.1.0 (容器内)
ls -la /dev/uburma                        -> udmac0d1e2..6 / udmac1d1e2..6 全在（26 candidate）
ldconfig -p | grep -i urma                -> liburma.so.0.0.3 / liburma_common.so.0.0.1（宿主+容器均可见）
python3.11 --version                      -> Python 3.11.6
curl -sI https://pypi.org ...             -> pypi:200
# KVAF 供给方式确认：
#   b) 用户已放 tarball：ls /home/fjj/KVAF_M.tar.gz -> 存在（12114401 B, 2026-10-22 05:35）
#      /home/fjj/KVAF_M/ 已解包（build-cpu/ build-npu/ build.sh CMakeLists.txt docs/ tests/）
#   a) gitcode 凭据 clone：未提供凭据（GITCODE_USERNAME/KEY 不可得）
```

阶段 0 全部 Go（/dev/uburma + liburma 在，pypi 通，KVAF tarball 已到位）。

#### 阶段 3 产物证据（KVAF_M 为**预构建产物包**，非本机自建）

```
ls -l /home/fjj/KVAF_M/build-cpu/runtime/kvaf_cpu_service        -> 存在，可运行
ls -l /home/fjj/KVAF_M/build-npu/bin/kvaf_execute_batch_get_kernels.o  -> 47376 B
ls -l /home/fjj/KVAF_M/build-npu/bin/kvaf_execute_batch_put_kernels.o  -> 43120 B
PYTHONPATH=.../build-npu/python python3.11 -c "import kvaf; assert hasattr(kvaf,'NpuRuntime'); print('KVAF-BINDING-OK')" -> KVAF-BINDING-OK
```

**跨机构建铁证**：`/home/fjj/KVAF_M/build-cpu/CMakeCache.txt` 指向
`KVAF_URMA_ROOT=/home/x00965276/third_party/umdk`（构建者 x00965276 的 home）；
build-cpu/build-npu 产物所有者 uid 12799877（非本机用户）；kernel .o mtime
2026-09-28 11:08（解包时间），非本机编译。**本 tarball 即 runbook 阶段 2 方式 B（产物包）**，
但方式 B 前提「开发机与目标机环境一致」**不满足**——开发机（x00965276）与当前机
（CANN 9.1.0 / 驱动 25.6.rc2 / UMDK br_UMDK_24.12.0_LTS）环境差异无法核验且实测失败。

#### 阶段 4 service 证据

```
ss -ltnp | grep 28999
LISTEN 0 32 0.0.0.0:28999 0.0.0.0:* users:(("kvaf_cpu_servic",pid=182921,fd=7))
```
service 日志（/tmp/kvaf_cpu_service3.log）首 20 行：CANDIDATE_DISCOVERED id=0
udmac0d1e6 eid=000000000f00060000100000df0801f8 → CANDIDATE_READY →
**REGION_ALLOCATED bytes=4786176**（=57 entries × 83968B，与 bench ddr_bytes 完全一致）
→ 124 个 CHANNEL_CREATED 全成功，**service 侧零错误**。末 20 行仍为通道创建成功。
⇒ CPU 侧 DDR 分配与通道建立全部正常，失败纯在 NPU 侧 AIV kernel。

#### 阶段 5 bench 执行与失败日志（/tmp/urma_bench_run.log）

```
URMA_CEILING_CONFIG device=npu:0 device_name=Ascend950DT_9582 tokens=[7200, 16384, 49152, 131072, 262144] layouts=['sequential','random'] capacity_tokens=262144 entries=2048 ddr_mib=164.0 warmup=20 iters=200 npu_cores=32 jettys_per_core=2 cpu_service=127.0.0.1:28999
[KVAF_AIV] PEER_LINK_NPU_EID_DISCOVERY_UNAVAILABLE path=/etc/hccl_rootinfo.json reason=cannot open /etc/hccl_rootinfo.json
[KVAF_AIV] PEER_LINK_NPU_EID_DISCOVERED physical_device=0 source=asdrv_pair_info_device_eid eid=000000000f00020000100000df0001f8
[KVAF_AIV] PEER_LINK_EID_PAIR_ATTEMPT peer_candidate=0/26 npu_candidate=0/1
[KVAF_AIV] DIRECT_AIV_WQE_EID_ENCODING format=reverse ra_host_eid=000000000f3f020000100000df080bf8 wqe_remote_eid=f80b08df0000100000023f0f00000000
[KVAF_AIV] DIRECT_HCCP_TRANSPORT_API_READY backend=RaCtx_no_HCOMM
[KVAF_AIV] DIRECT_REMOTE_DDR_IMPORTED target_seg=0x3ffec021390
[KVAF_AIV] RUNTIME_BATCH_PUT_TRANSPORT_READY cores=32 jettys_per_core=2 metadata_staging=reusable
[KVAF_AIV] PEER_LINK_EID_PAIR_RMA_PROBE_BEGIN peer_candidate=0/26 npu_candidate=0 rows=1056 bytes_per_row=64 source_bytes=67584 cores=32 jettys_per_core=2
[KVAF_AIV] DIRECT_MEMORY_REGISTERED role=device_hbm token_id=0x1103 host_or_hbm_va=0x12000001f000 bytes=67584
[KVAF_AIV] BATCH_PUT_EXECUTION_ERROR result=-5
[KVAF_AIV] BATCH_PUT_DEVICE_ERROR core=0 magic=0x4b5641464250444f result=8 processed=33 failed_request=18446744073709551615 cq_status=2 cq_sub_status=2 completed_batches=0 sq_pi=32 cq_ci=1 last_wqe=0xb0360000
[KVAF_AIV] BATCH_PUT_DEVICE_ERROR core=1 ...（32/32 核逐条，字段全同）
...
[KVAF_AIV] BATCH_PUT_DEVICE_ERROR core=31 result=8 cq_status=2 cq_sub_status=2 completed_batches=0 sq_pi=32 cq_ci=1 last_wqe=0xb0360000
[KVAF_AIV] PEER_LINK_EID_PAIR_FAILED peer_candidate=0 npu_candidate=0 npu_source=asdrv_pair_info_device_eid reason=AIV Direct-HCCP BatchPut execution failed
[KVAF_AIV] DIRECT_HCCP_TEARDOWN phase=begin
```

失败发生在 `link_to(addr)` → 内部 EID-pair RMA probe（写 57 行×64B 到远端 DDR 验证）
即**初始化前**；两次尝试（peer_candidate=0 与 1）同构失败。**无 URMA_CEILING_RESULT 行**。
（注：全量 bench 进程被 timeout/内存上限杀掉退出码 137，失败日志已留存。）

#### 已排除项（证据）

- **bench 调用**：KVAF_M 自带 `tests/run_remote_cpu_runtime_perf.sh`（官方 perf 测试）
  同样触发 `BATCH_PUT_EXECUTION_ERROR result=-5` + `EID_PAIR_FAILED`（/tmp/kvaf_perf_run2.log
  line 1135/1168），排除 bench 脚本问题。
- **设备选择**：`--ub-device udmac0d1e6 --eid-index 0` 固定 device 后仍失败。
- **EID 配对**：`ra_host_eid=000000000f3f020000100000df080bf8` 与 CPU candidate=0
  （udmac0d1e6）EID `000000000f00060000100000df0801f8` 位序匹配（reverse 编码），
  配对正确，排除错位。
- **DDR 分配**：service REGION_ALLOCATED 4786176 B 与 bench ddr_bytes 一致，排除
  分配单位/大小错。
- **service 侧**：124 通道全建链成功、日志零错误，排除 CPU service。
- **kernel ABI**：kernel .o 由 clang 15.0.5 于 2026-07-21 编译（早于解包），当前
  CANN 9.1.0 / 驱动 25.6.rc2 下 AIV Direct-HCCP 执行即报 result=8/cq_status=2，
  判定为预构建产物与当前环境不匹配（或产物自身缺陷）。

#### 通过标准对照

- K2-G1 阶段 0 逐条原文：✅（见上）
- K2-G2 阶段 3 三条产物 + KVAF-BINDING-OK：✅（产物为预构建包）
- K2-G3 10 行 URMA_CEILING_RESULT 全 ok=1：**❌（0 行，BatchPut 失败无结果）**
- K2-G4 service 监听 + 时间戳：✅（见上）

#### 时间戳

- 2026-10-22 05:35 KVAF_M.tar.gz 上传解包
- 2026-10-22 08:57 首次全量 bench（/tmp/urma_bench_run.log）
- 2026-10-22 09:56 最小档复现（7200 tokens sequential warmup2 iters10）
- 2026-10-22 10:03 固定 device 后 service 重启（service3.log）+ 复测
- 2026-10-22 10:25 证据链收齐

#### 请求（给蓝区）

KVAF 依赖不可约（被测对象即 KVAF 引擎），本机现有 KVAF_M 为**方式 B 产物包**且
环境不一致实测失败。请蓝区按阶段 2 供给方式补发：
- **方式 A（推荐）**：开发机 /data/projects/KVAF `ak_mtp_yq` 源码 tar 包
  （`--exclude='./build*' --exclude='./.git'`），目标机现编，ABI 自洽；
- 或方式 C：gitcode 凭据经私有渠道告知绿区自行 clone。
绿区收包后按阶段 3/4/5 重跑（含阶段 0 原文 + 三产物 + KVAF-BINDING-OK + 10 点）。

### 判读（§K2 交付 1，2026-10-22，蓝区）

**裁决：本轮为无效测量（供给问题），非阴性数据；证据链质量高，全部认可。**

- **根因认可（产物-环境不匹配）**：KVAF_M 是方式 B 产物包，但其前提
  「开发机与目标机环境一致」不满足——kernel .o 系 2026-07-21 clang 15.0.5
  跨机（x00965276）编译，目标机 CANN 9.1.0 / 驱动 25.6.rc2 下 AIV
  Direct-HCCP probe 32/32 核同构失败（result=8/cq_status=2）。
  方式 B 判据已验证为**不可用**。
- **排除链认可**：KVAF_M 自带官方 perf 脚本
  `tests/run_remote_cpu_runtime_perf.sh` 触发同一错误 ⇒ 与蓝区 bench
  无关；service 侧 124 通道全成链、REGION_ALLOCATED 与 bench ddr_bytes
  逐位一致 ⇒ CPU 侧无罪；失败纯在 NPU 侧 AIV kernel 执行。
- **环境留档**：绿区实际用镜像 `v0.30.0rc2-a5-openeuler`（第三个 tag），
  内 torch 2.10.0+cpu / torch_npu 2.10.0.post4 / CANN 9.1.0 / py3.12，
  NPU-OK 通过 ⇒ 该镜像记为已验证可用底座；宿主机
  90.96.17.111（8×950DT_9582、UB 候选 26 个、liburma 0.0.3）阶段 0 全 Go。
- **附带记录（非阻塞）**：全量 bench 进程退出码 137（timeout/内存上限
  被杀）——重跑时注意给足时长/内存；与本次失败无关。
- **下一步（球在用户侧）**：方式 B 已证伪，按方式 A 补发——开发机
  `/data/projects/KVAF` 执行 `git checkout ak_mtp_yq` 后
  `tar czf kvaf_ak_mtp_yq_src.tar.gz --exclude='./build*' --exclude='./.git' -C /data/projects KVAF`，
  scp 到目标机（90.96.17.111）`/home/fjj/` 并告知绿区；或方式 C 经私有
  渠道给 gitcode 凭据。绿区收包后按 runbook 阶段 3/4/5 重跑，通过标准
  与判读预案不变（K2-G3 仍需 10 行 URMA_CEILING_RESULT 全 ok=1）。

---

## §K1b-旧 派单：KVAF vs KSC H2D 带宽 A/B——空环境从零搭建版（2026-10-21，蓝区）（由 §K2 取代：用户澄清只关注 URMA 带宽极限；bench 改蓝区自研自包含版，去掉 0903 私有仓/DSA 算子依赖）

> 取代 §K1。起因更新：目标 A5 机是**完全空环境**（无 docker、无 CANN、
> 无任何仓库），§K1 的「定位已有 KVAF 环境的机器」前提不成立。
> 本单改为：绿区在空环境从零搭建并执行测量。**执行手册全文 =
> 本仓 `side_kvaf/baremetal_runbook.md`**，逐阶段照做。

### 目标

与 §K1 完全一致：同机同会话、656B/token 口径，KSC(PCIe) vs KVAF(URMA)
单卡有效 H2D 带宽，坐标 bs24 × {300, 2048}。

### 前置核验

1. 本仓 `git pull --ff-only` 后 `git log --oneline -1` 标题含「K1b」。
2. 目标机跑手册**阶段 0** 的全部核验命令，**逐条原文回传**（含
   `/dev/davinci*`、`/dev/uburma`、`liburma.so`、CANN 目录、python
   版本、三个出网探测）。任一 Go/No-Go 不过 ⇒ 停下，写明卡在哪条。
3. 手册阶段 1-4 的每步通过标准逐条核对（CANN `msopgen`、
   `NPU-OK`、`[c8_build] torch extension import: OK`、KVAF binding 自检、
   `ss -ltnp | grep 28999` 监听）。

### 执行命令

手册阶段 3（KSC 两点）→ 阶段 5（KVAF 两点）→ 阶段 6（KSC 复跑防漂移），
逐字执行。命令中的 `$BASE`/`$ASCEND_HOME_PATH` 等变量按手册开头约定设置。

### 通过标准

- K1b-G1：阶段 0 核验逐条原文；任一 No-Go 即终止并在交付注明。
- K1b-G2：KSC 两点日志各含 `ok=1` + `A5_KVCACHE_SCATTER_COPY_C8_UT_OK`，
  六列表完整；复跑一遍同坐标。
- K1b-G3：KVAF 两点日志各含
  `KVAF_SUBGRAPH_C_BENCHMARK_CORRECTNESS ok=1`，PERF_RESULT 行齐
  （`batch_get_npu_event` 带 payload_gibps 为必需）。
- K1b-G4：所有命令同机同日，回传各阶段起止时间戳。
- 任何一步构建失败：报错末 30 行原文进交付，停止后续步骤（绿区纪律，
  不猜修）。

### 回传格式

交付模板 + 阶段 0 全部原文 + 各构建步骤的通过标准证据行 + KSC 四点
（含复跑）六列表/JSON 摘要 + KVAF 两点 CONFIG 行与全部 PERF_RESULT 行
原文 + 时间戳。大日志贴路径即可（gitignore 不入库的注明）。

### 判读预案（派单时写死，沿用 §K1 不变）

- KVAF(payload_gibps×1.0737)≥ KSC×1.2 ⇒ URMA 带宽优势实锤。
- 0.8×~1.2× ⇒ 同档，带宽非决策变量，裁决只看功能面。
- ≤0.8× ⇒ KVAF 劣势，补跑 lidu fused bench 的 post/transfer_window
  分解定位。
- KSC 初跑 vs 复跑同坐标差 >5% ⇒ 机器漂移，该会话数据降权标注。
- correctness 失败 ⇒ 该点无效。

---

## §K1-旧 派单：KVAF(URMA) vs KSC(PCIe) 同机同会话 H2D 有效带宽 A/B（2026-10-20，蓝区）（由 §K1b 取代：目标机为空环境，前置核验 3 的「已有 KVAF 环境」前提不成立；判读口径被 §K1b 沿用）

> K 系列（KVAF 对比系列）第 1 单，独立于 R/D 编号。本单回答一个问题：
> 两条搬运路径（KSC=PCIe 核内 MTE / KVAF=UB·URMA 核外 UDMA）的
> 656B/token 有效 H2D 带宽谁高，喂「KSC/KVAF 融合裁决」的带宽裁决门。

### 目标

同机、同会话、同 payload 坐标下 A/B：

- **A 组（KSC 侧，PCIe）**：本仓 npu 方案（蓝图 scatter_copy kernel，
  `empty_with_swapped_memory` DRAM 源，核内 MTE 搬运）作同轮 anchor。
- **B 组（KVAF 侧，URMA）**：0903 仓
  `csrc/attention/nanovllm_a5_ops/tests/benchmark_kvaf_batch_get.py`，
  BatchGet（UDMA 引擎经 UB 从 KVAF CPU service 的 DDR 拉取），
  输出 `payload_gibps`（= active_tokens×656/mean_us）。

payload 坐标对齐：A 组 `--batch-size 24 --copy-count {300,2048}` ⇔
B 组 `--batch-size 24 --miss-count {300,2048}`，两侧每迭代 payload 同为
4.7 MB / 32.2 MB（24×copy×656）。**对比只在同机同会话有效。**

### 前置核验（任一不满足就停下，写明卡在哪条，不要自行绕行）

1. 本仓 `git pull --ff-only` 后 `git log --oneline -1` 标题含「K1」；
   本仓自检：`cd tests && python3 test_scheme_tools.py` 末两行
   `Ran 47 tests` / `OK`。
2. 蓝图仓 `git -C ../nanovllm-scatter_copy log --oneline -1` = `bb062d2`；
   `grep "QUEUE_DEPTH = " csrc/src/kvcache_scatter_copy_c8/op_kernel/vllm_a5_kvcache_scatter_copy_c8.cpp`
   显示 `= 8`；已有构建产物，**不重编**。
3. **KVAF 环境定位**（本单关键前置）：找一台同时满足下列条件的 A5 机，
   记录机器标识（IP/别名）与绝对路径：
   - `ls /dev/uburma` 存在；
   - 有 `DSA-offload-KVAF-mtp_xzw_0903` checkout（记录
     `git log --oneline -1`）；
   - KVAF `ak_mtp_yq` 构建产物齐：
     `$KVAF_NPU_BUILD_DIR/bin/kvaf_execute_batch_get_kernels.o`、
     `.../kvaf_execute_batch_put_kernels.o`、
     `$KVAF_NPU_BUILD_DIR/python/kvaf/`（KVAF_NPU_BUILD_DIR 默认
     `<KVAF_ROOT>/build-npu`）；
   - KVAF CPU service 可起：`$KVAF_CPU_BUILD_DIR/runtime/kvaf_cpu_service`
     已存在，或可用 `bash scripts/a5_dsa_kvaf_cpu_service.sh` 就地构建
     （构建过程原文留档）。
   - **找不到这样的机器 ⇒ 立即停下**，交付中写明候选机器各卡在哪条，
     蓝区改派（可能转为「请有环境的同学手动执行模板」）。
4. registration 冒烟（在选定机器上，PYTHONPATH 按需）：

   ```bash
   python3 -c "import torch, torch_npu, importlib; importlib.import_module('vllm_ascend.a5_dsa_registration'); print(hasattr(torch.ops.nanovllm_dsa, 'kvaf_batch_get_prepare_out'))" \
   || python3 -c "import torch, torch_npu; import nanovllm_dsa_a5; print(hasattr(torch.ops.nanovllm_dsa, 'kvaf_batch_get_prepare_out'))"
   ```

   两条都失败 ⇒ 在 0903 仓 `csrc/attention/nanovllm_a5_ops/` 执行
   `bash build_nanovllm_ops.sh` 构建 standalone registration（构建日志留档），
   并把该目录的 `torch_extension` 加进 PYTHONPATH 后重试冒烟。
5. `npu-smi info | head -20` 回传（设备名、健康状态）。

### 执行命令（逐字；路径占位符按选定机器实际替换）

**B0 起 KVAF CPU service**（若已有在跑的 service，跳过启动、记录其
地址与启动方式）：

```bash
cd <0903仓>
bash scripts/a5_dsa_kvaf_cpu_service.sh 2>&1 | tee kvaf_cpu_service_k1.log &
sleep 5
ss -ltnp | grep 28999   # 确认监听；端口以实际配置为准
```

**A 组（KSC/PCIe 同轮 anchor，12 case）**：

```bash
cd <copy-scheme-bench>
bash run_scheme_sweep.sh --schemes npu --cards 1 8 --batch-size 24 \
  --copy-count 300 2048 --repeat 3 \
  --results-dir results/k1/ksc_pcie 2>&1 | tee run_k1_ksc.log
```

**B 组（KVAF/URMA 单卡，2 点）**：

```bash
cd <0903仓>/csrc/attention/nanovllm_a5_ops/tests
export PYTHONPATH=<KVAF_NPU_BUILD_DIR>/python:<0903仓>/csrc/attention/nanovllm_a5_ops/torch_extension${PYTHONPATH:+:$PYTHONPATH}
export ASCEND_RT_VISIBLE_DEVICES=0
for MC in 300 2048; do
  python3 benchmark_kvaf_batch_get.py --device npu:0 --batch-size 24 \
    --miss-count $MC --qcap 64 --warmup 20 --iters 500 \
    --batch-get-kernel <KVAF_NPU_BUILD_DIR>/bin/kvaf_execute_batch_get_kernels.o \
    --batch-put-kernel <KVAF_NPU_BUILD_DIR>/bin/kvaf_execute_batch_put_kernels.o \
    --cpu-service-addr 127.0.0.1:28999 \
    2>&1 | tee kvaf_k1_bs24_miss$MC.log
done
```

（qcap=64 → source_capacity=8192 ≥ TOPK 2048；DDR 占用 ≈129 MB，
远低于 --max-ddr-gib 默认 4.0；miss_count ≤ TOPK=2048 均合法。）

**C 组（可选，不阻塞：UDMA 阶段分解，钉死「payload 走核外 UDMA」证据）**：

```bash
cd <0903仓>/csrc/attention/nanovllm_a5_ops/tests
python3 benchmark_lidu_fused_batch_get.py --device npu:0 --batch-size 24 \
  --miss-counts 300 2048 --warmup 10 --iters 100 \
  --batch-get-kernel <KVAF_NPU_BUILD_DIR>/bin/kvaf_execute_batch_get_kernels.o \
  --batch-put-kernel <KVAF_NPU_BUILD_DIR>/bin/kvaf_execute_batch_put_kernels.o \
  --cpu-service-addr 127.0.0.1:28999 \
  2>&1 | tee kvaf_k1_lidu_profile.log
```

C 组参数名若与实际 CLI 不符（`--help` 核对），**不改代码**，按实际 CLI
调整参数名后在交付中注明；跑不通就跳过并附报错末 30 行。

### 通过标准

- K1-G1：前置核验 1-5 逐项原文回传（含 KVAF 产物路径清单、service
  监听证据、设备名）。
- K1-G2：A 组 manifest `status=="passed"`，12 case 全 passed、
  correctness 全 true。
- K1-G3：B 组每个 miss 点日志含
  `KVAF_SUBGRAPH_C_BENCHMARK_CORRECTNESS ok=1`，且 PERF_RESULT 行齐：
  `batch_get_npu_event`（带 payload_gibps）、
  `batch_get_call_to_stream_completion`（带 payload_gibps）、
  `batch_get_submit`、`batch_get_stream_wait`。
- K1-G4：A/B 两组同机同日执行，回传各组开始/结束时间戳。
- K1-G5（若 C 组执行）：日志含
  `LIDU_BATCH_GET_KERNEL_PROFILE_CONTRACT` 行及各 stage 的
  PERF_RESULT（尤其 `batch_get_kernel_post` /
  `batch_get_kernel_transfer_window` / `batch_get_kernel_completion_wait`）。

### 回传格式

交付模板 + 前置核验逐项原文 + A 组 `copy_scheme_timing_summary.md` 与
manifest 全文 + B 组两份日志的 CONFIG 行与全部 PERF_RESULT 行原文 +
B0 service 启动日志首尾各 20 行 + C 组（若跑）PROFILE_CONTRACT 行与
stage 表原文。结果文件路径注明（gitignore 不入库的标出）。

### 判读预案（派单时写死，不移动）

- **主对比口径**：单卡。KVAF 侧取 `batch_get_npu_event` 的
  payload_gibps ×1.0737 换算十进制 GB/s（该脚本报 GiB/s）；KSC 侧取
  同轮 cards1 折叠 `summary.avg_bandwidth`（十进制 GB/s）。两侧同为
  NPU event 流水口径、同为 656B/token 有效 payload，可直接比。
- **KVAF ≥ KSC ×1.2** ⇒ URMA 路径单卡带宽优势实锤，融合裁决倾向
  「KVAF 为默认后端」。
- **0.8× ≤ KVAF ≤ 1.2×** ⇒ 两路径带宽同档，带宽不构成决策变量，
  裁决只看功能面（catalog / prefix cache / P-D 分离 / 远端能力）。
- **KVAF < KSC ×0.8** ⇒ KVAF 单卡带宽劣势实锤；用 C 组
  post/transfer_window/completion_wait 分解定位（post 占比高 = 控制面
  开销主导；transfer_window 长 = 引擎/链路吞吐低），再定优化项。
- **submit vs 完成分解**：`batch_get_submit`（host 提交耗时）相对
  `batch_get_call_to_stream_completion` 占比 >30% 时单独标注——说明
  队列提交本身重，异步收益打折。
- **cards8 行只留档**：KVAF bench 是单设备 harness，本轮不裁决多卡
  聚合；A 组 cards8 数字仅作 KSC 侧同轮参考，不与 KVAF 比。
- 任何点 correctness 失败 ⇒ 该点数据无效（不影响其他坐标判读）。

---

## §D1 派单：同代码异机性能归因诊断（08f0e60 / 原版 depth=2）（2026-10-15，蓝区）

> 诊断系列（D 系列）与 R 轮优化实验独立编号；本轮只定位问题，不优化。

### 背景与目标

蓝图仓 `xieqiang-hw/nanovllm-DSA-offload_scatter_copy` commit `08f0e601`
（"添加 kvcache_scatter_copy_c8 测试"，树上 23 文件的早期状态，kernel
`QUEUE_DEPTH = 2`）在用户报告的陌生环境（下称 **X 机**：x86_64 + A5，
CANN 9.1.0，宿主机编译跑通）上带宽「很差」，而参照环境（21：aarch64 +
A5，CANN 9.2.0）正常。蓝区已核 `git diff 08f0e601 bb062d2` **csrc 零差异**
（仅 tests/ 新增）⇒ 嫌疑在**环境层**：PCIe 拓扑（switch/降速）、IOMMU、
host NUMA 跨 socket、swapped-memory 驱动路径、CANN 版本差。容器内编译报错
（`std::length_error: vector::reserve`，import 冒烟崩在 build_c8.sh:86）
是 C++ ABI 不匹配，**只解释「容器编不了」，不产生「慢版 kernel」**——宿主机
编译产物是有效被测物。

本轮**只取证定位，不改被测代码**。副产品：21 上首个 depth=2 原版数据
（喂 R7 队列深度扫描基线）。

### 前置核验

1. 本仓 `git pull --ff-only` 后 `git log --oneline -1` 标题含「D1: §D1 派单」。
2. **X 机可达性确认**：绿区能否登录 X 机（/home/f00943536 所在机器，
   x86_64 + A5 + CANN 9.1.0）。**不可达 ⇒ 立即停下**，交付中写明卡在本条，
   蓝区改派为「对方手动执行模板」。
3. X 机上定位蓝图仓路径并记录；`grep "QUEUE_DEPTH = " csrc/src/kvcache_scatter_copy_c8/op_kernel/vllm_a5_kvcache_scatter_copy_c8.cpp`
   确认 `= 2`（未打补丁）；宿主机已有构建产物（`_custom_opp_c8` + .so）
   直接复用，**不重编**。
4. 21 参照：**`git worktree add`** 拉 08f0e60 干净副本另编（worktree 内独立
   构建，产物 _custom_opp_c8 在各自 worktree 内），**不动主 checkout 的
   depth=8 构建**。worktree 建议路径 `/home/h2d_test/nanovllm-d1-depth2`。
   构建用蓝图仓 build_c8.sh 标准流程（CANN 9.2.0 环境照常）。

### 执行命令

> X 机与 21 worktree 跑**同一组命令**对照；X 机用对方原构建产物 + 同一
> python 环境，21 用 worktree 新编。命令里蓝图仓路径按各机实际替换。

**A 环境取证**（两机各跑一遍，原文全回传）：

```bash
uname -m; uname -r
npu-smi info | head -30
cat $ASCEND_HOME_PATH/*/version.cfg 2>/dev/null || cat /usr/local/Ascend/ascend-toolkit/latest/*/version.cfg 2>/dev/null
lspci -tv
for bdf in $(lspci | grep -iE 'huawei|ascend' | awk '{print $1}'); do
  echo "== $bdf =="; lspci -vv -s $bdf 2>/dev/null | grep -E "LnkCap|LnkSta"
  cat /sys/bus/pci/devices/0000:$bdf/numa_node 2>/dev/null
done
dmesg 2>/dev/null | grep -iE "iommu|dmar" | tail -20
numactl -H 2>/dev/null || ls /sys/devices/system/node/
du -sh ~/.ascend 2>/dev/null; ls -la ~/.ascend 2>/dev/null | head
```

**B1 连续 H2D 探针**（本仓 tools/h2d_probe.py，两机各 8 卡逐卡跑）：

```bash
cd /home/h2d_test/copy-scheme-bench   # X 机换本仓实际路径
for d in 0 1 2 3 4 5 6 7; do
  ASCEND_RT_VISIBLE_DEVICES=$d python3 tools/h2d_probe.py --device npu:0
done
```

**B2 单卡 scatter（08f0e60 原版脚本，两机各跑）**：

```bash
cd <蓝图仓>   # X 机=对方仓路径；21=/home/h2d_test/nanovllm-d1-depth2
python3 tests/test_kvcache_scatter_copy.py --device npu:0 --batch-size 32 \
  --source-len 65536 --hbm-slots 8192 --copy-min 300 --copy-max 300 \
  --warmup 10 --iters 1000 --seed 7
```

**C 多卡扩展（08f0e60 原版 harness，两机各跑）**：

```bash
cd <蓝图仓>
CARD_COUNTS="1 2 4 8" BATCH_SIZES="32" COPY_COUNTS="300" \
  bash tests/run_kvcache_scatter_copy_multiprocess.sh
```

**D 分支（仅 X 机，按 A 取证结果触发，两条独立）**：

- D1a：若 A 显示卡与 CPU 跨 socket/NUMA（卡的 numa_node 与默认运行节点不同）：
  用 `numactl --cpunodebind=<卡所在node> --membind=<同node>` 包 B2 与 C 的
  cards8 重跑一遍。
- D1b：把 kernel `QUEUE_DEPTH` 2→8（单行改动，`git apply` 蓝区
  side_blueprint/blueprint_wip_queue8_numa.patch 中 kernel 那部分即可，
  或手动 sed 改这一行）重编，重跑 B2 + C 的 cards8。其余代码不动。

**E（可选，修容器编译，不阻塞）**：X 机容器内
`python3 -c "import torch; print(torch._C._GLIBCXX_USE_CXX11_ABI)"`
与宿主机同命令对比回传。

### 通过标准

- D1-G1：本仓自检末两行 `Ran 47 tests` / `OK`（21 上跑一遍即可）。
- D1-G2：A 取证两机**原文全回传**（每命令一段，不节选）。
- D1-G3：B1 两机各 8 卡 H2D_PROBE 行 + B2 两机单卡 JSON/日志原文。
- D1-G4：C 两机 cards1/2/4/8 汇总表全文（六列口径）。
- D1-G5：D 分支若触发，对应命令与输出原文。

### 判读预案（派单时写死）

- **B1 连续 H2D X ≪ 21（差距 >20%）** ⇒ 链路层实锤：对照 lspci LnkSta
  速率/宽度（x16→x8/x4 或 Gen 降级）或 switch 共享；连续大块搬运几乎只受
  链路影响，此档成立则无需继续深挖随机读路径。
- **B1 相当但 B2/C scatter X ≪ 21** ⇒ 随机读路径嫌疑：IOMMU 页表翻译
  （dmesg 有 DMAR/IOMMU 且 B1 正常时权重最高）、swapped-memory 驱动路径、
  CANN 9.1 vs 9.2 版本差。
- **C 组 cards1 差距小、cards8 差距拉大** ⇒ 共享上游竞争（switch/上行口
  争用），不是单链路问题。
- **D1a 绑定后恢复** ⇒ host NUMA 跨节点实锤（对方机器使用建议 + 一条
  numactl 包装）。
- **D1b 两机 depth2→8 幅度对比** ⇒ 队列深度收益的环境依赖性；若 X 机
  depth8 收益远大于 21，说明 X 机单请求延迟更高（与 IOMMU/链路互证）。
- 任何 case correctness 失败 ⇒ 该 case 数据无效（不影响其他坐标判读）。

---

## §R6e-旧 派单：cards8/bs32 五 copy 档直接对比（npu vs cpu vs hybrid±绑定 + 旧脚本对账）（2026-10-15，蓝区）（已交付+判读）

### 目标

用户指定坐标：**cards8、bs32、copy {100,200,300,500,2048}**。同机同轮产出
直接对比表：旧脚本 npu / 新 bench npu 锚 / cpu±绑定 / hybrid cf0.1±绑定
（cpu/hybrid 带 pretouch，生产形态三件套）。顺带以这 5 个坐标完成新旧
对账（R6d 取消后的缩减版；bs24 对账不做）。

### 前置核验

1. 本仓 `git pull --ff-only` 后 `git log --oneline -1` 标题含「R6e: §R6e 派单」。
2. 蓝图仓 `git -C ../nanovllm-scatter_copy log --oneline -1` = `bb062d2`；
   `grep "QUEUE_DEPTH = " csrc/src/kvcache_scatter_copy_c8/op_kernel/vllm_a5_kvcache_scatter_copy_c8.cpp`
   显示 `= 8`；未重编。
3. 四环境变量（ASCEND_CUSTOM_OPP_PATH / NANOVLLM_A5_INSTALL_OPP_PATH /
   NANOVLLM_CUST_OPAPI_LIB / SCATTER_C8_NUMA_NODES）grep 无匹配。
4. 在 21 执行。**§R6d 已取消（未交付）**：若 R6d 已在跑，停下即可，
   已产生的部分数据留档不判读。

### 执行命令

```bash
cd /home/h2d_test/copy-scheme-bench && git pull --ff-only
cd tests && python3 test_scheme_tools.py && cd ..

NODES=$(ls /sys/devices/system/node/ | grep '^node' | sed 's/^node//' | tr '\n' ' ' | sed 's/ *$//')
NN=$(ls /sys/devices/system/node/ | grep -c '^node')
if [ "$NN" -ge 8 ]; then CYCLE=""; else CYCLE="--numa-cycle"; fi
echo "NODES='$NODES' NN=$NN CYCLE='$CYCLE'"

# G0：旧脚本迷你组（蓝图仓，cards8 bs32 五 copy 档，5 case，蓝区 dry-run 已核）
cd /home/h2d_test/nanovllm-scatter_copy
CARD_COUNTS="8" BATCH_SIZES="32" COPY_COUNTS="100 200 300 500 2048" \
  bash tests/run_scatter_copy_multiprocess.sh 2>&1 | tee run_r6e_old.log

# A：新 bench npu 锚（15 case）
cd /home/h2d_test/copy-scheme-bench
bash run_scheme_sweep.sh --schemes npu --cards 8 --batch-size 32 \
  --copy-count 100 200 300 500 2048 --repeat 3 \
  --results-dir results/r6e/npu8 2>&1 | tee run_r6e_npu.log

# B：cpu（±绑定双跑，pretouch，30 case）
bash run_scheme_sweep.sh --schemes cpu --cards 8 --batch-size 32 \
  --copy-count 100 200 300 500 2048 --window 16 --pretouch \
  --numa-nodes "$NODES" $CYCLE --repeat 3 \
  --results-dir results/r6e/cpu8 2>&1 | tee run_r6e_cpu.log

# C：hybrid cf0.1（±绑定双跑，pretouch，30 case）
bash run_scheme_sweep.sh --schemes hybrid --cpu-fracs 0.1 --hybrid-modes overlap \
  --cards 8 --batch-size 32 --copy-count 100 200 300 500 2048 --window 16 \
  --pretouch --numa-nodes "$NODES" $CYCLE --repeat 3 \
  --results-dir results/r6e/hybrid8 2>&1 | tee run_r6e_hybrid.log

python3 tools/repeat_spread.py results/r6e/npu8 results/r6e/cpu8 results/r6e/hybrid8
```

共 80 case（5/15/30/30，蓝区 dry-run 已核）。默认参数两边一致
（source-len 65536 / hbm-slots 8192 / copy-cap 16384 / warmup 10 /
iters 1000 / seed 7 / --same-seed）。

### 通过标准

- R6e-G1：自检末两行 `Ran 47 tests` / `OK`。
- R6e-G2：三个 manifest 全 passed；75 个 case JSON 全 passed、correctness
  全 true；window==16；cpu/hybrid 组 `pretouch==true`；hybrid 组
  `cpu_frac==0.1`；numa 组每坐标不绑定+绑定成对；G0 旧脚本 5 case 全 passed。
- R6e-G3：`NODES=... NN=... CYCLE=...` 回显行回传。
- R6e-G5：绑定路径日志行 + JSON `config.numa_bind` 一致（沿用 §R6c 口径）。

### 回传格式

交付模板 + 三个目录 `copy_scheme_timing_summary.md` 全文 + 三个 manifest
全文 + `repeat_spread.py` 全部输出原文 + G0 旧脚本 5 个 case 的
cards/bs/copy/avg_bandwidth（或蓝图 summary 文件全文）+ 绑定路径日志行
（`grep -E "NUMA|LAUNCH" run_r6e_*.log` 原文）。

### 判读预案（派单时写死）

- **主对比表**：按 copy 档给 旧脚本 npu / 新 npu 折叠均值 / cpu 绑定 /
  hybrid 绑定（附各自不绑定对照），同轮可比。
- **bs32 复证 S2**：逐 copy 档判——hybrid8 绑定态折叠 ≥ 同轮 npu 锚
  ×1.05 且绑定态极差 ≤10% ⇒ 该档强阳性复证成立。
- **新旧等价（5 点）**：|新 npu 折叠均值 − 旧脚本值|/旧值 ≤5% ⇒ 新旧
  等价在 bs32 坐标实锤；超线列出查因。
- **绑定=修复复核**：cpu/hybrid 绑定态均值 ≥ 不绑定 ⇒ 维持；任一反向
  >10% 标注。
- **共享节点标注**：NN<8 循环映射沿用 §R6c 口径，不与 NN≥8 形态混比。
- 任何 case correctness 失败 ⇒ 该 case 无效（不影响其他坐标判读）。

### 交付（§R6e，2026-10-15，绿区）


**执行环境**：141.61.33.21（work21，主仓原地）。8 卡 Health=Warning + HBM 占用（Util 0%）；**numactl missing**（`which numactl` rc=1）→ **sched_setaffinity fallback 兜底路径**（§R6b/R6c 首验后本轮回放）；`numa_balancing`=1（21 特有，13 为 0）；NUMA 4 节点（node0 0-95/node1 96-191/node2 192-287/node3 288-383）。拓扑：`NODES='0 1 2 3'` `NN=4` `CYCLE='--numa-cycle'`（NN=4<8 → rank→nodes[rank%4] 循环映射，**rank4/5/6/7 与 rank0/1/2/3 共享 node0/1/2/3**——共享节点带宽上限受节点内控制器共享影响，判读标注，不与 NN≥8 形态混比）。蓝图内核 QUEUE_DEPTH=8 未重编；新 bench 三 manifest `queue_depth=default`。

**执行链**：
- R6e-G1：自检末两行 `Ran 47 tests` / `OK` ✓
- R6e-G2：三 manifest 全 `passed` + **75 case 全 passed** + correctness 全 true（per_device 层 data_exact/guard_unchanged 等；npu 5 字段、cpu/hybrid 2 字段，全 true）+ window==16 + cpu/hybrid `pretouch==true` + hybrid `cpu_frac==0.1` + numa 组每坐标不绑定/绑定成对（r6e_verify bad=0；npu 无 numa 变体为预期）+ G0 旧脚本 5 case 全 passed ✓
- R6e-G3：拓扑取证——NODES='0 1 2 3'、NN=4、CYCLE='--numa-cycle'；config.numa_nodes='0,1,2,3,0,1,2,3' 一致 ✓
- R6e-G5：fallback 路径日志行（runner 级 numactl=missing + 每节点 bound=1 + LAUNCH 行 numa_bind=affinity_fallback rank→node 循环映射）与 JSON `config.numa_bind` 一致（cpu8 绑定 15/15、hybrid8 绑定 15/15；不绑定 case numa_bind=none）✓

**主对比表（折叠带宽 `summary.avg_bandwidth` GB/s；绑定/不绑定按文件名 `_numa` 拆分，n=3 均值）**：

| copy | G0 旧脚本 | A 新 npu 折叠 | cpu 绑定 | cpu 不绑定 | hybrid 绑定 | hybrid 不绑定 |
|---|---|---|---|---|---|---|
| 100 | 170.62 | 175.19 | 154.79 | 158.67 | 100.31 | 104.38 |
| 200 | 166.95 | 173.02 | 173.78 | 171.29 | 175.68 | 178.44 |
| 300 | 165.60 | 167.99 | 171.72 | 143.29 | 181.91 | 177.40 |
| 500 | 164.16 | 164.82 | 158.16 | 161.08 | 182.18 | 178.24 |
| 2048 | 163.89 | 162.83 | 115.13 | 113.16 | 176.24 | 175.30 |

per-run 明细（GB/s，各 3 run）：
- npu 折叠：copy100 [173.06,179.00,173.50] / 200 [175.53,168.95,174.59] / 300 [166.41,172.93,164.63] / 500 [164.73,163.61,166.11] / 2048 [160.56,161.18,166.74]
- cpu 绑定：copy100 [154.31,150.15,159.91] / 200 [172.38,170.37,178.57] / 300 [175.58,167.10,172.47] / 500 [164.97,145.93,163.59] / 2048 [119.21,112.09,114.09]
- cpu 不绑定：copy100 [173.27,159.02,143.71] / 200 [167.72,176.59,169.56] / 300 [140.44,116.10,173.33] / 500 [155.38,159.95,167.90] / 2048 [102.44,118.47,118.58]
- hybrid 绑定：copy100 [100.59,99.13,101.22] / 200 [173.88,174.51,178.64] / 300 [181.38,182.32,182.04] / 500 [181.42,183.58,181.53] / 2048 [177.28,177.84,173.59]
- hybrid 不绑定：copy100 [116.14,90.37,106.62] / 200 [180.70,177.44,177.18] / 300 [168.81,181.16,182.24] / 500 [177.52,177.34,179.87] / 2048 [173.78,180.57,171.54]

（注：`copy_scheme_timing_summary.md/csv` 与 `repeat_spread.py` 输出为**绑定+不绑定混聚 n=6** 均值；主对比表按 `_numa` 拆分后的绑定/不绑定各自 n=3 均值。）

**判读输入（绿区只给原始数据与判据比对，结论留蓝区）**：
- **新旧等价（5 点）**：G0 旧 vs A 新 npu 折叠——copy100 +2.7%、copy200 +3.6%、copy300 +1.4%、copy500 +0.4%、copy2048 −0.6%，**全部 ≤5%** ⇒ 新旧等价在 bs32 坐标 5 档全成立（8 卡 ~163-175 GB/s 是两 harness 一致水平，非改前改后差异）。
- **bs32 复证 S2（逐 copy 档：hybrid8 绑定折叠 ≥ 同轮 npu 锚×1.05 且绑定极差 ≤10%）**：
  - copy300：181.91 ≥ 167.99×1.05=176.39 ✓ 且绑定极差 0.21% ✓
  - copy500：182.18 ≥ 164.82×1.05=173.06 ✓ 且绑定极差 0.54% ✓
  - copy2048：176.24 ≥ 162.83×1.05=170.97 ✓ 且绑定极差 1.07% ✓
  - copy200：175.68 vs 173.02×1.05=181.67 ✗（+1.5% <5%）
  - copy100：100.31 vs 175.19×1.05=183.95 ✗（**hybrid copy100 异常低**：绑定 3 run 99.13/100.59/101.22 稳定低值、不绑定 90.37/116.14/106.62 亦低——copy 数小时 hybrid overlap 发射开销主导，连 npu 一半都不到）
- **绑定=修复复核（绑定均值 ≥ 不绑定，反向 >10% 标注）**：
  - cpu：100 −2.4% / 200 +1.5% / 300 **+19.8%** / 500 −1.8% / 2048 +1.7%——无 >10% 反向；copy300 绑定增益显著（不绑定高方差 s=23.45，140.44/116.10/173.33）
  - hybrid：100 −3.9% / 200 −1.5% / 300 +2.5% / 500 +2.2% / 2048 +0.5%——无 >10% 反向；高 copy 档绑定稳定 ≥ 不绑定
- **共享节点标注**：NN=4 循环映射 rank4/5/6/7 共享 node0/1/2/3（LAUNCH 行 rank4→node0 … rank7→node3），绑定态带宽上限受节点内控制器共享影响，不与 NN≥8 形态混比。
- **稳定性标注**：repeat_spread 混聚 n=6——cpu copy100/300/500/2048 与 hybrid copy100 标 UNSTABLE（spread >10%）；按 `_numa` 拆分后 cpu 绑定 s≤4.0、hybrid 绑定 copy300/500 s<1.0（绑定消噪在本轮亦复现）。

**绑定路径日志行（G5 原文，per-case `*_numa_r1.log` grep `NUMA|LAUNCH`）**：

```
A5_COPY_SCHEME_NUMA_FALLBACK node=0 cpus=0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95 bound=1
A5_COPY_SCHEME_NUMA_FALLBACK node=1 cpus=96,97,98,99,100,101,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,158,159,160,161,162,163,164,165,166,167,168,169,170,171,172,173,174,175,176,177,178,179,180,181,182,183,184,185,186,187,188,189,190,191 bound=1
A5_COPY_SCHEME_NUMA_FALLBACK node=2 cpus=192,193,194,195,196,197,198,199,200,201,202,203,204,205,206,207,208,209,210,211,212,213,214,215,216,217,218,219,220,221,222,223,224,225,226,227,228,229,230,231,232,233,234,235,236,237,238,239,240,241,242,243,244,245,246,247,248,249,250,251,252,253,254,255,256,257,258,259,260,261,262,263,264,265,266,267,268,269,270,271,272,273,274,275,276,277,278,279,280,281,282,283,284,285,286,287 bound=1
A5_COPY_SCHEME_NUMA_FALLBACK node=3 cpus=288,289,290,291,292,293,294,295,296,297,298,299,300,301,302,303,304,305,306,307,308,309,310,311,312,313,314,315,316,317,318,319,320,321,322,323,324,325,326,327,328,329,330,331,332,333,334,335,336,337,338,339,340,341,342,343,344,345,346,347,348,349,350,351,352,353,354,355,356,357,358,359,360,361,362,363,364,365,366,367,368,369,370,371,372,373,374,375,376,377,378,379,380,381,382,383 bound=1
A5_COPY_SCHEME_NUMA_FALLBACK numactl=missing fallback=sched_setaffinity nodes=0,1,2,3,0,1,2,3
```

```
A5_COPY_SCHEME_LAUNCH rank=0 device=npu:0 scheme=cpu seed=7 numa_node=0 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=1 device=npu:1 scheme=cpu seed=7 numa_node=1 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=2 device=npu:2 scheme=cpu seed=7 numa_node=2 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=3 device=npu:3 scheme=cpu seed=7 numa_node=3 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=4 device=npu:4 scheme=cpu seed=7 numa_node=0 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=5 device=npu:5 scheme=cpu seed=7 numa_node=1 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=6 device=npu:6 scheme=cpu seed=7 numa_node=2 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=7 device=npu:7 scheme=cpu seed=7 numa_node=3 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=0 device=npu:0 scheme=cpu seed=7 numa_node=unbound numa_bind=unbound
A5_COPY_SCHEME_LAUNCH rank=1 device=npu:1 scheme=cpu seed=7 numa_node=unbound numa_bind=unbound
```

（不绑定 case LAUNCH 行 `numa_node=unbound numa_bind=unbound`，与绑定成对。）

**G0 旧脚本 5 case（蓝图 `results/scatter_copy_a5_c8`，device_count=8）**：

```
cards8 bs32 copy100 : 170.621 GB/s all_correct=True
cards8 bs32 copy200 : 166.951 GB/s all_correct=True
cards8 bs32 copy300 : 165.599 GB/s all_correct=True
cards8 bs32 copy500 : 164.163 GB/s all_correct=True
cards8 bs32 copy2048: 163.886 GB/s all_correct=True
```

**三个 `copy_scheme_timing_summary.md` 全文**：

```
# results/r6e/npu8

| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| npu | 0 | 0.5 | overlap | 8 | 32 | 100 | 96.264 | 101.697 | 175.188 |
| npu | 0 | 0.5 | overlap | 8 | 32 | 200 | 196.038 | 209.202 | 173.021 |
| npu | 0 | 0.5 | overlap | 8 | 32 | 300 | 301.085 | 313.694 | 167.989 |
| npu | 0 | 0.5 | overlap | 8 | 32 | 500 | 509.873 | 529.340 | 164.815 |
| npu | 0 | 0.5 | overlap | 8 | 32 | 2048 | 2116.722 | 2194.793 | 162.826 |
```

```
# results/r6e/cpu8

| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cpu | 0 | 0.5 | overlap | 8 | 32 | 100 | 108.358 | 123.712 | 156.730 |
| cpu | 0 | 0.5 | overlap | 8 | 32 | 200 | 196.514 | 224.157 | 172.531 |
| cpu | 0 | 0.5 | overlap | 8 | 32 | 300 | 330.048 | 358.473 | 157.505 |
| cpu | 0 | 0.5 | overlap | 8 | 32 | 500 | 535.780 | 605.823 | 159.619 |
| cpu | 0 | 0.5 | overlap | 8 | 32 | 2048 | 3116.242 | 3698.931 | 114.148 |
```

```
# results/r6e/hybrid8

| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| hybrid | 0 | 0.1 | overlap | 8 | 32 | 100 | 165.883 | 184.676 | 102.345 |
| hybrid | 0 | 0.1 | overlap | 8 | 32 | 200 | 190.060 | 200.218 | 177.059 |
| hybrid | 0 | 0.1 | overlap | 8 | 32 | 300 | 282.019 | 300.378 | 179.659 |
| hybrid | 0 | 0.1 | overlap | 8 | 32 | 500 | 467.957 | 496.251 | 180.210 |
| hybrid | 0 | 0.1 | overlap | 8 | 32 | 2048 | 1961.702 | 2040.413 | 175.765 |
```

**三个 `copy_scheme_run_manifest.json` 全文**：

```json
{
  "schema_version": 2,
  "status": "passed",
  "dtype": "c8",
  "timestamp_utc": "2026-10-15T08:37:35.072161+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "queue_depth": "default",
  "case_files": [
    "npu_cards8_bs32_copy100_rf0p0_r1.json",
    "npu_cards8_bs32_copy100_rf0p0_r2.json",
    "npu_cards8_bs32_copy100_rf0p0_r3.json",
    "npu_cards8_bs32_copy200_rf0p0_r1.json",
    "npu_cards8_bs32_copy200_rf0p0_r2.json",
    "npu_cards8_bs32_copy200_rf0p0_r3.json",
    "npu_cards8_bs32_copy300_rf0p0_r1.json",
    "npu_cards8_bs32_copy300_rf0p0_r2.json",
    "npu_cards8_bs32_copy300_rf0p0_r3.json",
    "npu_cards8_bs32_copy500_rf0p0_r1.json",
    "npu_cards8_bs32_copy500_rf0p0_r2.json",
    "npu_cards8_bs32_copy500_rf0p0_r3.json",
    "npu_cards8_bs32_copy2048_rf0p0_r1.json",
    "npu_cards8_bs32_copy2048_rf0p0_r2.json",
    "npu_cards8_bs32_copy2048_rf0p0_r3.json"
  ]
}
```

```json
{
  "schema_version": 2,
  "status": "passed",
  "dtype": "c8",
  "timestamp_utc": "2026-10-15T08:47:58.329920+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "queue_depth": "default",
  "case_files": [
    "hybrid_cards8_bs32_copy100_rf0p0_cf0p1_overlap_r1.json",
    "hybrid_cards8_bs32_copy100_rf0p0_cf0p1_overlap_r2.json",
    "hybrid_cards8_bs32_copy100_rf0p0_cf0p1_overlap_r3.json",
    "hybrid_cards8_bs32_copy200_rf0p0_cf0p1_overlap_r1.json",
    "hybrid_cards8_bs32_copy200_rf0p0_cf0p1_overlap_r2.json",
    "hybrid_cards8_bs32_copy200_rf0p0_cf0p1_overlap_r3.json",
    "hybrid_cards8_bs32_copy300_rf0p0_cf0p1_overlap_r1.json",
    "hybrid_cards8_bs32_copy300_rf0p0_cf0p1_overlap_r2.json",
    "hybrid_cards8_bs32_copy300_rf0p0_cf0p1_overlap_r3.json",
    "hybrid_cards8_bs32_copy500_rf0p0_cf0p1_overlap_r1.json",
    "hybrid_cards8_bs32_copy500_rf0p0_cf0p1_overlap_r2.json",
    "hybrid_cards8_bs32_copy500_rf0p0_cf0p1_overlap_r3.json",
    "hybrid_cards8_bs32_copy2048_rf0p0_cf0p1_overlap_r1.json",
    "hybrid_cards8_bs32_copy2048_rf0p0_cf0p1_overlap_r2.json",
    "hybrid_cards8_bs32_copy2048_rf0p0_cf0p1_overlap_r3.json",
    "hybrid_cards8_bs32_copy100_rf0p0_cf0p1_overlap_numa_r1.json",
    "hybrid_cards8_bs32_copy100_rf0p0_cf0p1_overlap_numa_r2.json",
    "hybrid_cards8_bs32_copy100_rf0p0_cf0p1_overlap_numa_r3.json",
    "hybrid_cards8_bs32_copy200_rf0p0_cf0p1_overlap_numa_r1.json",
    "hybrid_cards8_bs32_copy200_rf0p0_cf0p1_overlap_numa_r2.json",
    "hybrid_cards8_bs32_copy200_rf0p0_cf0p1_overlap_numa_r3.json",
    "hybrid_cards8_bs32_copy300_rf0p0_cf0p1_overlap_numa_r1.json",
    "hybrid_cards8_bs32_copy300_rf0p0_cf0p1_overlap_numa_r2.json",
    "hybrid_cards8_bs32_copy300_rf0p0_cf0p1_overlap_numa_r3.json",
    "hybrid_cards8_bs32_copy500_rf0p0_cf0p1_overlap_numa_r1.json",
    "hybrid_cards8_bs32_copy500_rf0p0_cf0p1_overlap_numa_r2.json",
    "hybrid_cards8_bs32_copy500_rf0p0_cf0p1_overlap_numa_r3.json",
    "hybrid_cards8_bs32_copy2048_rf0p0_cf0p1_overlap_numa_r1.json",
    "hybrid_cards8_bs32_copy2048_rf0p0_cf0p1_overlap_numa_r2.json",
    "hybrid_cards8_bs32_copy2048_rf0p0_cf0p1_overlap_numa_r3.json"
  ]
}
```

```json
{
  "schema_version": 2,
  "status": "passed",
  "dtype": "c8",
  "timestamp_utc": "2026-10-15T08:41:10.815881+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "queue_depth": "default",
  "case_files": [
    "cpu_cards8_bs32_copy100_rf0p0_r1.json",
    "cpu_cards8_bs32_copy100_rf0p0_r2.json",
    "cpu_cards8_bs32_copy100_rf0p0_r3.json",
    "cpu_cards8_bs32_copy200_rf0p0_r1.json",
    "cpu_cards8_bs32_copy200_rf0p0_r2.json",
    "cpu_cards8_bs32_copy200_rf0p0_r3.json",
    "cpu_cards8_bs32_copy300_rf0p0_r1.json",
    "cpu_cards8_bs32_copy300_rf0p0_r2.json",
    "cpu_cards8_bs32_copy300_rf0p0_r3.json",
    "cpu_cards8_bs32_copy500_rf0p0_r1.json",
    "cpu_cards8_bs32_copy500_rf0p0_r2.json",
    "cpu_cards8_bs32_copy500_rf0p0_r3.json",
    "cpu_cards8_bs32_copy2048_rf0p0_r1.json",
    "cpu_cards8_bs32_copy2048_rf0p0_r2.json",
    "cpu_cards8_bs32_copy2048_rf0p0_r3.json",
    "cpu_cards8_bs32_copy100_rf0p0_numa_r1.json",
    "cpu_cards8_bs32_copy100_rf0p0_numa_r2.json",
    "cpu_cards8_bs32_copy100_rf0p0_numa_r3.json",
    "cpu_cards8_bs32_copy200_rf0p0_numa_r1.json",
    "cpu_cards8_bs32_copy200_rf0p0_numa_r2.json",
    "cpu_cards8_bs32_copy200_rf0p0_numa_r3.json",
    "cpu_cards8_bs32_copy300_rf0p0_numa_r1.json",
    "cpu_cards8_bs32_copy300_rf0p0_numa_r2.json",
    "cpu_cards8_bs32_copy300_rf0p0_numa_r3.json",
    "cpu_cards8_bs32_copy500_rf0p0_numa_r1.json",
    "cpu_cards8_bs32_copy500_rf0p0_numa_r2.json",
    "cpu_cards8_bs32_copy500_rf0p0_numa_r3.json",
    "cpu_cards8_bs32_copy2048_rf0p0_numa_r1.json",
    "cpu_cards8_bs32_copy2048_rf0p0_numa_r2.json",
    "cpu_cards8_bs32_copy2048_rf0p0_numa_r3.json"
  ]
}
```

**`repeat_spread.py` 全部输出原文**：

```
# results/r6e/npu8
coordinate                                    n      mean      std  spread%  runs
npu/0.0/0.5/overlap/8/32/100/100              3   175.188    3.305    3.43%  173.06 179.00 173.50
npu/0.0/0.5/overlap/8/32/200/200              3   173.021    3.558    3.89%  175.53 168.95 174.59
npu/0.0/0.5/overlap/8/32/300/300              3   167.989    4.371    5.04%  166.41 172.93 164.63
npu/0.0/0.5/overlap/8/32/500/500              3   164.815    1.252    1.53%  164.73 163.61 166.11
npu/0.0/0.5/overlap/8/32/2048/2048            3   162.826    3.400    3.85%  160.56 161.18 166.74

# results/r6e/cpu8
coordinate                                    n      mean      std  spread%  runs
cpu/0.0/0.5/overlap/8/32/100/100              6   156.730   10.075   20.57%  150.15 159.91 154.31 173.27 159.02 143.71  <-- UNSTABLE
cpu/0.0/0.5/overlap/8/32/200/200              6   172.531    4.234    6.47%  172.38 178.57 170.37 176.59 169.56 167.72
cpu/0.0/0.5/overlap/8/32/300/300              6   157.505   24.080   51.24%  172.47 175.58 167.10 140.44 116.10 173.33  <-- UNSTABLE
cpu/0.0/0.5/overlap/8/32/500/500              6   159.619    7.980   15.05%  163.59 145.93 164.97 159.95 167.90 155.38  <-- UNSTABLE
cpu/0.0/0.5/overlap/8/32/2048/2048            6   114.148    6.408   16.37%  119.21 112.09 114.09 118.47 118.58 102.44  <-- UNSTABLE

# results/r6e/hybrid8
coordinate                                    n      mean      std  spread%  runs
hybrid/0.0/0.1/overlap/8/32/100/100           6   102.345    8.562   28.51%  99.13 101.22 100.59 106.62 116.14 90.37  <-- UNSTABLE
hybrid/0.0/0.1/overlap/8/32/200/200           6   177.059    2.549    3.92%  173.88 174.51 178.64 177.44 177.18 180.70
hybrid/0.0/0.1/overlap/8/32/300/300           6   179.659    5.333    8.00%  181.38 182.04 182.32 182.24 168.81 181.16
hybrid/0.0/0.1/overlap/8/32/500/500           6   180.210    2.459    3.52%  181.42 181.53 183.58 179.87 177.52 177.34
hybrid/0.0/0.1/overlap/8/32/2048/2048         6   175.765    3.354    5.27%  173.59 177.28 177.84 180.57 171.54 173.78
```

**数据出处**：results/r6e/ 下 npu8、cpu8、hybrid8 三目录（21 上，gitignore 不入库）+ run_r6e_old/npu/cpu/hybrid.log + run_r6e_spread.log；阶段 RC 全 0（STAGE_G0/A/B/C/SPREAD_RC=0）。commit 回填见 history.md。

### 判读（§R6e，2026-10-15，蓝区）

全部关键数字经蓝区从 per-run 明细独立复算，与绿区交付值逐位相符。

**裁决 1（新旧等价）：实锤。** G0 旧脚本 vs 新 bench npu 锚 5 点偏差
+2.7/+3.6/+1.4/+0.4/−0.6%，全部 ≤5% ⇒ fork 后的 harness 改写无回归。
cards8/bs32 坐标下 scatter_copy 的实测水平 = **163–175 GB/s**，两个
harness 同轮互证；「只有 160G」不是改写造成的。用户记忆中的 ~230 GB/s
已定位出处：蓝区本地 `h2d_bandwidth_vs_bs.svg`（2026-09-16 H2D 专项，
「8卡绑核 vs 单卡，copy=200」bs16 = **232.4**，bs_sweep 两轮峰区
~240–260）——口径是 **H2D 段有效带宽（连续 staging 大块搬运 + 绑核）**，
不是 scatter_copy kernel 离散 656B 随机行的端到端带宽，两者不可比，
不再追溯。

**裁决 2（S2 bs32 复证）：3/5 档成立。** copy300/500/2048 命中双条件——
hybrid 绑定 181.91/182.18/176.24 ≥ 同轮 npu 锚×1.05（176.39/173.06/
170.97），绑定极差 0.21%/0.54%/1.07% ≤10%。⇒ **生产形态（hybrid
cf=0.1 + pretouch + NUMA 绑定 + window16）在 bs32 中/大 miss 档
（≥300）优势复证**，与 R6c（bs24/copy300，+6.8%）互洽；bs32 增益
+8.2%~+10.5%。copy200（+1.5%）不达线，为过渡档。

**裁决 3（hybrid copy100 异常）：新发现 ⇒ 门控结论。** 绑定 3 run
99.13/100.59/101.22、不绑定 90.37~116.14，稳定仅为同轮 npu 的 ~57%——
copy 数小时 CPU 段份额（cf=0.1 → 每请求 ~10 token）藏不住 overlap 的
发射/旁流固定开销，反拖整体。⇒ **生产形态必须加门控：copy 数低于阈值
回退纯 npu kernel**；阈值待测定（候选 R8：copy∈{100,150,200,250,300}
×hybrid±绑定扫描定拐点）。

**裁决 4（cpu 全量方案）：大 copy 档出局确认。** cpu 绑定 copy2048 塌至
115.13（全量 gather 43MB/die/iter，CPU 段成本线性超过 kernel 节省）；
copy200/300 档 cpu 绑定（173.78/171.72）可追平 npu 锚但无优势。⇒ cpu
全量仅作对照；cpu-delta（只搬 miss 增量，驻留路线）不受此限，保留。

**裁决 5（绑定=修复复核）：维持。** cpu copy300 绑定 +19.8%（不绑定高
方差 140.44/116.10/173.33 复现落点抽签形态，绑定消噪）；hybrid 全档
绑定影响 −3.9%~+2.5%，无 >10% 反向。⇒ pretouch + NUMA 绑定继续作为
cpu/hybrid 默认配置。

**共享节点/环境标注**：NN=4 --numa-cycle，rank4-7 与 rank0-3 共享
node0-3（绑定态上限含节点内控制器共享因素，不与 NN≥8 形态混比）；
numa_balancing=1（21 特有）；21 无 numactl，sched_setaffinity
fallback 路径再次验证通过（runner/worker/JSON 三方一致）。

**下一步**：(a) 生产形态结论交用户（本判读即输入）；(b) R7 队列深度
扫描顺延排队；(c) 新增候选 R8 copy 数门控阈值扫描；(d) +26% 高簇成因
（R5 cf0.4 偶发 216/217）仍为开放问题——稳态收益 +6.8~10.5% 已实锤，
高簇不阻塞。

---

## §R6d-旧 派单：新旧带宽测试同机同轮对账（2026-10-15，蓝区）（取消：未交付，用户优先 bs32 直接对比；新旧对账缩为 §R6e G0 迷你组，bs24 对账不做）

### 目标

用户关切：fork 后的新 bench 与蓝图旧测试的 npu 带宽数字是否一致。同机同轮
对账：(a) 旧脚本跑历史矩阵留档；(b) 新 bench npu 方案跑重叠坐标 repeat 3；
(c) 重叠 12 坐标逐点偏差 ≤5% ⇒ 新旧等价实锤，此后历史曲线与本 bench 数字
互认同一口径。

### 前置核验

1. 本仓 `git pull --ff-only` 后 `git log --oneline -1` 标题含「R6d: §R6d 派单」。
2. 蓝图仓 `git -C ../nanovllm-scatter_copy log --oneline -1` = `bb062d2`；
   `grep "QUEUE_DEPTH = " csrc/src/kvcache_scatter_copy_c8/op_kernel/vllm_a5_kvcache_scatter_copy_c8.cpp`
   显示 `= 8`；未重编。
3. 四环境变量（ASCEND_CUSTOM_OPP_PATH / NANOVLLM_A5_INSTALL_OPP_PATH /
   NANOVLLM_CUST_OPAPI_LIB / SCATTER_C8_NUMA_NODES）grep 无匹配。
4. 在 21 执行（两仓并排 /home/h2d_test，蓝图已构建；21 上蓝图仓可读）。

### 执行命令

```bash
cd /home/h2d_test/copy-scheme-bench && git pull --ff-only
cd tests && python3 test_scheme_tools.py && cd ..

# A：旧脚本历史矩阵（蓝图仓，原接口原默认，96 case，蓝区 dry-run 已核）
cd /home/h2d_test/nanovllm-scatter_copy
CARD_COUNTS="1 2 4 8" BATCH_SIZES="8 16 24 32" \
COPY_COUNTS="0 100 200 300 500 2048" \
  bash tests/run_scatter_copy_multiprocess.sh 2>&1 | tee run_r6d_old.log

# B：新 bench npu 重叠坐标（bs24 × copy 0/100/300 × cards 1/2/4/8 ×repeat 3，36 case）
cd /home/h2d_test/copy-scheme-bench
bash run_scheme_sweep.sh --schemes npu --cards 1 2 4 8 --batch-size 24 \
  --copy-count 0 100 300 --repeat 3 --results-dir results/r6d/npu_matrix \
  2>&1 | tee run_r6d_new.log
```

两组的 source-len 65536 / hbm-slots 8192 / copy-cap 16384 / warmup 10 /
iters 1000 / seed 7 / --same-seed 默认值完全一致（蓝区已核两边 dry-run
命令行逐参数相同），差异只剩 runner 外壳。

### 通过标准

- R6d-G1：自检末两行 `Ran 47 tests` / `OK`。
- R6d-G2：旧脚本 96 个 case JSON 全 passed（蓝图六列口径，结果在蓝图仓
  results/scatter_copy_a5_c8/）；新 bench manifest passed、36 case 全
  passed、correctness 全 true。
- R6d-G3：回传旧脚本结果目录的 summary/markdown 全文（或逐 case JSON 的
  cards/bs/copy/avg_bandwidth 列表）+ 新 bench timing_summary 全文。

### 回传格式

交付模板 + 上述两个 summary 全文 + 两个 manifest/结果清单 + 重叠坐标对照表
（bs24 × copy{0,100,300} × cards{1,2,4,8} 共 12 点：旧值 / 新 repeat 折叠
均值 / 新极差 / 偏差%）。

### 判读预案（派单时写死）

- **等价判据**：12 个重叠坐标 |新折叠均值 − 旧值|/旧值 ≤5% 且新极差 ≤5%
  ⇒ 新旧等价实锤；任一坐标超线列出并查因。
- copy0 行带宽恒 0 不参与偏差判据，只核 avg_us 量级（~11µs 固定开销）。
- 非重叠坐标（bs8/16/32、copy200/500/2048）只留档，不与历史曲线跨轮比
  （机器状态已变），作为同轮刷新的新基线。
- 任何 case correctness 失败 ⇒ 该 case 无效。

---

## §R6c-旧 派单：S2 cards8 原坐标裁决 + fallback 路径首验（2026-10-15，蓝区）（已交付+判读）

> 注：派单节原文（前置核验/命令/通过标准/判读预案五条）见 commit
> `7f8427f`——绿区交付时覆盖了派单节，append-only 纪律不追溯改写，
> 此处恢复标题维持结构；判读即按 `7f8427f` 写死的预案执行。

### 交付（§R6c，2026-10-15，绿区）


**执行环境**：141.61.33.21（work21，主仓原地）。8 卡 Health=Warning + HBM 占用（Util 0%），R1-R5 同状态可跑；**numactl missing**（`which numactl` rc=1）→ **sched_setaffinity fallback 兜底路径首验**；`/proc/sys/kernel/numa_balancing`=**1**（21 特有，13 为 0，判读注意）；NUMA 4 节点（node0 0-95/node1 96-191/node2 192-287/node3 288-383）。拓扑：`NODES='0 1 2 3'` `NN=4` `CYCLE='--numa-cycle'`（NN=4<8 → A/B 组 cards 8 不变，rank→nodes[rank%4] 循环映射，**rank4/5/6/7 与 rank0/1/2/3 共享 node0/1/2/3**——共享节点带宽上限受节点内控制器共享影响，判读标注，不与 NN≥8 形态混比）。

**执行链**：
- R6c-G1：自检末两行 `Ran 47 tests` / `OK` ✓
- R6c-G2：三 manifest 全 `passed` + 17 case 全 passed + correctness 全 true（per_device 层 data_exact/guard_unchanged/zero_count/...）+ window==16 + hybrid cpu_frac==0.1（r6c_verify bad=0，G2 ALL PASS）✓
- R6c-G3：拓扑取证——NODES='0 1 2 3'、NN=4、CYCLE='--numa-cycle'；cpulist node0 0-95 / node1 96-191 / node2 192-287 / node3 288-383；numa_balancing=1；which numactl → missing（rc=1）✓
- R6c-G4（非门槛）：anchor8 折叠 **168.512** vs §R5 171.343 = **-1.65%**（≤15%，21 同机可比）✓
- R6c-G5：fallback 路径日志行（runner 级 + 每 worker bound=1 + LAUNCH 行 numa_bind=affinity_fallback）与 JSON `config.numa_bind=affinity_fallback` 一致（cpu8 绑定 3/3、hybrid8 绑定 4/4 全一致）✓

**关键实测（折叠带宽 `summary.avg_bandwidth`，极差=(max-min)/min，绑定/不绑定按文件名 `_numa` 拆分）**：

| 组 | 绑定均值 | 绑定极差 | 不绑定均值 | 不绑定极差 | 绑定 vs 不绑定 |
|---|---|---|---|---|---|
| numa_cpu8 | 170.603 | 9.53% | 138.285 | 28.98% | **+23.37%** |
| numa_hybrid8 | 180.019 | 0.99% | 168.721 | 19.24% | **+6.70%** |
| anchor8 | 168.512 | 0.37% | - | - | - |

per-run 明细（GB/s）：
- numa_cpu8 bind: 180.864 / 165.816 / 165.129（avg_us 224.517）；unbind: 160.718 / 129.532 / 124.605（avg_us 285.137）
- numa_hybrid8 bind: 180.099 / 179.934 / 180.907 / 179.133（avg_us 210.027）；unbind: 180.024 / 164.111 / 150.977 / 179.771（avg_us 229.742）
- anchor8: 168.821 / 168.202 / 168.512（avg_us 224.449）

**判读输入（绿区只给原始数据与判据比对，结论留蓝区）**：
- **抽签复现裁决输入**：numa_cpu8 不绑定态极差 **28.98% >15%** ✓（R5 噪声原坐标复现）且绑定态极差 **9.53% ≤10%** ✓ ⇒ 两条件同时满足。
- **S2 升级判据输入**：numa_hybrid8 绑定态极差 **0.99% ≤10%** ✓；绑定折叠 **180.019** vs anchor8 168.512×1.05=**176.938** ⇒ 180.019 **≥176.938**（≥×1.05）✓；且 ≥ anchor8 168.512 ✓。
- **绑定均值方向**：cpu8 +23.37%、hybrid8 +6.70% 均绑定 ≥ 不绑定 ⇒ 维持「绑定=修复」方向（无反向 >10%）。
- **fallback 验证**：numactl missing 时日志见 G5 兜底行（见下原文）；JSON config.numa_bind=affinity_fallback + numa_nodes='0,1,2,3,0,1,2,3' 与日志一致。
- **共享节点标注**：NN=4 循环映射 rank4/5/6/7 共享 node0/1/2/3，绑定态带宽上限受节点内控制器共享影响，不与 NN≥8 形态混比。

**绑定路径日志行（G5 原文，`grep -E "NUMA|LAUNCH" run_r6c_*.log`）**：

```


A5_COPY_SCHEME_NUMA_FALLBACK node=0 cpus=0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95 bound=1
A5_COPY_SCHEME_NUMA_FALLBACK node=1 cpus=96,97,98,99,100,101,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,158,159,160,161,162,163,164,165,166,167,168,169,170,171,172,173,174,175,176,177,178,179,180,181,182,183,184,185,186,187,188,189,190,191 bound=1
A5_COPY_SCHEME_NUMA_FALLBACK node=2 cpus=192,193,194,195,196,197,198,199,200,201,202,203,204,205,206,207,208,209,210,211,212,213,214,215,216,217,218,219,220,221,222,223,224,225,226,227,228,229,230,231,232,233,234,235,236,237,238,239,240,241,242,243,244,245,246,247,248,249,250,251,252,253,254,255,256,257,258,259,260,261,262,263,264,265,266,267,268,269,270,271,272,273,274,275,276,277,278,279,280,281,282,283,284,285,286,287 bound=1
A5_COPY_SCHEME_NUMA_FALLBACK node=3 cpus=288,289,290,291,292,293,294,295,296,297,298,299,300,301,302,303,304,305,306,307,308,309,310,311,312,313,314,315,316,317,318,319,320,321,322,323,324,325,326,327,328,329,330,331,332,333,334,335,336,337,338,339,340,341,342,343,344,345,346,347,348,349,350,351,352,353,354,355,356,357,358,359,360,361,362,363,364,365,366,367,368,369,370,371,372,373,374,375,376,377,378,379,380,381,382,383 bound=1
A5_COPY_SCHEME_NUMA_FALLBACK numactl=missing fallback=sched_setaffinity nodes=0,1,2,3,0,1,2,3


```
```

A5_COPY_SCHEME_LAUNCH rank=0 device=npu:0 scheme=cpu seed=7 numa_node=0 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=0 device=npu:0 scheme=hybrid seed=7 numa_node=0 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=1 device=npu:1 scheme=cpu seed=7 numa_node=1 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=1 device=npu:1 scheme=hybrid seed=7 numa_node=1 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=2 device=npu:2 scheme=cpu seed=7 numa_node=2 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=2 device=npu:2 scheme=hybrid seed=7 numa_node=2 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=3 device=npu:3 scheme=cpu seed=7 numa_node=3 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=3 device=npu:3 scheme=hybrid seed=7 numa_node=3 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=4 device=npu:4 scheme=cpu seed=7 numa_node=0 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=4 device=npu:4 scheme=hybrid seed=7 numa_node=0 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=5 device=npu:5 scheme=cpu seed=7 numa_node=1 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=5 device=npu:5 scheme=hybrid seed=7 numa_node=1 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=6 device=npu:6 scheme=cpu seed=7 numa_node=2 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=6 device=npu:6 scheme=hybrid seed=7 numa_node=2 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=7 device=npu:7 scheme=cpu seed=7 numa_node=3 numa_bind=affinity_fallback
A5_COPY_SCHEME_LAUNCH rank=7 device=npu:7 scheme=hybrid seed=7 numa_node=3 numa_bind=affinity_fallback


```

**2 case JSON（numa_hybrid8 绑定 r1 / 不绑定 r1，config+summary+per_device[0].performance）**：
- 绑定 r1（hybrid_cards8_bs24_copy300_rf0p0_cf0p1_overlap_numa_r1.json）：bw=180.099、avg_us=210.027、p50=209.995、p99=226.761、phases launch_to_gather_done=172.032 / h2d_scatter_tail=38.566 / kernel_event=202.486；config window=16 cpu_frac=0.1 hybrid_mode=overlap numa_bind=affinity_fallback numa_nodes='0,1,2,3,0,1,2,3'。
- 不绑定 r1（hybrid_cards8_bs24_copy300_rf0p0_cf0p1_overlap_r1.json）：bw=180.024、avg_us=209.927、p50=204.858、p99=228.841、phases launch_to_gather_done=152.953 / h2d_scatter_tail=52.384 / kernel_event=197.101；config numa_bind=none numa_nodes=''。
- 注：per_device 仅含 correctness 断言（全 true）；per-die gather/kernel 相位在 per_device[0].performance.phases——r1 单次绑定/不绑定相位相近，差异主要在 r2-r4 稳定性（绑定全落在 179.1-180.9，不绑定 r2/r3 跌至 150.98/164.11）。

**三个 `copy_scheme_timing_summary.md` 全文**：



```

# results/r6c/numa_cpu8

| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 300 | 254.827 | 309.215 | 154.444 |

```

```

# results/r6c/numa_hybrid8

| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| hybrid | 0 | 0.1 | overlap | 8 | 24 | 300 | 219.885 | 239.401 | 174.370 |

```

```

# results/r6c/anchor8

| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| npu | 0 | 0.5 | overlap | 8 | 24 | 300 | 224.449 | 232.899 | 168.512 |

```


**三个 `copy_scheme_run_manifest.json` 全文**：



```

# results/r6c/numa_cpu8/copy_scheme_run_manifest.json

{
  "schema_version": 2,
  "status": "passed",
  "dtype": "c8",
  "timestamp_utc": "2026-10-15T07:33:29.044004+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "queue_depth": "default",
  "case_files": [
    "cpu_cards8_bs24_copy300_rf0p0_r1.json",
    "cpu_cards8_bs24_copy300_rf0p0_r2.json",
    "cpu_cards8_bs24_copy300_rf0p0_r3.json",
    "cpu_cards8_bs24_copy300_rf0p0_numa_r1.json",
    "cpu_cards8_bs24_copy300_rf0p0_numa_r2.json",
    "cpu_cards8_bs24_copy300_rf0p0_numa_r3.json"
  ]
}

```

```

# results/r6c/numa_hybrid8/copy_scheme_run_manifest.json

{
  "schema_version": 2,
  "status": "passed",
  "dtype": "c8",
  "timestamp_utc": "2026-10-15T07:34:54.223221+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "queue_depth": "default",
  "case_files": [
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p1_overlap_r1.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p1_overlap_r2.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p1_overlap_r3.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p1_overlap_r4.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p1_overlap_numa_r1.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p1_overlap_numa_r2.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p1_overlap_numa_r3.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p1_overlap_numa_r4.json"
  ]
}

```

```

# results/r6c/anchor8/copy_scheme_run_manifest.json

{
  "schema_version": 2,
  "status": "passed",
  "dtype": "c8",
  "timestamp_utc": "2026-10-15T07:36:39.976324+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "queue_depth": "default",
  "case_files": [
    "npu_cards8_bs24_copy300_rf0p0_r1.json",
    "npu_cards8_bs24_copy300_rf0p0_r2.json",
    "npu_cards8_bs24_copy300_rf0p0_r3.json"
  ]
}

```


**`repeat_spread.py` 输出全文**（run_r6c_spread.log，含 r5 对照）：

```

# results/r6c/numa_cpu8
coordinate                                    n      mean      std  spread%  runs
cpu/0.0/0.5/overlap/8/24/300/300              6   154.444   22.324   45.15%  180.86 165.82 165.13 160.72 129.53 124.60  <-- UNSTABLE

# results/r6c/numa_hybrid8
coordinate                                    n      mean      std  spread%  runs
hybrid/0.0/0.1/overlap/8/24/300/300           8   174.370   10.973   19.82%  180.10 179.93 180.91 179.13 180.02 164.11 150.98 179.77  <-- UNSTABLE

# results/r6c/anchor8
coordinate                                    n      mean      std  spread%  runs
npu/0.0/0.5/overlap/8/24/300/300              3   168.512    0.309    0.37%  168.82 168.20 168.51

# results/r5/confirm8
coordinate                                    n      mean      std  spread%  runs
hybrid/0.0/0.1/overlap/8/24/300/300           6   167.849   21.593   43.05%  180.82 126.41 180.16 178.20 161.54 179.97  <-- UNSTABLE
hybrid/0.0/0.15/overlap/8/24/300/300          6   161.415   22.146   47.81%  162.05 152.45 160.43 183.76 184.78 125.01  <-- UNSTABLE
hybrid/0.0/0.3/overlap/8/24/300/300           6   164.463   30.908   63.24%  187.23 155.81 191.13 141.65 192.83 118.13  <-- UNSTABLE
hybrid/0.0/0.4/overlap/8/24/300/300           6   178.175   35.383   58.83%  216.04 182.23 136.79 217.27 178.16 138.56  <-- UNSTABLE

# results/r5/anchor8
coordinate                                    n      mean      std  spread%  runs
npu/0.0/0.5/overlap/8/24/300/300              6   171.343    2.150    3.96%  171.78 170.64 174.48 171.76 171.57 167.82


```

**数据出处**：results/r6c/{numa_cpu8,numa_hybrid8,anchor8}（gitignore 不入库）+ run_r6c_{cpu,hybrid,anchor,spread}.log + /tmp/run_r6c_wrapper.log。

判读留蓝区（绿区不改码，只回传原始数据）。

### 判读（§R6c，2026-10-15，蓝区）

全部关键数字经蓝区从 runs 明细独立复算，与绿区交付值逐位相符。

**裁决 1（抽签复现）：实锤。** numa_cpu8 不绑定态极差 **28.98% >15%**（runs
160.72/129.53/124.60——R5 式逐 run 偏移在 21 原坐标复现），绑定态极差
**9.53% ≤10%**（180.86/165.82/165.13）。结合 R6b 的均值差实锤（+11.97%）
与 gather 相位归因（-19.7%），**R5 的 43~63% 噪声 = CPU gather 段 NUMA
落点问题，归因闭环**。注意 21 的 `numa_balancing=1`（autoNUMA 开着）抽签
仍复现、绑定仍消噪——autoNUMA 救不了 first-touch 落点。

**裁决 2（S2 升级）：强阳性，解冻。** numa_hybrid8 绑定态极差 **0.99% ≤10%**
✓；绑定折叠 **180.019 ≥ anchor8 168.512×1.05=176.938** ✓（实际 ×1.068，
**+6.82%**）。⇒ **S2 升级强阳性，drafts/production_form_hybrid.md
（cf=0.1）解冻，进入集成实施评估**。边界标注：未达 R5 高簇外推的 +26%
上限（~217 GB/s），稳态实得 +6.8%；高簇成因未明（R5 cf0.4 偶发的 216/217
两 run），列为开放问题，不阻塞解冻。

**裁决 3（绑定均值方向）：维持「绑定=修复」。** cpu8 +23.37%、hybrid8 +6.70%
均正向，无反向 >10%。附带观测：cpu8 绑定态 170.6 ≈ anchor 168.5（+1.2%）
——NUMA 修复后纯 cpu 路径在 cards8 copy300 已**追平** kernel（R4 时为
-10%），cpu-delta 路线的容量上限同步上修。

**裁决 4（fallback 首验）：通过。** 21 无 numactl：runner 级
`numactl=missing` + 8 worker `bound=1`（cpulist 逐节点回传）+ JSON
`config.numa_bind=affinity_fallback` 三方一致；`--numa-cycle` 循环映射
（0,1,2,3,0,1,2,3）按设计生效。R6b 的代码修复在目标环境实战成立。

**共享节点标注**：NN=4，rank4-7 与 rank0-3 共享 node0-3；共享形态下绑定
仍 +23%/+6.7%，NN≥8 形态预期不劣于此（按派单口径不混比）。

**哨兵**：anchor8 168.512 vs §R5 171.343 = -1.65%（21 同机，≤15% ✓），
极差 0.37%——anchor 稳态再确认。

**下一步**：(a) 生产形态解冻 ⇒ 蓝区产出 vLLM 集成实施评估（hybrid 嵌入
层间流水，三件套：cf=0.1 + pretouch + NUMA 绑定）；(b) R6d 新旧带宽对账
（用户关切，本轮同推）；(c) R7 队列深度扫描仍在队列（优先级让位于集成
评估）；(d) 节点负载感知 rank→node 映射、R5 高簇成因列为候选开放问题。

---
## §R6b-旧 派单：NUMA 归因裁决（numactl 缺失修复版）（2026-10-15，蓝区）（已交付+判读）

### 与 §R6 的关系

§R6 阻塞于前置核验第 4 条：`which numactl` 不存在（work21 未装 numactl）。
蓝区不修环境、改代码兜底：numactl 缺失时 runner 不再做命令前缀包装，
改经 `SCATTER_C8_NUMA_FALLBACK=<node>` 把节点号传给 worker；worker 在
**DRAM 镜像与 staging 池分配之前** 用 `os.sched_setaffinity` 绑定该节点
cpulist——first-touch 使池页落在该节点，对本实验等效 `--cpunodebind +
--membind`。自检 41→46 项全绿。若 numactl 恰好存在仍走 numactl 原路径；
实际路径逐 rank 打日志并写入结果 JSON（`config.numa_bind`）。本轮目标、
命令矩阵、判读预案与 §R6 完全一致。

### 前置核验

1. 本仓 `git pull --ff-only` 后 `git log --oneline -1` 标题含「R6b: §R6b 派单」。
2. 蓝图仓 `git -C ../nanovllm-scatter_copy log --oneline -1` = `bb062d2`；
   `grep "QUEUE_DEPTH = " csrc/src/kvcache_scatter_copy_c8/op_kernel/vllm_a5_kvcache_scatter_copy_c8.cpp`
   显示 `= 8`；未重编。
3. 四环境变量（ASCEND_CUSTOM_OPP_PATH / NANOVLLM_A5_INSTALL_OPP_PATH /
   NANOVLLM_CUST_OPAPI_LIB / SCATTER_C8_NUMA_NODES）grep 无匹配。
4. `which numactl || echo missing`——存在与否都回传（只决定走哪条绑定
   路径，不再是阻塞项）。

### 执行命令

```bash
cd /home/h2d_test/copy-scheme-bench && git pull --ff-only
cd tests && python3 test_scheme_tools.py && cd ..

numactl -H 2>/dev/null || ls /sys/devices/system/node/ | grep '^node'
lscpu | grep -i numa
cat /proc/sys/kernel/numa_balancing

bash run_scheme_sweep.sh --schemes cpu --cards 8 1 --batch-size 24 \
  --copy-count 300 --window 16 --numa-nodes "<NODES>" --repeat 3 \
  --results-dir results/r6b/numa_cpu 2>&1 | tee run_r6b_cpu.log

bash run_scheme_sweep.sh --schemes hybrid --cpu-fracs 0.1 --hybrid-modes overlap \
  --cards 8 --batch-size 24 --copy-count 300 --window 16 \
  --numa-nodes "<NODES>" --repeat 4 --results-dir results/r6b/numa_hybrid \
  2>&1 | tee run_r6b_hybrid.log

bash run_scheme_sweep.sh --schemes npu --cards 8 --batch-size 24 \
  --copy-count 300 --window 16 --repeat 3 --results-dir results/r6b/anchor8 \
  2>&1 | tee run_r6b_anchor.log

python3 tools/repeat_spread.py results/r6b/numa_cpu results/r6b/numa_hybrid \
  results/r6b/anchor8 results/r5/confirm8 results/r5/anchor8
```

`"<NODES>"` 占位符：`numactl -H` 可得时用其 `node N size:` 的 N 序列；
不可得时用 `ls /sys/devices/system/node/ | grep '^node' | sed 's/^node//'`
的编号序列（空格分隔，**外层引号保留**——argparse 单参数）。节点数必须
≥8（max cards）；若不足 8，把 A/B 组 `--cards 8 1` / `--cards 8` 中的 8
降为节点数，并在交付中注明。共 23 case（12/8/3，蓝区 dry-run 已复核；
--numa-nodes 内建每 case 不绑定+绑定双跑，绑定态命名带 `_numa`）。

### 通过标准

- R6b-G1：自检末两行 `Ran 46 tests` / `OK`。
- R6b-G2：三个 manifest 全 `status=="passed"`；23 个 case JSON 全 passed、
  correctness 全 true；window==16；numa 组每坐标不绑定+绑定成对；
  hybrid 组 `cpu_frac==0.1`。
- R6b-G3：拓扑取证三项原文回传（numactl -H 或 node 编号清单、lscpu NUMA
  行、numa_balancing 值）。
- R6b-G4（跨轮一致性，非门槛）：anchor8 折叠 vs §R5 anchor8（171.343
  GB/s）偏差 ≤15%。
- R6b-G5（绑定路径取证）：numa 组日志中每个绑定 case 有
  `A5_COPY_SCHEME_LAUNCH ... numa_bind=numactl|affinity_fallback` 行；
  走兜底时另有 runner 级 `A5_COPY_SCHEME_NUMA_FALLBACK numactl=missing`
  与每 worker 的 `A5_COPY_SCHEME_NUMA_FALLBACK node=<N> cpus=<清单>
  bound=1`（cpus 清单即该 rank 落点的拓扑取证，逐行回传）。结果 JSON
  `config.numa_bind` 与日志一致。tee 出的 run_r6b_*.log 中
  `grep -E "NUMA|LAUNCH"` 即可取齐。

### 回传格式

同 §R6：交付模板 + 三个目录的 `copy_scheme_timing_summary.md` 全文 +
三个 manifest 全文 + `repeat_spread.py` 全部输出原文 + 拓扑取证三项原文
+ 绑定路径日志行（grep NUMA/LAUNCH 原文）+ 2 个 case JSON 全文——
numa_cpu cards8 不绑定 r1 与 `_numa` 绑定 r1 各一（看 per-die gather
相位对比）。

### 判读预案（派单时写死）

沿用 §R6 六条，原文照录（「绑定态」= numactl 或兜底任一实际路径）：

- 比较口径：同轮同坐标，repeat 折叠带宽/avg_us_mean；极差用
  repeat_spread.py 的 (max-min)/min；p99/p50 > 2 标「波动大」。
- **NUMA 实锤**：numa_cpu cards8 绑定态折叠带宽较不绑定态升 >10%
  （或 avg_us_mean 降 >10%）⇒ NUMA 实锤。
- **落点抽签裁决**：numa_cpu cards8 绑定态 repeat 极差 ≤10% 且不绑定态
  极差 >15% ⇒ 落点抽签实锤；绑定态均值 ≥ 不绑定态均值 ⇒ 绑定=修复，
  纳入正式配置（与 pretouch 并列）。
- **S2 升级判据**：numa_hybrid 绑定态 repeat 极差 ≤10% 且折叠带宽 ≥
  同轮 anchor8 折叠 ×1.05 ⇒ S2 在 NUMA 归置形态下升级**强阳性**，
  生产形态稿（drafts/production_form_hybrid.md，cf=0.1）解冻进入集成
  实施评估。
- **证伪分支**：绑定 vs 不绑定差异 <10% 且两组极差照旧 ⇒ NUMA 归因
  证伪，噪声归因转向（频点/链路竞争，标注新候选），S2 冻结维持；
  R7 回队列深度扫描（drafts/R5_queue_depth.md 改编号）。
- cards1 为对照：单 die 绑定不应有显著差异；若差异 >10% 说明绑定本身
  有开销/收益，单独标注。
- 任何 case correctness 失败 ⇒ 该 case 无效（不影响其他坐标判读）。

---

---

### 交付（§R6b，2026-10-15，绿区）

**执行环境**：按用户指示改在 **141.61.33.13 的 glm_52 容器**（ID 18d46dcfff8e，镜像 vllm-ascend:dev-26.1.0.day20260817-A5-py311-openEuler24.03-lts-aarch64）内执行，不在 21。原因：13 宿主 anaconda python3.11.7+torch 2.7.1 与蓝图仓 `torch_extension/vllm_dsa_a5/_C.cpython-311-aarch64-linux-gnu.so`（21 用 torch 2.10 编译）ABI 不兼容（import 报 `undefined symbol: c10::TensorImpl::decref_pyobject()`），sweep worker 加载即崩；glm_52 容器 python 3.11.10 + torch 2.10.0+cpu + torch_npu 2.10.0.post4 与 .so 编译版本匹配。容器挂载全部 8×davinci（davinci0-7）+ /home→/home（13 解包的两仓容器内可见）；容器内 CANN /usr/local/Ascend/ascend-toolkit/latest 就绪；容器内 numactl 存在（/usr/bin/numactl）→ 走 **numactl 原路径**。13 无 GitHub 出网，两仓经 21 打包 scp 中转解包到 /home/h2d_test/。时间 2026-10-15T06:33Z–06:45Z（容器内 UTC）。
**前置核验**：1) 本仓 `git log --oneline -1` = `8638f8d` 标题含「R6b: §R6b 派单」 ✓；2) 蓝图仓 `git -C ../nanovllm-scatter_copy log --oneline -1` = `bb062d2` ✓；`grep "QUEUE_DEPTH = "`（csrc/src/kvcache_scatter_copy_c8/op_kernel/vllm_a5_kvcache_scatter_copy_c8.cpp）= `= 8` ✓；未重编 ✓；3) 四环境变量（ASCEND_CUSTOM_OPP_PATH / NANOVLLM_A5_INSTALL_OPP_PATH / NANOVLLM_CUST_OPAPI_LIB / SCATTER_C8_NUMA_NODES）grep 无匹配 ✓；4) `which numactl` = /usr/bin/numactl（存在 → numactl 原路径）✓。
**执行**：`<NODES>` = `"0 1 2 3"`（numactl -H 得 4 节点，<8 → **A/B 组 cards 8→4**、anchor8 保持 cards8，case 数 12/8/3 不变）。三组 sweep 容器内串行（run_r6b.sh 包装：tee 日志 + STAGE_*_RC + DONE 标记，命令本体未改）。三组 RC=0；共 23 case（12/8/3，iters=1000 默认）。
**通过标准命中**：
- R6b-G1 ✓：自检末两行 `Ran 46 tests` / `OK`（容器内，13 宿主 G1 同）。
- R6b-G2 ✓：三个 manifest 全 `status=="passed"`；23 个 case JSON 全 passed、correctness 全 true（断言在 `per_device[0].correctness` 的 data_exact/guard_unchanged，顶层 `correctness={}` 为结构空字段）；window==16 全 ✓；hybrid 组 `cpu_frac==0.1` 全 ✓、cpu/npu 组 cpu_frac==0.5；numa 组每坐标不绑定+绑定成对（r6b_verify2.py 重判：cases=23, bad=0）。
- R6b-G3 ✓（原文见下）：numactl -H = 4 nodes (0-3)；lscpu NUMA = 4；numa_balancing = 0。
- R6b-G4 ✓（非门槛）：anchor8 折叠 167.571 GB/s vs §R5 anchor8 171.343 GB/s，偏差 -2.20% ≤ 15%。
- R6b-G5 ✓（原文见下）：numa 组日志每个绑定 case 有 `A5_COPY_SCHEME_LAUNCH ... numa_bind=numactl`（rank i → node i 一一对应）；结果 JSON `config.numa_bind` 与日志一致（numactl/none 成对）。

**timing_summary.md [numa_cpu] 全文**（results/r6b/numa_cpu/）：

```
| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 300 | 189.664 | 189.664 | 24.910 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 300 | 212.545 | 230.038 | 89.822 |
```

**timing_summary.md [numa_hybrid] 全文**（results/r6b/numa_hybrid/）：

```
| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| hybrid | 0 | 0.1 | overlap | 4 | 24 | 300 | 211.651 | 216.359 | 89.318 |
```

**timing_summary.md [anchor8] 全文**（results/r6b/anchor8/）：

```
| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| npu | 0 | 0.5 | overlap | 8 | 24 | 300 | 226.835 | 239.988 | 167.571 |
```

**manifest [numa_cpu] 全文**（results/r6b/numa_cpu/copy_scheme_run_manifest.json）：

```json
{
  "schema_version": 2,
  "status": "passed",
  "dtype": "c8",
  "timestamp_utc": "2026-10-15T06:40:50.794190+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "queue_depth": "default",
  "case_files": [
    "cpu_cards4_bs24_copy300_rf0p0_r1.json",
    "cpu_cards4_bs24_copy300_rf0p0_r2.json",
    "cpu_cards4_bs24_copy300_rf0p0_r3.json",
    "cpu_cards1_bs24_copy300_rf0p0_r1.json",
    "cpu_cards1_bs24_copy300_rf0p0_r2.json",
    "cpu_cards1_bs24_copy300_rf0p0_r3.json",
    "cpu_cards4_bs24_copy300_rf0p0_numa_r1.json",
    "cpu_cards4_bs24_copy300_rf0p0_numa_r2.json",
    "cpu_cards4_bs24_copy300_rf0p0_numa_r3.json",
    "cpu_cards1_bs24_copy300_rf0p0_numa_r1.json",
    "cpu_cards1_bs24_copy300_rf0p0_numa_r2.json",
    "cpu_cards1_bs24_copy300_rf0p0_numa_r3.json"
  ]
}
```

**manifest [numa_hybrid] 全文**（results/r6b/numa_hybrid/copy_scheme_run_manifest.json）：

```json
{
  "schema_version": 2,
  "status": "passed",
  "dtype": "c8",
  "timestamp_utc": "2026-10-15T06:43:11.133369+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "queue_depth": "default",
  "case_files": [
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p1_overlap_r1.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p1_overlap_r2.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p1_overlap_r3.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p1_overlap_r4.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p1_overlap_numa_r1.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p1_overlap_numa_r2.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p1_overlap_numa_r3.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p1_overlap_numa_r4.json"
  ]
}
```

**manifest [anchor8] 全文**（results/r6b/anchor8/copy_scheme_run_manifest.json）：

```json
{
  "schema_version": 2,
  "status": "passed",
  "dtype": "c8",
  "timestamp_utc": "2026-10-15T06:44:49.643456+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "queue_depth": "default",
  "case_files": [
    "npu_cards8_bs24_copy300_rf0p0_r1.json",
    "npu_cards8_bs24_copy300_rf0p0_r2.json",
    "npu_cards8_bs24_copy300_rf0p0_r3.json"
  ]
}
```

**repeat_spread.py 全部输出原文**（对 r6b 三组 + r5 对照 confirm8/anchor8 全量输入，绑定/不绑定因同目录双跑被混聚 n=6/8，拆分见下）：

```

# results/r6b/numa_cpu
coordinate                                    n      mean      std  spread%  runs
cpu/0.0/0.5/overlap/1/24/300/300              6    24.910    0.469    4.12%  24.53 24.43 24.50 25.34 25.43 25.23
cpu/0.0/0.5/overlap/4/24/300/300              6    89.822    6.560   19.07%  89.99 96.92 97.78 82.12 88.70 83.43  <-- UNSTABLE

# results/r6b/numa_hybrid
coordinate                                    n      mean      std  spread%  runs
hybrid/0.0/0.1/overlap/4/24/300/300           8    89.318    0.722    2.44%  88.52 90.28 89.74 89.61 89.64 89.72 88.13 88.91

# results/r6b/anchor8
coordinate                                    n      mean      std  spread%  runs
npu/0.0/0.5/overlap/8/24/300/300              3   167.571    2.840    3.30%  166.67 170.75 165.29

# results/r5/confirm8
coordinate                                    n      mean      std  spread%  runs
hybrid/0.0/0.1/overlap/8/24/300/300           6   167.849   21.593   43.05%  180.82 126.41 180.16 178.20 161.54 179.97  <-- UNSTABLE
hybrid/0.0/0.15/overlap/8/24/300/300          6   161.415   22.146   47.81%  162.05 152.45 160.43 183.76 184.78 125.01  <-- UNSTABLE
hybrid/0.0/0.3/overlap/8/24/300/300           6   164.463   30.908   63.24%  187.23 155.81 191.13 141.65 192.83 118.13  <-- UNSTABLE
hybrid/0.0/0.4/overlap/8/24/300/300           6   178.175   35.383   58.83%  216.04 182.23 136.79 217.27 178.16 138.56  <-- UNSTABLE

# results/r5/anchor8
coordinate                                    n      mean      std  spread%  runs
npu/0.0/0.5/overlap/8/24/300/300              6   171.343    2.150    3.96%  171.78 170.64 174.48 171.76 171.57 167.82

```

**拓扑取证三项原文**（容器内，R6b-G3）：

```
=== numactl -H ===
available: 4 nodes (0-3)
node 0 cpus: 0-95
node 0 size: 381448 MB
node 0 free: 22743 MB
node 1 cpus: 96-191
node 1 size: 387058 MB
node 1 free: 24818 MB
node 2 cpus: 192-287
node 2 size: 387000 MB
node 2 free: 36952 MB
node 3 cpus: 288-383
node 3 size: 386014 MB
node 3 free: 35392 MB
node distances:
node   0   1   2   3
  0:  10  15  20  20
  1:  15  10  20  20
  2:  20  20  10  15
  3:  20  20  15  10

=== lscpu | grep -i numa ===
NUMA node(s):                         4
NUMA node0 CPU(s):                    0-95
NUMA node1 CPU(s):                    96-191
NUMA node2 CPU(s):                    192-287
NUMA node3 CPU(s):                    288-383

=== cat /proc/sys/kernel/numa_balancing ===
0

=== ls /sys/devices/system/node/ | grep '^node' ===
node0
node1
node2
node3
```
（cpus 清单原文为逐 CPU 空格分隔，此处折叠为区间；`<NODES>`="0 1 2 3"）

**绑定路径日志行（R6b-G5，numactl 原路径，逐行原文）**：

```
绑定 case（cpu_cards4_bs24_copy300_rf0p0_numa_r1.log 的 LAUNCH 行，rank→node 一一对应）：
A5_COPY_SCHEME_LAUNCH rank=0 device=npu:0 scheme=cpu seed=7 numa_node=0 numa_bind=numactl
A5_COPY_SCHEME_LAUNCH rank=1 device=npu:1 scheme=cpu seed=7 numa_node=1 numa_bind=numactl
A5_COPY_SCHEME_LAUNCH rank=2 device=npu:2 scheme=cpu seed=7 numa_node=2 numa_bind=numactl
A5_COPY_SCHEME_LAUNCH rank=3 device=npu:3 scheme=cpu seed=7 numa_node=3 numa_bind=numactl

不绑定 case（cpu_cards4_bs24_copy300_rf0p0_r1.log 的 LAUNCH 行）：
A5_COPY_SCHEME_LAUNCH rank=0 device=npu:0 scheme=cpu seed=7 numa_node=unbound numa_bind=unbound
A5_COPY_SCHEME_LAUNCH rank=1 device=npu:1 scheme=cpu seed=7 numa_node=unbound numa_bind=unbound
A5_COPY_SCHEME_LAUNCH rank=2 device=npu:2 scheme=cpu seed=7 numa_node=unbound numa_bind=unbound
A5_COPY_SCHEME_LAUNCH rank=3 device=npu:3 scheme=cpu seed=7 numa_node=unbound numa_bind=unbound

CONFIG 行（绑定 case，staging_pinned=True / window=16 / queue_depth=8）：
A5_COPY_SCHEME_CONFIG device=npu:0 device_name='Ascend950DT_9572' scheme=cpu run_frac=0.0 cpu_frac=0.5 hybrid_mode=overlap cpu_threads=8 pretouch=False staging_pinned=True window=16 batch=24 copy_range=[300,300] copied_tokens=7200 cpu_tokens=0 queue_depth=8
```
结果 JSON `config.numa_bind` 与日志一致：绑定 case = `"numactl"` 且 `config.numa_nodes="0,1,2,3"`，不绑定 case = `"none"` 且 `numa_nodes=""`；numa_cpu 6 绑定/6 不绑定、numa_hybrid 4 绑定/4 不绑定、anchor8 全 none（r6b_verify2.py 已核）。

**2 个 case JSON 全文**（numa_cpu cards4 不绑定 r1 与 `_numa` 绑定 r1；cards8 因 <NODES>=4 降为 cards4，per-die gather 相位对比见下）：


###FILE:numa_cpu/cards4 不绑定 r1###
```json
{
  "schema_version": 2,
  "test": "a5_kvcache_copy_scheme_multiprocess",
  "status": "passed",
  "timestamp_utc": "2026-10-15T06:41:14.653253+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 4,
  "devices": [
    0,
    1,
    2,
    3
  ],
  "same_seed": true,
  "config": {
    "dtype": "c8",
    "row_bytes": 656,
    "batch_size": 24,
    "source_len": 65536,
    "hbm_slots": 8192,
    "copy_min": 300,
    "copy_max": 300,
    "copy_cap": 16384,
    "warmup": 10,
    "iters": 1000,
    "seed": 7,
    "allow_non_a5": false,
    "scheme": "cpu",
    "run_frac": 0.0,
    "cpu_frac": 0.5,
    "hybrid_mode": "overlap",
    "cpu_threads": 8,
    "pretouch": false,
    "window": 16,
    "numa_nodes": "",
    "numa_bind": "none"
  },
  "summary": {
    "avg_us_mean": 230.5397375000002,
    "avg_us_max": 241.03022999999934,
    "avg_bandwidth": 82.12107261900589,
    "total_payload_bytes_per_iteration": 18892800,
    "copied_tokens_sum_per_iteration": 28800,
    "all_correct": true
  },
  "per_device": [
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-15T06:41:10.200039+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:0",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "cpu",
        "run_frac": 0.0,
        "cpu_frac": 0.5,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 0,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 227.05463000000034,
        "avg_us_max": 227.05463000000034,
        "avg_bandwidth": 20.802042222173547
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 227.05463000000034,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 227.0546300000007,
          "p50": 225.1625,
          "p90": 238.090625,
          "p99": 302.07875,
          "min": 206.99375,
          "max": 302.07875,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "cpu_gather_us": 105.85924000000004,
          "device_wall_us": 121.19539000000002,
          "device_event_us": 111.39786010980606,
          "device_overhead_us": 9.797529890193953
        }
      },
      "rank": 0,
      "logical_device_index": 0
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-15T06:41:10.188049+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:1",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "cpu",
        "run_frac": 0.0,
        "cpu_frac": 0.5,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 0,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 215.07405000000142,
        "avg_us_max": 215.07405000000142,
        "avg_bandwidth": 21.960808382043158
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 215.07405000000142,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 215.07405000000028,
          "p50": 213.871875,
          "p90": 228.375,
          "p99": 296.8725,
          "min": 194.75,
          "max": 296.8725,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "cpu_gather_us": 93.72346,
          "device_wall_us": 121.35059000000001,
          "device_event_us": 111.34391701221466,
          "device_overhead_us": 10.00667298778535
        }
      },
      "rank": 1,
      "logical_device_index": 1
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-15T06:41:10.224652+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:2",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "cpu",
        "run_frac": 0.0,
        "cpu_frac": 0.5,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 0,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 241.03022999999934,
        "avg_us_max": 241.03022999999934,
        "avg_bandwidth": 19.595882226059416
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 241.03022999999934,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 241.03023000000005,
          "p50": 238.3275,
          "p90": 264.39375,
          "p99": 344.45125,
          "min": 202.065,
          "max": 344.45125,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "cpu_gather_us": 121.88471000000003,
          "device_wall_us": 119.14551999999998,
          "device_event_us": 109.24913811683655,
          "device_overhead_us": 9.896381883163427
        }
      },
      "rank": 2,
      "logical_device_index": 2
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-15T06:41:10.223000+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:3",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "cpu",
        "run_frac": 0.0,
        "cpu_frac": 0.5,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 0,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 239.0000399999997,
        "avg_us_max": 239.0000399999997,
        "avg_bandwidth": 19.76233978872977
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 239.0000399999997,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 239.00003999999885,
          "p50": 237.24125,
          "p90": 265.144375,
          "p99": 344.93125,
          "min": 201.48125,
          "max": 344.93125,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "cpu_gather_us": 118.89105000000004,
          "device_wall_us": 120.10899000000002,
          "device_event_us": 110.63837087154388,
          "device_overhead_us": 9.470619128456136
        }
      },
      "rank": 3,
      "logical_device_index": 3
    }
  ]
}

```

###FILE:numa_cpu/cards4 绑定 r1 (_numa)###
```json
{
  "schema_version": 2,
  "test": "a5_kvcache_copy_scheme_multiprocess",
  "status": "passed",
  "timestamp_utc": "2026-10-15T06:42:16.126258+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 4,
  "devices": [
    0,
    1,
    2,
    3
  ],
  "same_seed": true,
  "config": {
    "dtype": "c8",
    "row_bytes": 656,
    "batch_size": 24,
    "source_len": 65536,
    "hbm_slots": 8192,
    "copy_min": 300,
    "copy_max": 300,
    "copy_cap": 16384,
    "warmup": 10,
    "iters": 1000,
    "seed": 7,
    "allow_non_a5": false,
    "scheme": "cpu",
    "run_frac": 0.0,
    "cpu_frac": 0.5,
    "hybrid_mode": "overlap",
    "cpu_threads": 8,
    "pretouch": false,
    "window": 16,
    "numa_nodes": "0,1,2,3",
    "numa_bind": "numactl"
  },
  "summary": {
    "avg_us_mean": 215.99402249999955,
    "avg_us_max": 280.44294999999937,
    "avg_bandwidth": 89.98850213402038,
    "total_payload_bytes_per_iteration": 18892800,
    "copied_tokens_sum_per_iteration": 28800,
    "all_correct": true
  },
  "per_device": [
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-15T06:42:12.380076+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:0",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "cpu",
        "run_frac": 0.0,
        "cpu_frac": 0.5,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 0,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 280.44294999999937,
        "avg_us_max": 280.44294999999937,
        "avg_bandwidth": 16.841928099814993
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 280.44294999999937,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 280.4429499999986,
          "p50": 278.92625,
          "p90": 305.295625,
          "p99": 330.495625,
          "min": 250.369375,
          "max": 330.495625,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "cpu_gather_us": 141.68710000000002,
          "device_wall_us": 138.75585000000004,
          "device_event_us": 128.32055795192719,
          "device_overhead_us": 10.43529204807285
        }
      },
      "rank": 0,
      "logical_device_index": 0
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-15T06:42:12.308478+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:1",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "cpu",
        "run_frac": 0.0,
        "cpu_frac": 0.5,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 0,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 212.50845999999945,
        "avg_us_max": 212.50845999999945,
        "avg_bandwidth": 22.225938675570905
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 212.50845999999945,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 212.50846000000067,
          "p50": 205.52875,
          "p90": 245.8875,
          "p99": 264.678125,
          "min": 184.7975,
          "max": 264.678125,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "cpu_gather_us": 72.25660999999998,
          "device_wall_us": 140.25185,
          "device_event_us": 129.8945251107216,
          "device_overhead_us": 10.357324889278388
        }
      },
      "rank": 1,
      "logical_device_index": 1
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-15T06:42:12.281395+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:2",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "cpu",
        "run_frac": 0.0,
        "cpu_frac": 0.5,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 0,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 185.66286999999912,
        "avg_us_max": 185.66286999999912,
        "avg_bandwidth": 25.439658451902755
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 185.66286999999912,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 185.66286999999974,
          "p50": 184.340625,
          "p90": 189.03125,
          "p99": 246.46625,
          "min": 180.389375,
          "max": 246.46625,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "cpu_gather_us": 70.50667999999997,
          "device_wall_us": 115.15618999999998,
          "device_event_us": 106.42206287384033,
          "device_overhead_us": 8.734127126159656
        }
      },
      "rank": 2,
      "logical_device_index": 2
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-15T06:42:12.281610+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:3",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "cpu",
        "run_frac": 0.0,
        "cpu_frac": 0.5,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 0,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 185.36181000000025,
        "avg_us_max": 185.36181000000025,
        "avg_bandwidth": 25.480976906731723
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 185.36181000000025,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 185.36180999999883,
          "p50": 184.185,
          "p90": 188.585,
          "p99": 247.134375,
          "min": 177.95125,
          "max": 247.134375,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "cpu_gather_us": 69.33599000000002,
          "device_wall_us": 116.02582000000002,
          "device_event_us": 106.40901052951813,
          "device_overhead_us": 9.616809470481893
        }
      },
      "rank": 3,
      "logical_device_index": 3
    }
  ]
}

```

**判读输入（绑定 vs 不绑定，口径=同轮同坐标，折叠值取 case JSON `summary.avg_bandwidth`/`summary.avg_us_mean`，绑定=文件名带 `_numa`，极差=(max-min)/min）**：
```
numa_cpu cards1 (repeat3):
  绑定    mean=24.488  spread=0.43%  avg_us_mean=192.882  runs=24.532 24.427 24.503
  不绑定  mean=25.333  spread=0.82%  avg_us_mean=186.446  runs=25.340 25.433 25.226
  绑定 vs 不绑定 = -3.34%（单 die 对照）
numa_cpu cards4 (repeat3):
  绑定    mean=94.896  spread=8.66%  avg_us_mean=201.571  runs=89.989 96.918 97.780
  不绑定  mean=84.749  spread=8.01%  avg_us_mean=223.518  runs=82.121 88.700 83.427
  绑定 vs 不绑定 = +11.97%（avg_us_mean 降 9.82%）
numa_hybrid cards4 (repeat4):
  绑定    mean=89.538  spread=1.98%  avg_us_mean=211.219  runs=88.524 90.279 89.738 89.611
  不绑定  mean=89.098  spread=1.80%  avg_us_mean=212.083  runs=89.636 89.716 88.133 88.906
  绑定 vs 不绑定 = +0.49%
anchor8 npu cards8 (repeat3):
  npu     mean=167.571 spread=3.30%  avg_us_mean=226.835  runs=166.669 170.752 165.292
```

**观察（只事实，判读留蓝区）**：
- 绑定态 per-die gather 相位（cards4 绑定 r1 日志逐 die avg_us：185.663/185.362/212.508/280.443 µs，die 随 rank/node 索引增大而变慢；不绑定 r1：215.074/227.055/239.000/241.030 µs 较均匀）——折叠带宽 bind 89.99 > unbind 82.12：快 die 25.44/25.48 vs 21.96/20.80，慢 die 16.84 vs 19.60。
- repeat_spread 对 r6b/numa_cpu 的 cards1 n=6 spread 4.12%、cards4 n=6 spread 19.07%（标 UNSTABLE）是绑定+不绑定混聚结果；按坐标拆分后极差见上。
- 跨轮：anchor8 167.571 vs §R5 anchor8 171.343（-2.20%）；但 §R5 在 21、本组在 13/glm_52 容器，跨机绝对值不可比（测量口径注明），G4 仅作参考。
- 本组 23 case 无 correctness 失败；p99/p50 未逐 case 汇总（正确性门槛先于性能，均已过）。

**异常/备注**：
- 执行环境变更：13 宿主 ABI 不兼容（torch 2.7.1 vs .so 编译 torch 2.10）→ 改在 glm_52 容器（torch 2.10.0 匹配）执行；13 无 GitHub 出网，两仓经 21 打包 scp 中转解包。
- 降 cards：`<NODES>`=4 节点 <8 → A/B 组 cards 8→4（numa_cpu `--cards 4 1`、numa_hybrid `--cards 4`）、anchor8 保持 cards8；**S2 升级判据坐标不匹配（numa_hybrid cards4 vs anchor8 cards8）**，由蓝区处理。
- correctness 字段：case JSON 顶层 `correctness={}`（结构空字段），断言在 `per_device[0].correctness`（data_exact/guard_unchanged 全 true）。
- 结果文件在 13 的 results/r6b/（.gitignore 不入库；13 无 git 远端，21 为交付仓）；日志 run_r6b_cpu.log / run_r6b_hybrid.log / run_r6b_anchor.log。
- 带宽口径：`effective_bandwidth = payload_bytes/(avg_us×1000)` 每 die、多 die=各 die 速率之和，`payload_bytes=copied_tokens×656`（cards4 copy300 = 3600 token/die）；与 §R5 交付口径一致（r6b case JSON `summary.avg_bandwidth` 已对账）。

### 判读（§R6b，2026-10-15，蓝区）

**裁决 1（NUMA 实锤）：命中**。按派单写死的降卡规则坐标落在 cards4：numa_cpu 绑定态折叠 94.896 vs 不绑定 84.749 = **+11.97% > 10% 阈值**。per-die gather 相位（r1）：绑定 141.69/72.26/70.51/69.34µs vs 不绑定 105.86/93.72/121.88/118.89µs（均值 88.45 vs 110.09，**-19.7%**）——增益确实落在 CPU gather 段，机制归因闭环。cards1 对照 -3.34%（|差|<10%）⇒ 绑定本身无显著开销/收益 ✓。

**裁决 2（落点抽签）：此环境不成立，呈稳定均值差形态**。混聚拆分：cpu cards4 绑定 r1-3 = 89.99/96.92/97.78（极差 8.66% ≤10% ✓），不绑定 = 82.12/88.70/83.43（极差 **8.01%，未达 >15%**）；hybrid cards4 绑定/不绑定拆分极差 1.99%/1.80%。13 机 cards4 的 NUMA 效应是**稳定 -11% 均值惩罚**而非 R5 式 run 级抽签（43~63%）。机制推测：4 节点 × 96 核只跑 4 worker，调度器天然撒开 + numa_balancing=0 ⇒ run 间落点方差小；但 first-touch 池页节点一旦固定、worker 的 8 个 torch 线程跨节点访存 ⇒ 稳定惩罚。R5（21 机 cards8）的强抽签形态留 R6c 在原坐标裁决。

**裁决 3（S2 升级）：本轮不可判**（hybrid 降 cards4 vs anchor8 cards8 坐标不齐，绿区已声明）。辅助事实：hybrid cards4 绑定均值 +0.49%、极差 1.99%——cf0.1 只有 10% 流量过 CPU gather，NUMA 收益被稀释到噪声下，方向自洽；稳定性 ✓。S2 须 cards8 同坐标补测 ⇒ R6c。

**裁决 4（证伪分支）**：不触发（裁决 1 命中）。

**门槛与哨兵**：R6b-G1..G5 全过（自检 46 项、23 case 全 passed/correctness 全 true、拓扑 4 节点 × 96 核 distances 15/20、numa_balancing=0、numactl 原路径 rank→node 一一对应、JSON `config.numa_bind` 与日志一致）。anchor8 167.571 vs §R5 171.343 = -2.20%（跨机仅参考），极差 3.30% 复现 anchor 稳定性。

**附带发现**：绑定态 die 间异质——r1 的 rank0/node0 gather 141.7µs 显著慢于其余三 die（69~72µs）；node0 free 内存最少（22.7GB vs 35~37GB），疑节点驻留负载。绑定把 run 级抽签换成了固定 die 级异质；「按节点空闲/负载选 rank→node 映射」列为优化候选（非门槛）。

**结论**：NUMA 实锤 + 绑定=修复（cards4、numactl 路径，均值 +12%），绑定纳入 cpu/hybrid 正式配置候选（与 pretouch 并列）。S2 未决 ⇒ R6c 回 21（R5 噪声原地）cards8 原坐标复测，首验 sched_setaffinity 兜底路径。队列深度 R7 顺延。

---

## §R6-旧 派单：NUMA 归因实锤 + 绑定修复验证（2026-10-15，蓝区）（阻塞：numactl 缺失，由 §R6b 取代）

### 目标

R5 判读把 hybrid 噪声机制收窄到 CPU gather 段的 **NUMA 落点抽签**
（anchor8 极差 3.96% vs hybrid 43~63%；R4 die 双峰 1.74x 三方互洽，
drafts/die_bimodality_r4.md）。本轮直接裁决：(a) 拓扑取证（numactl -H）；
(b) cpu/hybrid 的 NUMA 绑定 vs 不绑定同轮对比——若绑定消噪且提速，
NUMA 归因实锤 + 修复方案落袋；若绑定无效应，NUMA 归因证伪。

### 前置核验

1. 本仓 `git pull --ff-only` 后 `git log --oneline -1` 标题含「R6: §R6 派单」。
2. 蓝图仓 `git -C ../nanovllm-scatter_copy log --oneline -1` = `bb062d2`；
   `grep "QUEUE_DEPTH = " csrc/src/kvcache_scatter_copy_c8/op_kernel/vllm_a5_kvcache_scatter_copy_c8.cpp`
   显示 `= 8`；未重编。
3. 四环境变量（ASCEND_CUSTOM_OPP_PATH / NANOVLLM_A5_INSTALL_OPP_PATH /
   NANOVLLM_CUST_OPAPI_LIB / SCATTER_C8_NUMA_NODES）grep 无匹配。
4. `which numactl` 存在。

### 执行命令

```bash
cd /home/h2d_test/copy-scheme-bench && git pull --ff-only
cd tests && python3 test_scheme_tools.py && cd ..

numactl -H
lscpu | grep -i numa

bash run_scheme_sweep.sh --schemes cpu --cards 8 1 --batch-size 24 \
  --copy-count 300 --window 16 --numa-nodes "<NODES>" --repeat 3 \
  --results-dir results/r6/numa_cpu

bash run_scheme_sweep.sh --schemes hybrid --cpu-fracs 0.1 --hybrid-modes overlap \
  --cards 8 --batch-size 24 --copy-count 300 --window 16 \
  --numa-nodes "<NODES>" --repeat 4 --results-dir results/r6/numa_hybrid

bash run_scheme_sweep.sh --schemes npu --cards 8 --batch-size 24 \
  --copy-count 300 --window 16 --repeat 3 --results-dir results/r6/anchor8

python3 tools/repeat_spread.py results/r6/numa_cpu results/r6/numa_hybrid \
  results/r6/anchor8 results/r5/confirm8 results/r5/anchor8
```

`"<NODES>"` 占位符：用 `numactl -H` 输出的节点 id 清单替换（`node N size:`
行的 N 序列，空格分隔，**外层引号保留**——argparse 单参数）。节点数必须
≥8（max cards）；若不足 8，把 B/C 组 `--cards 8 1` / `--cards 8` 中的 8 降为
节点数，并在交付中注明。共 23 case（12/8/3，蓝区 dry-run 已核验；
--numa-nodes 使每个 case 自动跑不绑定/绑定两遍，绑定态命名带 `_numa`）。

### 通过标准

- R6-G1：自检末两行 `Ran 41 tests` / `OK`。
- R6-G2：三个 manifest 全 `status=="passed"`；23 个 case JSON 全 passed、
  correctness 全 true；window==16；numa 组每坐标不绑定+绑定成对；
  hybrid 组 `cpu_frac==0.1`。
- R6-G3：`numactl -H` 与 `lscpu | grep -i numa` 输出原文回传。
- R6-G4（跨轮一致性，非门槛）：anchor8 折叠 vs §R5 anchor8（171.343
  GB/s）偏差 ≤15%。

### 回传格式

同 §R5：交付模板 + 三个目录的 `copy_scheme_timing_summary.md` 全文 +
三个 manifest 全文 + `repeat_spread.py` 全部输出原文 + numactl/lscpu
原文 + 2 个 case JSON 全文——numa_cpu cards8 不绑定 r1 与 `_numa` 绑定
r1 各一（看 per-device gather 相位对比）。

### 判读预案（派单时写死）

- 比较口径：同轮同坐标，repeat 折叠带宽/avg_us_mean；极差用
  repeat_spread.py 的 (max-min)/min；p99/p50 > 2 标「波动大」。
- **NUMA 实锤**：numa_cpu cards8 绑定态折叠带宽较不绑定态升 >10%
  （或 avg_us_mean 降 >10%）⇒ NUMA 实锤。
- **落点抽签裁决**：numa_cpu cards8 绑定态 repeat 极差 ≤10% 且不绑定态
  极差 >15% ⇒ 落点抽签实锤；绑定态均值 ≥ 不绑定态均值 ⇒ 绑定=修复，
  纳入正式配置（与 pretouch 并列）。
- **S2 升级判据**：numa_hybrid 绑定态 repeat 极差 ≤10% 且折叠带宽 ≥
  同轮 anchor8 折叠 ×1.05 ⇒ S2 在 NUMA 归置形态下升级**强阳性**，
  生产形态稿（drafts/production_form_hybrid.md，cf=0.1）解冻进入集成
  实施评估。
- **证伪分支**：绑定 vs 不绑定差异 <10% 且两组极差照旧 ⇒ NUMA 归因
  证伪，噪声归因转向（频点/链路竞争，标注新候选），S2 冻结维持；
  R7 回队列深度扫描（drafts/R5_queue_depth.md 改编号）。
- cards1 为对照：单 die 绑定不应有显著差异；若差异 >10% 说明绑定本身
  有开销/收益，单独标注。
- 任何 case correctness 失败 ⇒ 该 case 无效（不影响其他坐标判读）。

---

## §R5-旧 派单：S2 弱阳性同轮高重复确认跑（2026-10-15，蓝区）

### 目标

R4 判读 S2 **弱阳性**：hybrid cf0.4/cf0.1 cards8 copy300 = 178.90/178.41
GB/s ≥ 同轮 npu anchor 171.26（+4.5%/+4.2%），但 frac 曲线非单调
（cf0.25 凹陷 157.39，相邻档摆动 ±10%）——**边际与 run 级噪声同量级**。
本轮用更高重复数（repeat 6）同轮复测最优区 + 加密曲线（cf0.15/0.3），
判定 S2 是真阳性还是噪声伪影；cards4 次要确认。

### 前置核验

1. 本仓 `git pull --ff-only` 后 `git log --oneline -1` 标题含「R5: §R5 派单」。
2. 蓝图仓 `git -C ../nanovllm-scatter_copy log --oneline -1` = `bb062d2`；
   `grep "QUEUE_DEPTH = " csrc/src/kvcache_scatter_copy_c8/op_kernel/vllm_a5_kvcache_scatter_copy_c8.cpp`
   显示 `= 8`；未重编。
3. 四环境变量（ASCEND_CUSTOM_OPP_PATH / NANOVLLM_A5_INSTALL_OPP_PATH /
   NANOVLLM_CUST_OPAPI_LIB / SCATTER_C8_NUMA_NODES）grep 无匹配。

### 执行命令

```bash
cd /home/h2d_test/copy-scheme-bench && git pull --ff-only
cd tests && python3 test_scheme_tools.py && cd ..

bash run_scheme_sweep.sh --schemes hybrid --cpu-fracs 0.1 0.15 0.3 0.4 --hybrid-modes overlap --cards 8 --batch-size 24 --copy-count 300 --window 16 --repeat 6 --results-dir results/r5/confirm8

bash run_scheme_sweep.sh --schemes hybrid --cpu-fracs 0.1 0.25 --hybrid-modes overlap --cards 4 --batch-size 24 --copy-count 300 --window 16 --repeat 4 --results-dir results/r5/confirm4

bash run_scheme_sweep.sh --schemes npu --cards 8 --batch-size 24 --copy-count 300 --window 16 --repeat 6 --results-dir results/r5/anchor8

bash run_scheme_sweep.sh --schemes npu --cards 4 --batch-size 24 --copy-count 300 --window 16 --repeat 4 --results-dir results/r5/anchor4
```

共 42 case（24/8/6/4，蓝区 dry-run 已核验；iters=1000 默认与 R4 一致，
不改第二变量）。

### 通过标准

- R5-G1：自检末两行 `Ran 40 tests` / `OK`。
- R5-G2：四个 manifest 全 `status=="passed"`；42 个 case JSON 全 passed、
  correctness 全 true；hybrid 组 `config.window==16` 且
  `hybrid_mode=="overlap"`、`cpu_frac` 与组一致。
- R5-G3：每个 case JSON 含 `performance.latency_us.p50/p99`（迭代级分位数）。
- R5-G4（跨轮一致性，非门槛）：anchor8 与 §R4 E 组同坐标（171.264 GB/s）
  偏差 ≤15%；超出原样回传注明。

### 回传格式

同 §R4：交付模板 + 四个目录的 `copy_scheme_timing_summary.md` 全文 +
四个 manifest 全文 + 3 个 case JSON 全文——confirm8 cf0.1 的 r1 与 r6
各一（看 repeat 内 phases/分位数稳定性）+ anchor8 r1 一个。

### 判读预案（派单时写死）

- 比较口径：同轮同坐标，avg_us_mean/带宽用 repeat 折叠值；`p99/p50 > 2`
  标注「波动大，证据弱」；同 case 6 次 repeat 的带宽极差 (max-min)/min
  >10% 标注「不稳」。
- **S2 确认（强阳性）**：confirm8 最优 cf 的折叠带宽 ≥ anchor8 折叠带宽
  ×1.05，且该 cf 的 repeat 带宽极差 ≤5% ⇒ S2 强阳性，R6 进入生产形态
  集成评估（vLLM 层间流水嵌入，蓝区设计稿定稿）+ pretouch 纳入默认配置。
- **弱阳性维持**：最优 cf ≥ anchor8 但不满足上一条 ⇒ 收益存疑，生产形态
  设计稿照写但全程标注「收益存疑，未确认」。
- **翻回阴性**：最优 cf < anchor8 ⇒ R4 阳性为噪声伪影，S2 不成立，R6 =
  队列深度扫描（drafts/R5_queue_depth.md 改编号 R6 派出）。
- cards4：confirm4 最优 cf vs anchor4 同口径比较（参考项；cards4 档有
  连续两轮漂移史，证据弱，单独标注）。
- 曲线形态：cf ∈ {0.1, 0.15, 0.3, 0.4} 若相邻档仍 >10% 非单调摆动 ⇒
  噪声主导、cf* 不可分辨，生产形态稿按 cf=0.1（R4 延迟口径最稳档）写死。

---

---

### 交付（§R5，2026-10-15，绿区）

**执行环境**：机器 work21（141.61.33.21）openEuler aarch64；8× Ascend950DT_9572（可见设备 0-7）；宿主 root；CANN 9.2.0（/usr/local/Ascend/ascend-toolkit/latest）；时间 2026-10-14T19:36Z–19:45Z（confirm8 19:36–19:41、confirm4 19:41–19:43、anchor8 19:43–19:44、anchor4 19:44–19:45）。
**前置核验**：1) 本仓 `git pull --ff-only` 后 `git log --oneline -1` 标题含「R5: §R5 派单」 ✓；2) 蓝图仓 `git -C ../nanovllm-scatter_copy log --oneline -1` = `bb062d2` ✓；`grep "QUEUE_DEPTH = "` = `= 8` ✓；未重编 ✓；3) 四环境变量（ASCEND_CUSTOM_OPP_PATH / NANOVLLM_A5_INSTALL_OPP_PATH / NANOVLLM_CUST_OPAPI_LIB / SCATTER_C8_NUMA_NODES）grep 无匹配 ✓。
**执行**：逐字命令 confirm8/confirm4/anchor8/anchor4 四组（见派单）串行执行（r5_sweep.sh 包装：tee 日志 + STAGE_*_RC + DONE 标记，命令本体未改）。四组 RC=0；共 42 case（24/8/6/4，iters=1000 默认）。
**通过标准命中**：
- R5-G1 ✓：自检末两行 `Ran 40 tests` / `OK`。
- R5-G2 ✓：四个 manifest 全 `status=="passed"`；42 个 case JSON 全 passed、correctness 全 true；hybrid 组全部 `config.window==16` 且 `hybrid_mode=="overlap"`、`cpu_frac` 与组一致（r5_verify2.py：case_jsons_checked=42, bad=0）。
- R5-G3 ✓（结构性差异注明）：32 个 hybrid case 含 `performance.latency_us.p50/p99`；10 个 npu case 无 `latency_us` 字段，p50/p99 在 `performance.latency_us_synced`（npu 方案 Event 计时路径的结构差异，逐 case 已核 p50/p99 均在）。
- R5-G4 ✓（非门槛）：anchor8 折叠 171.343 GB/s vs §R4 E 组同坐标 171.264 GB/s，偏差 0.05% ≤ 15%。

**timing_summary.md [confirm8] 全文**（/home/h2d_test/copy-scheme-bench/results/r5/confirm8/copy_scheme_timing_summary.md）：

```
| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| hybrid | 0 | 0.1 | overlap | 8 | 24 | 300 | 234.034 | 253.663 | 167.849 |
| hybrid | 0 | 0.15 | overlap | 8 | 24 | 300 | 247.316 | 282.711 | 161.415 |
| hybrid | 0 | 0.3 | overlap | 8 | 24 | 300 | 243.695 | 280.783 | 164.463 |
| hybrid | 0 | 0.4 | overlap | 8 | 24 | 300 | 222.171 | 242.464 | 178.175 |
```

**timing_summary.md [confirm4] 全文**（/home/h2d_test/copy-scheme-bench/results/r5/confirm4/copy_scheme_timing_summary.md）：

```
| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| hybrid | 0 | 0.1 | overlap | 4 | 24 | 300 | 345.166 | 363.731 | 54.823 |
| hybrid | 0 | 0.25 | overlap | 4 | 24 | 300 | 351.281 | 360.084 | 53.807 |
```

**timing_summary.md [anchor8] 全文**（/home/h2d_test/copy-scheme-bench/results/r5/anchor8/copy_scheme_timing_summary.md）：

```
| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| npu | 0 | 0.5 | overlap | 8 | 24 | 300 | 221.831 | 232.482 | 171.343 |
```

**timing_summary.md [anchor4] 全文**（/home/h2d_test/copy-scheme-bench/results/r5/anchor4/copy_scheme_timing_summary.md）：

```
| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| npu | 0 | 0.5 | overlap | 4 | 24 | 300 | 304.851 | 325.503 | 63.300 |
```

**manifest [confirm8] 全文**（/home/h2d_test/copy-scheme-bench/results/r5/confirm8/copy_scheme_run_manifest.json）：

```json
{
  "schema_version": 2,
  "status": "passed",
  "dtype": "c8",
  "timestamp_utc": "2026-10-14T19:36:35.444815+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "queue_depth": "default",
  "case_files": [
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p1_overlap_r1.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p1_overlap_r2.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p1_overlap_r3.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p1_overlap_r4.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p1_overlap_r5.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p1_overlap_r6.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p15_overlap_r1.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p15_overlap_r2.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p15_overlap_r3.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p15_overlap_r4.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p15_overlap_r5.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p15_overlap_r6.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p3_overlap_r1.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p3_overlap_r2.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p3_overlap_r3.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p3_overlap_r4.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p3_overlap_r5.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p3_overlap_r6.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p4_overlap_r1.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p4_overlap_r2.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p4_overlap_r3.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p4_overlap_r4.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p4_overlap_r5.json",
    "hybrid_cards8_bs24_copy300_rf0p0_cf0p4_overlap_r6.json"
  ]
}
```

**manifest [confirm4] 全文**（/home/h2d_test/copy-scheme-bench/results/r5/confirm4/copy_scheme_run_manifest.json）：

```json
{
  "schema_version": 2,
  "status": "passed",
  "dtype": "c8",
  "timestamp_utc": "2026-10-14T19:41:51.808619+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "queue_depth": "default",
  "case_files": [
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p1_overlap_r1.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p1_overlap_r2.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p1_overlap_r3.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p1_overlap_r4.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p25_overlap_r1.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p25_overlap_r2.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p25_overlap_r3.json",
    "hybrid_cards4_bs24_copy300_rf0p0_cf0p25_overlap_r4.json"
  ]
}
```

**manifest [anchor8] 全文**（/home/h2d_test/copy-scheme-bench/results/r5/anchor8/copy_scheme_run_manifest.json）：

```json
{
  "schema_version": 2,
  "status": "passed",
  "dtype": "c8",
  "timestamp_utc": "2026-10-14T19:43:33.937053+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "queue_depth": "default",
  "case_files": [
    "npu_cards8_bs24_copy300_rf0p0_r1.json",
    "npu_cards8_bs24_copy300_rf0p0_r2.json",
    "npu_cards8_bs24_copy300_rf0p0_r3.json",
    "npu_cards8_bs24_copy300_rf0p0_r4.json",
    "npu_cards8_bs24_copy300_rf0p0_r5.json",
    "npu_cards8_bs24_copy300_rf0p0_r6.json"
  ]
}
```

**manifest [anchor4] 全文**（/home/h2d_test/copy-scheme-bench/results/r5/anchor4/copy_scheme_run_manifest.json）：

```json
{
  "schema_version": 2,
  "status": "passed",
  "dtype": "c8",
  "timestamp_utc": "2026-10-14T19:44:54.151813+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "queue_depth": "default",
  "case_files": [
    "npu_cards4_bs24_copy300_rf0p0_r1.json",
    "npu_cards4_bs24_copy300_rf0p0_r2.json",
    "npu_cards4_bs24_copy300_rf0p0_r3.json",
    "npu_cards4_bs24_copy300_rf0p0_r4.json"
  ]
}
```

**3 个 case JSON 全文**：


###FILE:confirm8/cf0.1 r1###
```json
{
  "schema_version": 2,
  "test": "a5_kvcache_copy_scheme_multiprocess",
  "status": "passed",
  "timestamp_utc": "2026-10-14T19:36:45.503099+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 8,
  "devices": [
    0,
    1,
    2,
    3,
    4,
    5,
    6,
    7
  ],
  "same_seed": true,
  "config": {
    "dtype": "c8",
    "row_bytes": 656,
    "batch_size": 24,
    "source_len": 65536,
    "hbm_slots": 8192,
    "copy_min": 300,
    "copy_max": 300,
    "copy_cap": 16384,
    "warmup": 10,
    "iters": 1000,
    "seed": 7,
    "allow_non_a5": false,
    "scheme": "hybrid",
    "run_frac": 0.0,
    "cpu_frac": 0.1,
    "hybrid_mode": "overlap",
    "cpu_threads": 8,
    "pretouch": false,
    "window": 16,
    "numa_nodes": ""
  },
  "summary": {
    "avg_us_mean": 209.1566800000001,
    "avg_us_max": 218.99523999999988,
    "avg_bandwidth": 180.82422725213982,
    "total_payload_bytes_per_iteration": 37785600,
    "copied_tokens_sum_per_iteration": 57600,
    "all_correct": true
  },
  "per_device": [
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:36:42.439634+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:0",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.1,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 720,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 211.72393999999946,
        "avg_us_max": 211.72393999999946,
        "avg_bandwidth": 22.308294470620623
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 211.72393999999946,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 211.7239400000003,
          "p50": 211.19125,
          "p90": 216.7675,
          "p99": 236.47875,
          "min": 192.2025,
          "max": 236.47875,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 160.60377000000003,
          "h2d_scatter_tail_us": 51.120170000000016,
          "kernel_event_us": 204.73759746551514
        }
      },
      "rank": 0,
      "logical_device_index": 0
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:36:42.421636+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:1",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.1,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 720,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 197.62854999999965,
        "avg_us_max": 197.62854999999965,
        "avg_bandwidth": 23.89938093458667
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 197.62854999999965,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 197.62854999999973,
          "p50": 197.384375,
          "p90": 201.015625,
          "p99": 224.451875,
          "min": 185.95875,
          "max": 224.451875,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 152.64808999999997,
          "h2d_scatter_tail_us": 44.980460000000015,
          "kernel_event_us": 189.67390727996826
        }
      },
      "rank": 1,
      "logical_device_index": 1
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:36:42.425300+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:2",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.1,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 720,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 201.27153000000115,
        "avg_us_max": 201.27153000000115,
        "avg_bandwidth": 23.46680625918615
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 201.27153000000115,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 201.271530000001,
          "p50": 202.10625,
          "p90": 206.665,
          "p99": 229.125625,
          "min": 142.82875,
          "max": 229.125625,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 134.17896999999996,
          "h2d_scatter_tail_us": 67.09255999999999,
          "kernel_event_us": 193.2548669576645
        }
      },
      "rank": 2,
      "logical_device_index": 2
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:36:42.443531+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:3",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.1,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 720,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 218.99523999999988,
        "avg_us_max": 218.99523999999988,
        "avg_bandwidth": 21.567592062731602
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 218.99523999999988,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 218.9952400000003,
          "p50": 219.005625,
          "p90": 224.409375,
          "p99": 246.904375,
          "min": 169.9275,
          "max": 246.904375,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 183.71867999999998,
          "h2d_scatter_tail_us": 35.27655999999999,
          "kernel_event_us": 211.25006592273712
        }
      },
      "rank": 3,
      "logical_device_index": 3
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:36:42.435264+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:4",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.1,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 720,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 209.73528000000056,
        "avg_us_max": 209.73528000000056,
        "avg_bandwidth": 22.51981640856983
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 209.73528000000056,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 209.73527999999988,
          "p50": 207.624375,
          "p90": 213.360625,
          "p99": 244.02125,
          "min": 200.169375,
          "max": 264.02,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 183.29257000000004,
          "h2d_scatter_tail_us": 26.442709999999998,
          "kernel_event_us": 201.3458217382431
        }
      },
      "rank": 4,
      "logical_device_index": 4
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:36:42.436483+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:5",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.1,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 720,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 210.71165000000067,
        "avg_us_max": 210.71165000000067,
        "avg_bandwidth": 22.41546682397478
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 210.71165000000067,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 210.7116499999996,
          "p50": 208.38125,
          "p90": 214.7325,
          "p99": 247.113125,
          "min": 200.69625,
          "max": 270.76,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 180.33172000000002,
          "h2d_scatter_tail_us": 30.379930000000012,
          "kernel_event_us": 202.7892816066742
        }
      },
      "rank": 5,
      "logical_device_index": 5
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:36:42.434916+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:6",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.1,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 720,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 209.9170199999996,
        "avg_us_max": 209.9170199999996,
        "avg_bandwidth": 22.50031941192767
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 209.9170199999996,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 209.91702,
          "p50": 209.28625,
          "p90": 214.365,
          "p99": 238.008125,
          "min": 201.4075,
          "max": 241.45875,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 164.70752000000002,
          "h2d_scatter_tail_us": 45.209500000000006,
          "kernel_event_us": 201.6685870885849
        }
      },
      "rank": 6,
      "logical_device_index": 6
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:36:42.437134+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:7",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.1,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 720,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 213.27022999999994,
        "avg_us_max": 213.27022999999994,
        "avg_bandwidth": 22.1465508805425
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 213.27022999999994,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 213.27023000000094,
          "p50": 215.66375,
          "p90": 220.026875,
          "p99": 233.208125,
          "min": 156.89625,
          "max": 233.208125,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 149.95584999999994,
          "h2d_scatter_tail_us": 63.31437999999999,
          "kernel_event_us": 204.92072367668152
        }
      },
      "rank": 7,
      "logical_device_index": 7
    }
  ]
}

```

###FILE:confirm8/cf0.1 r6###
```json
{
  "schema_version": 2,
  "test": "a5_kvcache_copy_scheme_multiprocess",
  "status": "passed",
  "timestamp_utc": "2026-10-14T19:37:51.771206+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 8,
  "devices": [
    0,
    1,
    2,
    3,
    4,
    5,
    6,
    7
  ],
  "same_seed": true,
  "config": {
    "dtype": "c8",
    "row_bytes": 656,
    "batch_size": 24,
    "source_len": 65536,
    "hbm_slots": 8192,
    "copy_min": 300,
    "copy_max": 300,
    "copy_cap": 16384,
    "warmup": 10,
    "iters": 1000,
    "seed": 7,
    "allow_non_a5": false,
    "scheme": "hybrid",
    "run_frac": 0.0,
    "cpu_frac": 0.1,
    "hybrid_mode": "overlap",
    "cpu_threads": 8,
    "pretouch": false,
    "window": 16,
    "numa_nodes": ""
  },
  "summary": {
    "avg_us_mean": 210.28546249999997,
    "avg_us_max": 223.9565000000004,
    "avg_bandwidth": 179.96971089348372,
    "total_payload_bytes_per_iteration": 37785600,
    "copied_tokens_sum_per_iteration": 57600,
    "all_correct": true
  },
  "per_device": [
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:37:48.646837+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:0",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.1,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 720,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 195.7543899999999,
        "avg_us_max": 195.7543899999999,
        "avg_bandwidth": 24.128194519673364
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 195.7543899999999,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 195.75439000000003,
          "p50": 194.870625,
          "p90": 201.125,
          "p99": 228.114375,
          "min": 188.031875,
          "max": 228.114375,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 150.17156,
          "h2d_scatter_tail_us": 45.582829999999994,
          "kernel_event_us": 187.82194030284882
        }
      },
      "rank": 0,
      "logical_device_index": 0
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:37:48.660263+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:1",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.1,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 720,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 212.81865999999874,
        "avg_us_max": 212.81865999999874,
        "avg_bandwidth": 22.193542615107283
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 212.81865999999874,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 212.81865999999985,
          "p50": 214.8,
          "p90": 219.3,
          "p99": 228.469375,
          "min": 181.1325,
          "max": 228.469375,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 148.31088,
          "h2d_scatter_tail_us": 64.50778,
          "kernel_event_us": 205.24694514274597
        }
      },
      "rank": 1,
      "logical_device_index": 1
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:37:48.670694+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:2",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.1,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 720,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 223.9565000000004,
        "avg_us_max": 223.9565000000004,
        "avg_bandwidth": 21.089809851466654
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 223.9565000000004,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 223.95649999999983,
          "p50": 222.3975,
          "p90": 230.223125,
          "p99": 268.1525,
          "min": 169.2725,
          "max": 268.1525,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 197.15293999999997,
          "h2d_scatter_tail_us": 26.803559999999997,
          "kernel_event_us": 214.87359404563904
        }
      },
      "rank": 2,
      "logical_device_index": 2
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:37:48.651860+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:3",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.1,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 720,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 201.02863999999974,
        "avg_us_max": 201.02863999999974,
        "avg_bandwidth": 23.49515969465846
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 201.02863999999974,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 201.02864000000073,
          "p50": 201.894375,
          "p90": 207.611875,
          "p99": 225.27625,
          "min": 162.360625,
          "max": 225.27625,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 152.55933,
          "h2d_scatter_tail_us": 48.46931000000003,
          "kernel_event_us": 192.96959269046783
        }
      },
      "rank": 3,
      "logical_device_index": 3
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:37:48.652258+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:4",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.1,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 720,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 209.9190700000008,
        "avg_us_max": 209.9190700000008,
        "avg_bandwidth": 22.50009968127232
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 209.9190700000008,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 209.9190699999995,
          "p50": 211.125625,
          "p90": 217.8525,
          "p99": 246.57625,
          "min": 156.03,
          "max": 246.57625,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 136.58094999999997,
          "h2d_scatter_tail_us": 73.33812000000002,
          "kernel_event_us": 201.6304794549942
        }
      },
      "rank": 4,
      "logical_device_index": 4
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:37:48.653143+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:5",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.1,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 720,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 207.91719000000043,
        "avg_us_max": 207.91719000000043,
        "avg_bandwidth": 22.716736408374842
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 207.91719000000043,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 207.91718999999978,
          "p50": 207.264375,
          "p90": 213.1225,
          "p99": 236.29375,
          "min": 195.396875,
          "max": 236.29375,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 164.31994999999998,
          "h2d_scatter_tail_us": 43.597239999999985,
          "kernel_event_us": 200.0934065580368
        }
      },
      "rank": 5,
      "logical_device_index": 5
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:37:48.664051+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:6",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.1,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 720,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 215.12149999999974,
        "avg_us_max": 215.12149999999974,
        "avg_bandwidth": 21.955964420106802
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 215.12149999999974,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 215.12149999999832,
          "p50": 215.7875,
          "p90": 220.451875,
          "p99": 241.431875,
          "min": 147.86375,
          "max": 241.431875,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 166.30037,
          "h2d_scatter_tail_us": 48.82112999999998,
          "kernel_event_us": 206.81456303596497
        }
      },
      "rank": 6,
      "logical_device_index": 6
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:37:48.659356+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:7",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.1,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 720,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 215.76774999999998,
        "avg_us_max": 215.76774999999998,
        "avg_bandwidth": 21.89020370282399
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 215.76774999999998,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 215.7677499999994,
          "p50": 215.773125,
          "p90": 222.08375,
          "p99": 238.88625,
          "min": 162.01875,
          "max": 238.88625,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 175.60205999999994,
          "h2d_scatter_tail_us": 40.165690000000005,
          "kernel_event_us": 207.4589204788208
        }
      },
      "rank": 7,
      "logical_device_index": 7
    }
  ]
}

```

###FILE:anchor8/r1###
```json
{
  "schema_version": 2,
  "test": "a5_kvcache_copy_scheme_multiprocess",
  "status": "passed",
  "timestamp_utc": "2026-10-14T19:43:47.012476+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 8,
  "devices": [
    0,
    1,
    2,
    3,
    4,
    5,
    6,
    7
  ],
  "same_seed": true,
  "config": {
    "dtype": "c8",
    "row_bytes": 656,
    "batch_size": 24,
    "source_len": 65536,
    "hbm_slots": 8192,
    "copy_min": 300,
    "copy_max": 300,
    "copy_cap": 16384,
    "warmup": 10,
    "iters": 1000,
    "seed": 7,
    "allow_non_a5": false,
    "scheme": "npu",
    "run_frac": 0.0,
    "cpu_frac": 0.5,
    "hybrid_mode": "overlap",
    "cpu_threads": 8,
    "pretouch": false,
    "window": 16,
    "numa_nodes": ""
  },
  "summary": {
    "avg_us_mean": 221.45599555969238,
    "avg_us_max": 234.09666442871094,
    "avg_bandwidth": 171.78324696031513,
    "total_payload_bytes_per_iteration": 37785600,
    "copied_tokens_sum_per_iteration": 57600,
    "all_correct": true
  },
  "per_device": [
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:43:43.762477+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:0",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "npu",
        "run_frac": 0.0,
        "cpu_frac": 0.5,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": false,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 0,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 221.83578491210938,
        "avg_us_max": 221.83578491210938,
        "avg_bandwidth": 21.291425104706693
      },
      "performance": {
        "timer": "npu_event",
        "avg_us": 221.83578491210938,
        "avg_us_host_synced": 217.19335999999987,
        "latency_us_synced": {
          "mean": 217.19335999999993,
          "p50": 212.05,
          "p90": 259.45,
          "p99": 294.41,
          "min": 176.43,
          "max": 310.34,
          "n": 250
        },
        "phases": {}
      },
      "rank": 0,
      "logical_device_index": 0
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:43:43.771688+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:1",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "npu",
        "run_frac": 0.0,
        "cpu_frac": 0.5,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": false,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 0,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 234.09666442871094,
        "avg_us_max": 234.09666442871094,
        "avg_bandwidth": 20.176280646828047
      },
      "performance": {
        "timer": "npu_event",
        "avg_us": 234.09666442871094,
        "avg_us_host_synced": 224.82564000000008,
        "latency_us_synced": {
          "mean": 224.82563999999994,
          "p50": 220.15,
          "p90": 290.96,
          "p99": 363.33,
          "min": 167.44,
          "max": 561.06,
          "n": 250
        },
        "phases": {}
      },
      "rank": 1,
      "logical_device_index": 1
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:43:43.769941+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:2",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "npu",
        "run_frac": 0.0,
        "cpu_frac": 0.5,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": false,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 0,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 233.5634765625,
        "avg_us_max": 233.5634765625,
        "avg_bandwidth": 20.22233985173664
      },
      "performance": {
        "timer": "npu_event",
        "avg_us": 233.5634765625,
        "avg_us_host_synced": 223.73056,
        "latency_us_synced": {
          "mean": 223.73055999999997,
          "p50": 213.88,
          "p90": 300.77,
          "p99": 353.51,
          "min": 169.83,
          "max": 358.05,
          "n": 250
        },
        "phases": {}
      },
      "rank": 2,
      "logical_device_index": 2
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:43:43.739610+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:3",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "npu",
        "run_frac": 0.0,
        "cpu_frac": 0.5,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": false,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 0,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 178.8670196533203,
        "avg_us_max": 178.8670196533203,
        "avg_bandwidth": 26.406209535746147
      },
      "performance": {
        "timer": "npu_event",
        "avg_us": 178.8670196533203,
        "avg_us_host_synced": 208.7602000000002,
        "latency_us_synced": {
          "mean": 208.76020000000017,
          "p50": 208.27,
          "p90": 220.46,
          "p99": 233.69,
          "min": 181.67,
          "max": 318.47,
          "n": 250
        },
        "phases": {}
      },
      "rank": 3,
      "logical_device_index": 3
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:43:43.768324+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:4",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "npu",
        "run_frac": 0.0,
        "cpu_frac": 0.5,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": false,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 0,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 221.27569580078125,
        "avg_us_max": 221.27569580078125,
        "avg_bandwidth": 21.345317581793473
      },
      "performance": {
        "timer": "npu_event",
        "avg_us": 221.27569580078125,
        "avg_us_host_synced": 253.9895200000001,
        "latency_us_synced": {
          "mean": 253.98951999999994,
          "p50": 252.62,
          "p90": 293.16,
          "p99": 337.78,
          "min": 178.36,
          "max": 379.38,
          "n": 250
        },
        "phases": {}
      },
      "rank": 4,
      "logical_device_index": 4
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:43:43.769165+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:5",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "npu",
        "run_frac": 0.0,
        "cpu_frac": 0.5,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": false,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 0,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 223.54489135742188,
        "avg_us_max": 223.54489135742188,
        "avg_bandwidth": 21.128642087589295
      },
      "performance": {
        "timer": "npu_event",
        "avg_us": 223.54489135742188,
        "avg_us_host_synced": 252.3228000000001,
        "latency_us_synced": {
          "mean": 252.3228000000001,
          "p50": 253.82,
          "p90": 291.04,
          "p99": 349.79,
          "min": 166.13,
          "max": 384.68,
          "n": 250
        },
        "phases": {}
      },
      "rank": 5,
      "logical_device_index": 5
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:43:43.785515+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:6",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "npu",
        "run_frac": 0.0,
        "cpu_frac": 0.5,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": false,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 0,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 226.9278564453125,
        "avg_us_max": 226.9278564453125,
        "avg_bandwidth": 20.81366331126583
      },
      "performance": {
        "timer": "npu_event",
        "avg_us": 226.9278564453125,
        "avg_us_host_synced": 249.67939999999987,
        "latency_us_synced": {
          "mean": 249.6794,
          "p50": 253.05,
          "p90": 293.35,
          "p99": 343.82,
          "min": 163.34,
          "max": 434.34,
          "n": 250
        },
        "phases": {}
      },
      "rank": 6,
      "logical_device_index": 6
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:43:43.768207+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:7",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "npu",
        "run_frac": 0.0,
        "cpu_frac": 0.5,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": false,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 0,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 231.5365753173828,
        "avg_us_max": 231.5365753173828,
        "avg_bandwidth": 20.399368840649004
      },
      "performance": {
        "timer": "npu_event",
        "avg_us": 231.5365753173828,
        "avg_us_host_synced": 221.2968800000001,
        "latency_us_synced": {
          "mean": 221.2968800000002,
          "p50": 222.45,
          "p90": 256.49,
          "p99": 266.14,
          "min": 165.62,
          "max": 269.94,
          "n": 250
        },
        "phases": {}
      },
      "rank": 7,
      "logical_device_index": 7
    }
  ]
}

```

**判读预案输入（repeat 折叠带宽 / repeat 极差 / p99/p50，口径=同轮同坐标，折叠值取 harness avg_bandwidth）**：
```
confirm8 (hybrid cards8 copy300, repeat6):
  cf0.1  folded_bw=167.849  min=126.406 max=180.824 range%=43.05  p99/p50 all<1.5
  cf0.15 folded_bw=161.415  min=125.014 max=184.782 range%=47.81  p99/p50 all<1.5
  cf0.3  folded_bw=164.463  min=118.126 max=192.830 range%=63.24  p99/p50 all<1.5
  cf0.4  folded_bw=178.175  min=136.793 max=217.267 range%=58.83  p99/p50 all<1.5
confirm4 (hybrid cards4 copy300, repeat4):
  cf0.1  folded_bw=54.823   min=53.859  max=56.479  range%=4.86   p99/p50 all<1.2
  cf0.25 folded_bw=53.807   min=53.394  max=54.588  range%=2.24   p99/p50 all<1.2
anchor8 (npu cards8 copy300, repeat6):
  npu    folded_bw=171.343  min=167.825 max=174.477 range%=3.96   p99/p50 all<1.5
anchor4 (npu cards4 copy300, repeat4):
  npu    folded_bw=63.300   min=55.902  max=65.949  range%=17.97  p99/p50 all<1.5
```
逐 repeat 明细（r1..r6 带宽 / mean / p50 / p99 / p99/p50）见 /tmp/r5_analysis2.py 输出，已回传如下：
```
confirm8 cf0.1: r1 180.824/211.7/211.2/236.5/1.12  r2 126.406/319.4/316.3/427.6/1.35  r3 180.160/207.0/206.7/234.0/1.13  r4 178.201/202.9/202.1/223.0/1.10  r5 161.535/276.4/277.0/389.3/1.41  r6 179.970/195.8/194.9/228.1/1.17
confirm8 cf0.15: r1 162.055/261.9/261.6/358.5/1.37  r2 152.446/149.6/150.0/205.7/1.37  r3 160.433/275.1/271.9/375.0/1.38  r4 183.762/187.7/187.1/217.7/1.16  r5 184.782/207.5/206.1/234.3/1.14  r6 125.014/321.6/321.8/384.8/1.20
confirm8 cf0.3: r1 187.227/226.3/224.1/318.1/1.42  r2 155.810/282.0/281.1/391.5/1.39  r3 191.135/174.1/173.0/211.1/1.22  r4 141.653/303.5/290.8/402.9/1.39  r5 192.830/163.2/162.3/206.4/1.27  r6 118.126/365.0/367.8/546.1/1.48
confirm8 cf0.4: r1 216.037/172.7/171.6/215.2/1.25  r2 182.225/225.3/222.9/278.1/1.25  r3 136.793/304.5/299.4/412.5/1.38  r4 217.267/166.2/159.2/226.9/1.43  r5 178.162/177.7/176.7/221.3/1.25  r6 138.563/303.1/305.7/397.9/1.30
confirm4 cf0.1: r1 53.859/354.5/358.4/392.2/1.09  r2 54.584/370.7/402.5/444.5/1.10  r3 56.479/339.6/348.6/380.8/1.09  r4 54.371/342.1/341.6/372.8/1.09
confirm4 cf0.25: r1 53.670/357.9/363.8/376.0/1.03  r2 53.577/353.5/354.6/386.5/1.09  r3 53.394/356.3/356.6/412.2/1.16  r4 54.588/337.8/337.4/356.4/1.06
anchor8 npu: r1 171.783/217.2/212.1/294.4/1.39  r2 170.640/230.9/236.7/292.7/1.24  r3 174.477/230.4/233.5/307.0/1.31  r4 171.759/208.3/209.2/227.0/1.09  r5 171.572/229.5/222.8/316.9/1.42  r6 167.825/218.4/227.8/246.5/1.08
anchor4 npu: r1 55.902/320.3/332.2/368.3/1.11  r2 65.949/224.2/221.6/314.9/1.42  r3 65.448/310.2/310.0/401.0/1.29  r4 65.902/247.0/256.4/287.1/1.12
```

**观察（只事实，判读留蓝区）**：
- confirm8 折叠带宽（harness avg_bandwidth）：cf0.1=167.849 / cf0.15=161.415 / cf0.3=164.463 / cf0.4=178.175 GB/s。最优 cf=cf0.4。
- anchor8 折叠 171.343 GB/s。最优 cf0.4 与 anchor8 之比 = 178.175/171.343 = 1.0399（+3.99%）。
- confirm8 各 cf repeat 带宽极差均 >10%（43.05/47.81/63.24/58.83%），全部达「不稳」标注；cf0.4 极差 58.83%（r4 217.267 vs r3 136.793）。
- p99/p50：42 case 全部 <2（最大 1.48），无「波动大」标注触发；cf0.3 r6 p99=546.069µs 为全组最大单值。
- 曲线形态：cf 相邻档 167.849→161.415(-3.84%)→164.463(+1.89%)→178.175(+8.34%)，无相邻档 >10% 摆动；但非单调（凹）且各档 repeat 极差大。
- anchor8 repeat 极差 3.96%（稳定），anchor4 极差 17.97%。
- 跨轮（§R4 A 组同坐标 cards8 copy300）：cf0.1 178.41→167.849（-5.92%）、cf0.4 178.90→178.175（-0.41%）；anchor8 171.343 vs §R4 E 171.264（+0.05%）。
- confirm4（参考项，漂移史证据弱）：cf0.1=54.823 / cf0.25=53.807，均 < anchor4=63.300。

**异常/备注**：
- R5-G3 结构性差异：npu 方案 case JSON 无 `performance.latency_us` 字段（Event 计时路径），p50/p99 落在 `performance.latency_us_synced`；逐 case 已核存在。hybrid 组无此差异。
- 带宽口径复核：harness `effective_bandwidth = payload_bytes / (avg_us * 1000.0)`，`payload_bytes = copied_tokens × 656`（copied_tokens = copy_count × batch_size，cards8 copy300 即 7200 token/die），多 die 带宽=各 die 速率之和；与 §R4 交付口径一致。
- 结果文件在 results/r5/（.gitignore，不入库）；日志 /home/h2d_test/copy-scheme-bench/run_r5.log。

### 判读（§R5，2026-10-15，蓝区）

对照 §R5「判读预案」（派单时写死）逐条裁决（除注明外均为绿区**实测值**）：

**门槛**：R5-G1 ✓（40 项 OK，与 920c579 一致）/ R5-G2 ✓（42 case 全
passed、correctness 全 true、window/frac/mode 核验无串组）/ R5-G3 ✓
（分位数均在；npu 方案 p50/p99 在 `latency_us_synced` 属 Event 计时
路径的既有结构差异，绿区逐 case 已核）/ R5-G4 ✓（anchor8 跨轮偏差
0.05%）。

**裁决 1：S2 弱阳性维持（三分支写死判据的居中分支）**

- 强阳性判据「最优 cf ≥ anchor8×1.05 且 repeat 极差 ≤5%」：最优 cf0.4
  = 178.175 < 179.91（=171.343×1.05）且极差 58.83% ⇒ 双条件均不满足。
- 翻回阴性判据「最优 cf < anchor8」：178.175 > 171.343 ⇒ 不成立。
- ⇒ **弱阳性维持**：带宽口径 +3.99%，收益存疑。生产形态设计稿
  （drafts/production_form_hybrid.md）维持「收益存疑，未确认」标注。
- **延迟口径补充（判读参考，非写死判据）**：cf0.4 avg_us_mean 222.171
  vs anchor 221.831µs —— **打平**（+0.15%）。带宽 +3.99% 全部来自
  per-die 偏斜（快 die 拉高速率总和）。生产 decode 看延迟，hybrid 在
  延迟口径下**无收益**。

**裁决 2：cf* 不可分辨，生产稿按 cf=0.1 写死**

- 曲线相邻档摆动 -3.84/+1.89/+8.34%（字面未触发「>10%」），但各 cf 的
  repeat 极差 43.05~63.24% 远超档间差异——按预案意图（噪声主导 ⇒
  cf* 不可分辨）裁决：**cf* 不可分辨**，生产形态稿固定 cf=0.1（R4
  延迟口径全档最稳：max/mean 仅 1.04）。

**裁决 3：cards4 同轮实锤不过锚**

- confirm4 最优 cf0.1 = 54.823 << anchor4 = 63.300（0.87x），同轮
  证据（不再是跨轮）。S2 仍仅 cards8 带宽口径弱阳。anchor4 自身极差
  17.97%（cards4 漂移史延续，该档证据弱依旧）。

**裁决 4：噪声机制收窄到 CPU gather 段（三方互洽）——NUMA 落点抽签**

- anchor8（纯 npu）repeat 极差 **3.96%** vs confirm8（hybrid）**43~63%**
  ——噪声是 hybrid/cpu 路径特有，非机器整体漂移。
- 逐 repeat 明细：cf0.4 r1 216.0 / r3 136.8 / r4 217.3 / r6 138.6
  GB/s——run 间翻倍摆动，且同一 cf 内高/低档分明。
- 与 R4 per-device 双峰（drafts/die_bimodality_r4.md：die3/7 gather 快
  1.74x）互洽：worker 每 run 重新 spawn，DRAM 池页 NUMA 落点重新抽签，
  cpu_gather 段对落点敏感，npu kernel 不经 host DRAM 访问故稳。
- 机制归因标注**推测**，但三方证据互洽；R6 以 NUMA 绑定实验直接裁决。

**结论性判断**：hybrid 相对 npu 的真实收益在带宽口径 +4%、延迟口径
打平、且不可复现（极差 43~63%）——**S2 对生产的价值存疑冻结**。
噪声机制本身成为更大靶点：若 NUMA 归置把 hybrid 各 run 稳定到分布
上沿（cf0.4 r1/r4 档 216~217 GB/s），对 anchor 的收益是 **+26%**
而非 +4%。资源转向 NUMA 归因实锤（见 §R6）。

**下一步**：R6 = NUMA 主菜（拓扑取证 + cpu/hybrid 绑定扫描）+
同轮 anchor 哨兵。队列深度扫描继续顺延（R7 候选）。

---

## §R4-旧 派单：hybrid 细 frac 扫描 + pretouch/THP 查 gather 相位成分（2026-10-15，蓝区）

### 目标

R3 判读：host 压减有效（超预期），S1 翻正未达成（w16 cpu/npu 0.88~0.89x），
S2 重开候选成立（hybrid cf0.5 于 cards4/8 < min(npu, w16 cpu)）。本轮两件事：

1. **hybrid 细 frac 扫描**（w16，overlap，cards4/8，cf∈{0.1,0.25,0.4,0.6}）：
   找最优分流点 cf*，看最优 cf 能否过同轮 npu 锚点（S2 阳性裁决）。
2. **pretouch / THP 查 w16 cpu gather 相位（28.3µs）的成分**：缺页（pretouch
   可消）？TLB miss（THP 可消）？还是纯带宽 bound（两者皆不动）？

队列深度（npu 侧余量）顺延 R5 候选。本轮无代码改动，纯测量。

### 前置核验

1. 本仓 `git pull --ff-only` 后 `git log --oneline -1` 标题为
   "R4: §R4 派单（hybrid 细 frac 扫描 + pretouch/THP 查 gather 成分）"。
2. 蓝图仓不变：`git -C ../nanovllm-scatter_copy log --oneline -1` = `bb062d2`；
   `QUEUE_DEPTH = 8`；**不需要重编**。
3. 环境变量无残留（同 §R1 前置核验第 5 条）。

### 执行命令

逐字执行（工作目录 /home/h2d_test/copy-scheme-bench）：

```bash
git pull --ff-only && git log --oneline -1
cd tests && python3 test_scheme_tools.py && cd ..
# A: hybrid 细 frac 扫描（48 case）
bash run_scheme_sweep.sh --schemes hybrid --cpu-fracs 0.1 0.25 0.4 0.6 \
  --hybrid-modes overlap --cards 4 8 --batch-size 24 --copy-count 0 100 300 \
  --window 16 --repeat 2 --results-dir results/r4/frac
# B: cpu + pretouch（24 case）
bash run_scheme_sweep.sh --schemes cpu --cards 1 2 4 8 --batch-size 24 \
  --copy-count 0 100 300 --window 16 --pretouch --repeat 2 \
  --results-dir results/r4/pretouch
# C: THP=always + pretouch（24 case）；自记录原值、自恢复
THP_EN_ORIG=$(sed 's/.*\[\(.*\)\].*/\1/' /sys/kernel/mm/transparent_hugepage/enabled)
THP_DE_ORIG=$(sed 's/.*\[\(.*\)\].*/\1/' /sys/kernel/mm/transparent_hugepage/defrag)
echo "orig: enabled=$THP_EN_ORIG defrag=$THP_DE_ORIG"
echo always > /sys/kernel/mm/transparent_hugepage/enabled
echo always > /sys/kernel/mm/transparent_hugepage/defrag
cat /sys/kernel/mm/transparent_hugepage/enabled /sys/kernel/mm/transparent_hugepage/defrag
bash run_scheme_sweep.sh --schemes cpu --cards 1 2 4 8 --batch-size 24 \
  --copy-count 0 100 300 --window 16 --pretouch --repeat 2 \
  --results-dir results/r4/pretouch_thp
echo "$THP_EN_ORIG" > /sys/kernel/mm/transparent_hugepage/enabled
echo "$THP_DE_ORIG" > /sys/kernel/mm/transparent_hugepage/defrag
cat /sys/kernel/mm/transparent_hugepage/enabled /sys/kernel/mm/transparent_hugepage/defrag
# D: 轮内基线 cpu w16（8 case；B/C 的比较基准，防跨轮漂移）
bash run_scheme_sweep.sh --schemes cpu --cards 1 8 --batch-size 24 \
  --copy-count 0 300 --window 16 --repeat 2 --results-dir results/r4/base
# E: npu 漂移哨兵（2 case；S2 判据的同轮 npu 值）
bash run_scheme_sweep.sh --schemes npu --cards 8 --batch-size 24 \
  --copy-count 300 --window 16 --repeat 2 --results-dir results/r4/anchor
```

共 106 case（蓝区 dry-run 已核验各组 case 数 48/24/24/8/2）。若 C 组 THP
节点不存在或无权限：原样记录报错，跳过 C 组，其余组照常执行（不算整轮失败）。

### 通过标准

- R4-G1：自检末两行 `Ran 39 tests` / `OK`。
- R4-G2：五个 manifest 全 `status=="passed"`；106 个 case JSON 全 passed、
  correctness 全 true；全部 case JSON `config.window==16`；pretouch/pretouch_thp
  两组 `config.pretouch==true`、base 组 `==false`（防串组）。
- R4-G3：C 组三次 cat 输出回传——「orig」行记录原值；设置后那次
  enabled/defrag 均显示 `[always]`；收尾那次恢复原值（与 orig 一致）。
- R4-G4（跨轮一致性，非门槛）：D 组 vs §R3 w16 同坐标（cpu cards1/8
  copy0/300）偏差 ≤15%；超出原样回传注明。

### 回传格式

同 §R3：交付模板 + 五个目录的 `copy_scheme_timing_summary.md` 全文 +
五个 manifest 全文 + 4 个 case JSON 全文——B/C/D 组 cpu cards1 copy100 各一
（看 gather 相位成分）、A 组 hybrid cards8 copy300 cf0.25 一个（看最优区
phases）+ C 组三次 cat 输出原文。

### 判读预案（派单时写死）

- 比较口径：同轮同坐标，avg_us_mean 用 repeat 折叠值；`p99/p50 > 2` 的坐标
  标注「波动大，证据弱」。
- **S2 阳性**：A 组最优 cf 的 hybrid copy300 cards8 带宽 ≥ 同轮 E 组 npu
  anchor ⇒ S2 阳性，转入生产形态评估（vLLM 集成形态）。
- frac 曲线：给出 cards4/8 各 copy 档的最优分流点 cf*；若曲线在边界取最优
  （无内点极小），如实记录并标注「边界最优」。
- **缺页实锤**：B 组 cpu_gather_us 较 D 组同坐标降 >15%。
- **TLB 实锤**：C 组 cpu_gather_us 较 B 组同坐标再降 >10%。
- B、C 均无明显下降 ⇒ gather 相位为纯带宽 bound，CPU 侧无更多可压空间，
  资源转 R5（队列深度）或集合层方向。
- 顺带回填 breakeven 模型：用 w16 实测 T0_cpu（5.1~6.6µs）重算交叉点 ρ*
  表，对照 drafts/breakeven_r2_preview.md 的预测（copy300 档 0.64→0.37）。
- 任何 case correctness 失败 ⇒ 该 case 无效（不影响其他坐标判读）。

---

---

### 交付（§R4，2026-10-15，绿区）

**执行环境**：机器 work21（141.61.33.21）openEuler aarch64；8× Ascend950DT_9572（可见设备 0-7）；宿主 root；CANN 9.2.0（/usr/local/Ascend/ascend-toolkit/latest）；时间 2026-10-14T18:48Z–19:10Z（A frac 18:48–18:58、B pretouch 18:58–19:03、C THP+pretouch 19:03–19:08、D base 19:08–19:09、E anchor 19:09–19:10）。
**前置核验**：1) 本仓 `git pull --ff-only` 后 `git log --oneline -1` = `c6e5f62` "R4: §R4 派单（hybrid 细 frac 扫描 + pretouch/THP 查 gather 成分）" ✓；2) 蓝图仓 `git -C ../nanovllm-scatter_copy log --oneline -1` = `bb062d2` ✓；`QUEUE_DEPTH = 8` ✓；未重编 ✓；3) 四环境变量（ASCEND_CUSTOM_OPP_PATH / NANOVLLM_A5_INSTALL_OPP_PATH / NANOVLLM_CUST_OPAPI_LIB / SCATTER_C8_NUMA_NODES）grep 无匹配 ✓。
**执行**：逐字命令 A–E 五组（见派单）串行执行（r4_sweep.sh 包装：tee 日志 + RC + DONE 标记，命令本体未改）。A/B/C/D/E 各组 RC=0；共 106 case（48/24/24/8/2）。
**通过标准**：
- R4-G1 ✓：自检末两行 `Ran 39 tests` / `OK`。
- R4-G2 ✓：五个 manifest 全 `status=="passed"`；106 case JSON 全 passed、correctness 全 true；全部 case JSON `config.window==16`；pretouch/pretouch_thp 组 `config.pretouch==true`、base 组 `==false`（r4_verify.py：case_jsons_checked=106, bad=0）。
- R4-G3 ✓：C 组三次 THP cat 输出见下（orig=madvise → 设置后双 `[always]` → 恢复后回 `[madvise]` 与 orig 一致）。
- R4-G4 ✓（非门槛）：D 组 vs §R3 w16 同坐标（cpu cards1/8 copy0/300）最大偏差 9.58% ≤ 15%（逐坐标见下）。

**timing_summary.md [frac] 全文**（/home/h2d_test/copy-scheme-bench/results/r4/frac/copy_scheme_timing_summary.md）：

```
| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| hybrid | 0 | 0.1 | overlap | 4 | 24 | 0 | 35.564 | 41.099 | 0.000 |
| hybrid | 0 | 0.1 | overlap | 4 | 24 | 100 | 194.366 | 202.660 | 32.454 |
| hybrid | 0 | 0.1 | overlap | 4 | 24 | 300 | 276.595 | 292.730 | 72.725 |
| hybrid | 0 | 0.1 | overlap | 8 | 24 | 0 | 33.619 | 36.029 | 0.000 |
| hybrid | 0 | 0.1 | overlap | 8 | 24 | 100 | 161.832 | 175.961 | 78.244 |
| hybrid | 0 | 0.1 | overlap | 8 | 24 | 300 | 212.060 | 219.553 | 178.414 |
| hybrid | 0 | 0.25 | overlap | 4 | 24 | 0 | 33.762 | 35.536 | 0.000 |
| hybrid | 0 | 0.25 | overlap | 4 | 24 | 100 | 190.794 | 197.162 | 33.040 |
| hybrid | 0 | 0.25 | overlap | 4 | 24 | 300 | 273.335 | 283.693 | 75.395 |
| hybrid | 0 | 0.25 | overlap | 8 | 24 | 0 | 35.295 | 45.811 | 0.000 |
| hybrid | 0 | 0.25 | overlap | 8 | 24 | 100 | 154.972 | 164.522 | 81.455 |
| hybrid | 0 | 0.25 | overlap | 8 | 24 | 300 | 254.010 | 302.419 | 157.394 |
| hybrid | 0 | 0.4 | overlap | 4 | 24 | 0 | 34.144 | 35.729 | 0.000 |
| hybrid | 0 | 0.4 | overlap | 4 | 24 | 100 | 193.310 | 205.496 | 32.671 |
| hybrid | 0 | 0.4 | overlap | 4 | 24 | 300 | 351.275 | 357.697 | 53.842 |
| hybrid | 0 | 0.4 | overlap | 8 | 24 | 0 | 36.054 | 44.182 | 0.000 |
| hybrid | 0 | 0.4 | overlap | 8 | 24 | 100 | 164.669 | 182.153 | 76.782 |
| hybrid | 0 | 0.4 | overlap | 8 | 24 | 300 | 216.906 | 265.078 | 178.897 |
| hybrid | 0 | 0.6 | overlap | 4 | 24 | 0 | 34.693 | 39.383 | 0.000 |
| hybrid | 0 | 0.6 | overlap | 4 | 24 | 100 | 197.834 | 208.654 | 31.900 |
| hybrid | 0 | 0.6 | overlap | 4 | 24 | 300 | 346.620 | 384.047 | 55.414 |
| hybrid | 0 | 0.6 | overlap | 8 | 24 | 0 | 36.638 | 46.542 | 0.000 |
| hybrid | 0 | 0.6 | overlap | 8 | 24 | 100 | 176.987 | 199.352 | 71.671 |
| hybrid | 0 | 0.6 | overlap | 8 | 24 | 300 | 267.305 | 303.461 | 146.371 |
```

**timing_summary.md [pretouch] 全文**（/home/h2d_test/copy-scheme-bench/results/r4/pretouch/copy_scheme_timing_summary.md）：

```
| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 0 | 4.926 | 4.926 | 0.000 |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 100 | 81.644 | 81.644 | 19.284 |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 300 | 182.306 | 182.306 | 25.908 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 0 | 5.357 | 5.400 | 0.000 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 100 | 94.191 | 101.003 | 33.909 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 300 | 200.263 | 200.767 | 47.172 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 0 | 5.415 | 5.760 | 0.000 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 100 | 114.800 | 124.676 | 55.870 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 300 | 264.437 | 288.202 | 73.077 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 0 | 6.788 | 7.303 | 0.000 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 100 | 100.219 | 117.968 | 128.408 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 300 | 255.303 | 313.438 | 154.046 |
```

**timing_summary.md [pretouch_thp] 全文**（/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/copy_scheme_timing_summary.md）：

```
| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 0 | 4.925 | 4.925 | 0.000 |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 100 | 86.323 | 86.323 | 18.240 |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 300 | 184.037 | 184.037 | 25.665 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 0 | 5.455 | 5.479 | 0.000 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 100 | 94.061 | 97.811 | 33.597 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 300 | 193.210 | 194.516 | 48.943 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 0 | 5.606 | 5.729 | 0.000 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 100 | 126.077 | 137.322 | 50.321 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 300 | 307.739 | 313.669 | 61.423 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 0 | 7.102 | 7.783 | 0.000 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 100 | 116.254 | 131.954 | 110.392 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 300 | 319.324 | 399.361 | 125.025 |
```

**timing_summary.md [base] 全文**（/home/h2d_test/copy-scheme-bench/results/r4/base/copy_scheme_timing_summary.md）：

```
| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 0 | 5.102 | 5.102 | 0.000 |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 300 | 184.237 | 184.237 | 25.639 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 0 | 7.190 | 7.569 | 0.000 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 300 | 277.124 | 357.522 | 144.526 |
```

**timing_summary.md [anchor] 全文**（/home/h2d_test/copy-scheme-bench/results/r4/anchor/copy_scheme_timing_summary.md）：

```
| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| npu | 0 | 0.5 | overlap | 8 | 24 | 300 | 221.860 | 234.950 | 171.264 |
```

**五个 manifest**（status / timestamp_utc / case_files 数）：

| dir | status | timestamp_utc | cases |
|---|---|---|---|

| frac | passed | 2026-10-14T18:48:29.664751+00:00 | 48 |

| pretouch | passed | 2026-10-14T18:58:50.328122+00:00 | 24 |

| pretouch_thp | passed | 2026-10-14T19:03:32.909873+00:00 | 24 |

| base | passed | 2026-10-14T19:08:13.504860+00:00 | 8 |

| anchor | passed | 2026-10-14T19:09:49.287080+00:00 | 2 |

**C 组三次 THP cat 输出原文**（run_r4.log）：
```

orig: enabled=madvise defrag=madvise
always [madvise] never
always defer defer+madvise [madvise] never
[always] madvise never
[always] defer defer+madvise madvise never
===C===
Running cpu_cards1_bs24_copy0_rf0p0_r1; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards1_bs24_copy0_rf0p0_r1.log
Running cpu_cards1_bs24_copy0_rf0p0_r2; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards1_bs24_copy0_rf0p0_r2.log
Running cpu_cards1_bs24_copy100_rf0p0_r1; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards1_bs24_copy100_rf0p0_r1.log
Running cpu_cards1_bs24_copy100_rf0p0_r2; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards1_bs24_copy100_rf0p0_r2.log
Running cpu_cards1_bs24_copy300_rf0p0_r1; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards1_bs24_copy300_rf0p0_r1.log
Running cpu_cards1_bs24_copy300_rf0p0_r2; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards1_bs24_copy300_rf0p0_r2.log
Running cpu_cards2_bs24_copy0_rf0p0_r1; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards2_bs24_copy0_rf0p0_r1.log
Running cpu_cards2_bs24_copy0_rf0p0_r2; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards2_bs24_copy0_rf0p0_r2.log
Running cpu_cards2_bs24_copy100_rf0p0_r1; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards2_bs24_copy100_rf0p0_r1.log
Running cpu_cards2_bs24_copy100_rf0p0_r2; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards2_bs24_copy100_rf0p0_r2.log
Running cpu_cards2_bs24_copy300_rf0p0_r1; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards2_bs24_copy300_rf0p0_r1.log
Running cpu_cards2_bs24_copy300_rf0p0_r2; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards2_bs24_copy300_rf0p0_r2.log
Running cpu_cards4_bs24_copy0_rf0p0_r1; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards4_bs24_copy0_rf0p0_r1.log
Running cpu_cards4_bs24_copy0_rf0p0_r2; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards4_bs24_copy0_rf0p0_r2.log
Running cpu_cards4_bs24_copy100_rf0p0_r1; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards4_bs24_copy100_rf0p0_r1.log
Running cpu_cards4_bs24_copy100_rf0p0_r2; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards4_bs24_copy100_rf0p0_r2.log
Running cpu_cards4_bs24_copy300_rf0p0_r1; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards4_bs24_copy300_rf0p0_r1.log
Running cpu_cards4_bs24_copy300_rf0p0_r2; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards4_bs24_copy300_rf0p0_r2.log
Running cpu_cards8_bs24_copy0_rf0p0_r1; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards8_bs24_copy0_rf0p0_r1.log
Running cpu_cards8_bs24_copy0_rf0p0_r2; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards8_bs24_copy0_rf0p0_r2.log
Running cpu_cards8_bs24_copy100_rf0p0_r1; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards8_bs24_copy100_rf0p0_r1.log
Running cpu_cards8_bs24_copy100_rf0p0_r2; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards8_bs24_copy100_rf0p0_r2.log
Running cpu_cards8_bs24_copy300_rf0p0_r1; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards8_bs24_copy300_rf0p0_r1.log
Running cpu_cards8_bs24_copy300_rf0p0_r2; log=/home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/cpu_cards8_bs24_copy300_rf0p0_r2.log
scheme  run_frac  cpu_frac  hybrid_mode  cards  batch_size  copy_count  avg_us_mean  avg_us_max  avg_bandwidth
   cpu         0       0.5      overlap      1          24           0        4.925       4.925          0.000
   cpu         0       0.5      overlap      1          24         100       86.323      86.323         18.240
   cpu         0       0.5      overlap      1          24         300      184.037     184.037         25.665
   cpu         0       0.5      overlap      2          24           0        5.455       5.479          0.000
   cpu         0       0.5      overlap      2          24         100       94.061      97.811         33.597
   cpu         0       0.5      overlap      2          24         300      193.210     194.516         48.943
   cpu         0       0.5      overlap      4          24           0        5.606       5.729          0.000
   cpu         0       0.5      overlap      4          24         100      126.077     137.322         50.321
   cpu         0       0.5      overlap      4          24         300      307.739     313.669         61.423
   cpu         0       0.5      overlap      8          24           0        7.102       7.783          0.000
   cpu         0       0.5      overlap      8          24         100      116.254     131.954        110.392
   cpu         0       0.5      overlap      8          24         300      319.324     399.361        125.025
Saved: /home/h2d_test/copy-scheme-bench/results/r4/pretouch_thp/copy_scheme_timing_summary.csv
STAGE_C_RC=0
===C-THP-RESTORED===
always [madvise] never
always defer defer+madvise [madvise] never
```

**R4-G4 逐坐标**（D 组 vs §R3 w16 同坐标，repeat 折叠 avg_us_mean）：
```

coord                              R3w16_us  R4base_us     dev%

cpu_cards1_bs24_copy0_rf0p0           5.053      5.102     0.97

cpu_cards1_bs24_copy300_rf0p0      202.924    184.237     9.21

cpu_cards8_bs24_copy0_rf0p0           6.561      7.190     9.58

cpu_cards8_bs24_copy300_rf0p0      263.169    277.124     5.30

MAX_ABS_DEV%=9.58
```

**4 个 case JSON 全文**：


###FILE:B/pretouch###
```json
{
  "schema_version": 2,
  "test": "a5_kvcache_copy_scheme_multiprocess",
  "status": "passed",
  "timestamp_utc": "2026-10-14T18:59:24.668072+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1,
  "devices": [
    0
  ],
  "same_seed": true,
  "config": {
    "dtype": "c8",
    "row_bytes": 656,
    "batch_size": 24,
    "source_len": 65536,
    "hbm_slots": 8192,
    "copy_min": 100,
    "copy_max": 100,
    "copy_cap": 16384,
    "warmup": 10,
    "iters": 1000,
    "seed": 7,
    "allow_non_a5": false,
    "scheme": "cpu",
    "run_frac": 0.0,
    "cpu_frac": 0.5,
    "hybrid_mode": "overlap",
    "cpu_threads": 8,
    "pretouch": true,
    "window": 16,
    "numa_nodes": ""
  },
  "summary": {
    "avg_us_mean": 81.69047999999991,
    "avg_us_max": 81.69047999999991,
    "avg_bandwidth": 19.272747571075623,
    "total_payload_bytes_per_iteration": 1574400,
    "copied_tokens_sum_per_iteration": 2400,
    "all_correct": true
  },
  "per_device": [
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T18:59:21.871401+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:0",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 100,
        "copy_max": 100,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "cpu",
        "run_frac": 0.0,
        "cpu_frac": 0.5,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": true,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100
        ],
        "copied_tokens": 2400,
        "cpu_tokens": 0,
        "payload_bytes_per_iteration": 1574400
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 100,
        "avg_us_mean": 81.69047999999991,
        "avg_us_max": 81.69047999999991,
        "avg_bandwidth": 19.272747571075623
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 81.69047999999991,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 81.69047999999967,
          "p50": 75.32875,
          "p90": 101.9225,
          "p99": 138.195625,
          "min": 73.27625,
          "max": 138.195625,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "cpu_gather_us": 26.731340000000003,
          "device_wall_us": 54.95913999999999,
          "device_event_us": 49.186088263988495,
          "device_overhead_us": 5.773051736011498
        }
      },
      "rank": 0,
      "logical_device_index": 0
    }
  ]
}

```

###FILE:C/pretouch_thp###
```json
{
  "schema_version": 2,
  "test": "a5_kvcache_copy_scheme_multiprocess",
  "status": "passed",
  "timestamp_utc": "2026-10-14T19:04:06.327425+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1,
  "devices": [
    0
  ],
  "same_seed": true,
  "config": {
    "dtype": "c8",
    "row_bytes": 656,
    "batch_size": 24,
    "source_len": 65536,
    "hbm_slots": 8192,
    "copy_min": 100,
    "copy_max": 100,
    "copy_cap": 16384,
    "warmup": 10,
    "iters": 1000,
    "seed": 7,
    "allow_non_a5": false,
    "scheme": "cpu",
    "run_frac": 0.0,
    "cpu_frac": 0.5,
    "hybrid_mode": "overlap",
    "cpu_threads": 8,
    "pretouch": true,
    "window": 16,
    "numa_nodes": ""
  },
  "summary": {
    "avg_us_mean": 86.99071999999964,
    "avg_us_max": 86.99071999999964,
    "avg_bandwidth": 18.09848222890909,
    "total_payload_bytes_per_iteration": 1574400,
    "copied_tokens_sum_per_iteration": 2400,
    "all_correct": true
  },
  "per_device": [
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:04:03.334299+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:0",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 100,
        "copy_max": 100,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "cpu",
        "run_frac": 0.0,
        "cpu_frac": 0.5,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": true,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100,
          100
        ],
        "copied_tokens": 2400,
        "cpu_tokens": 0,
        "payload_bytes_per_iteration": 1574400
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 100,
        "avg_us_mean": 86.99071999999964,
        "avg_us_max": 86.99071999999964,
        "avg_bandwidth": 18.09848222890909
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 86.99071999999964,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 86.9907199999998,
          "p50": 85.775,
          "p90": 89.635,
          "p99": 127.775,
          "min": 82.570625,
          "max": 127.775,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "cpu_gather_us": 28.056609999999992,
          "device_wall_us": 58.93411000000002,
          "device_event_us": 53.29691195487976,
          "device_overhead_us": 5.637198045120255
        }
      },
      "rank": 0,
      "logical_device_index": 0
    }
  ]
}

```

###FILE:D/base###
```json
{
  "schema_version": 2,
  "test": "a5_kvcache_copy_scheme_multiprocess",
  "status": "passed",
  "timestamp_utc": "2026-10-14T19:08:47.866667+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1,
  "devices": [
    0
  ],
  "same_seed": true,
  "config": {
    "dtype": "c8",
    "row_bytes": 656,
    "batch_size": 24,
    "source_len": 65536,
    "hbm_slots": 8192,
    "copy_min": 300,
    "copy_max": 300,
    "copy_cap": 16384,
    "warmup": 10,
    "iters": 1000,
    "seed": 7,
    "allow_non_a5": false,
    "scheme": "cpu",
    "run_frac": 0.0,
    "cpu_frac": 0.5,
    "hybrid_mode": "overlap",
    "cpu_threads": 8,
    "pretouch": false,
    "window": 16,
    "numa_nodes": ""
  },
  "summary": {
    "avg_us_mean": 182.6161299999997,
    "avg_us_max": 182.6161299999997,
    "avg_bandwidth": 25.864089880778916,
    "total_payload_bytes_per_iteration": 4723200,
    "copied_tokens_sum_per_iteration": 7200,
    "all_correct": true
  },
  "per_device": [
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T19:08:45.070016+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:0",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "cpu",
        "run_frac": 0.0,
        "cpu_frac": 0.5,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 0,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 182.6161299999997,
        "avg_us_max": 182.6161299999997,
        "avg_bandwidth": 25.864089880778916
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 182.6161299999997,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 182.61612999999875,
          "p50": 181.56125,
          "p90": 184.919375,
          "p99": 242.11375,
          "min": 176.421875,
          "max": 242.11375,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "cpu_gather_us": 69.02941,
          "device_wall_us": 113.58672,
          "device_event_us": 105.53224939107895,
          "device_overhead_us": 8.054470608921052
        }
      },
      "rank": 0,
      "logical_device_index": 0
    }
  ]
}

```

###FILE:A/frac_hybrid_cards8_copy300_cf0p25###
```json
{
  "schema_version": 2,
  "test": "a5_kvcache_copy_scheme_multiprocess",
  "status": "passed",
  "timestamp_utc": "2026-10-14T18:53:25.250583+00:00",
  "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 8,
  "devices": [
    0,
    1,
    2,
    3,
    4,
    5,
    6,
    7
  ],
  "same_seed": true,
  "config": {
    "dtype": "c8",
    "row_bytes": 656,
    "batch_size": 24,
    "source_len": 65536,
    "hbm_slots": 8192,
    "copy_min": 300,
    "copy_max": 300,
    "copy_cap": 16384,
    "warmup": 10,
    "iters": 1000,
    "seed": 7,
    "allow_non_a5": false,
    "scheme": "hybrid",
    "run_frac": 0.0,
    "cpu_frac": 0.25,
    "hybrid_mode": "overlap",
    "cpu_threads": 8,
    "pretouch": false,
    "window": 16,
    "numa_nodes": ""
  },
  "summary": {
    "avg_us_mean": 259.4926812500004,
    "avg_us_max": 296.4943300000003,
    "avg_bandwidth": 154.20061312221608,
    "total_payload_bytes_per_iteration": 37785600,
    "copied_tokens_sum_per_iteration": 57600,
    "all_correct": true
  },
  "per_device": [
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T18:53:22.215990+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:0",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.25,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 1800,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 294.2852500000022,
        "avg_us_max": 294.2852500000022,
        "avg_bandwidth": 16.049734059046337
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 294.2852500000022,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 294.2852500000012,
          "p50": 296.52125,
          "p90": 307.554375,
          "p99": 397.29,
          "min": 175.111875,
          "max": 397.29,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 284.6283700000001,
          "h2d_scatter_tail_us": 9.656880000000005,
          "kernel_event_us": 284.1626890897751
        }
      },
      "rank": 0,
      "logical_device_index": 0
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T18:53:22.207279+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:1",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.25,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 1800,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 282.32988999999964,
        "avg_us_max": 282.32988999999964,
        "avg_bandwidth": 16.729365778451605
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 282.32988999999964,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 282.3298900000016,
          "p50": 278.83875,
          "p90": 291.780625,
          "p99": 376.228125,
          "min": 265.28,
          "max": 376.228125,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 273.52639,
          "h2d_scatter_tail_us": 8.803500000000001,
          "kernel_event_us": 272.9458272457123
        }
      },
      "rank": 1,
      "logical_device_index": 1
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T18:53:22.214710+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:2",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.25,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 1800,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 289.45696999999893,
        "avg_us_max": 289.45696999999893,
        "avg_bandwidth": 16.317451260544935
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 289.45696999999893,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 289.45696999999996,
          "p50": 286.735,
          "p90": 300.615,
          "p99": 379.82875,
          "min": 237.189375,
          "max": 379.82875,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 280.7143699999999,
          "h2d_scatter_tail_us": 8.742600000000003,
          "kernel_event_us": 280.4544677734375
        }
      },
      "rank": 2,
      "logical_device_index": 2
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T18:53:22.094929+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:3",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.25,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 1800,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 173.3438900000009,
        "avg_us_max": 173.3438900000009,
        "avg_bandwidth": 27.24757128734088
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 173.3438900000009,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 173.34388999999913,
          "p50": 172.674375,
          "p90": 176.194375,
          "p99": 211.145,
          "min": 166.315,
          "max": 211.145,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 167.06895999999998,
          "h2d_scatter_tail_us": 6.27493,
          "kernel_event_us": 166.82114684581757
        }
      },
      "rank": 3,
      "logical_device_index": 3
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T18:53:22.220627+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:4",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.25,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 1800,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 296.4943300000003,
        "avg_us_max": 296.4943300000003,
        "avg_bandwidth": 15.930152863294202
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 296.4943300000003,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 296.4943300000012,
          "p50": 301.74,
          "p90": 310.453125,
          "p99": 396.703125,
          "min": 173.9025,
          "max": 396.703125,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 285.81708999999995,
          "h2d_scatter_tail_us": 10.67724,
          "kernel_event_us": 285.5232570171356
        }
      },
      "rank": 4,
      "logical_device_index": 4
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T18:53:22.216527+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:5",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.25,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 1800,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 293.89662000000095,
        "avg_us_max": 293.89662000000095,
        "avg_bandwidth": 16.070957195764908
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 293.89662000000095,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 293.89661999999845,
          "p50": 296.04125,
          "p90": 310.039375,
          "p99": 390.38375,
          "min": 173.299375,
          "max": 390.38375,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 284.11985000000004,
          "h2d_scatter_tail_us": 9.776769999999999,
          "kernel_event_us": 283.89583945274353
        }
      },
      "rank": 5,
      "logical_device_index": 5
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T18:53:22.207716+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:6",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.25,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 1800,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 284.7617600000003,
        "avg_us_max": 284.7617600000003,
        "avg_bandwidth": 16.58649672624581
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 284.7617600000003,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 284.7617600000006,
          "p50": 282.4925,
          "p90": 296.23,
          "p99": 364.55625,
          "min": 262.7025,
          "max": 364.55625,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 275.08822999999995,
          "h2d_scatter_tail_us": 9.67353,
          "kernel_event_us": 274.31344962120056
        }
      },
      "rank": 6,
      "logical_device_index": 6
    },
    {
      "schema_version": 2,
      "test": "a5_kvcache_copy_scheme_singlecard",
      "status": "passed",
      "timestamp_utc": "2026-10-14T18:53:22.083043+00:00",
      "device_count": 1,
      "config": {
        "device": "npu:7",
        "device_name": "Ascend950DT_9572",
        "dtype": "c8",
        "row_bytes": 656,
        "batch_size": 24,
        "source_len": 65536,
        "hbm_slots": 8192,
        "copy_min": 300,
        "copy_max": 300,
        "copy_cap": 16384,
        "warmup": 10,
        "iters": 1000,
        "seed": 7,
        "scheme": "hybrid",
        "run_frac": 0.0,
        "cpu_frac": 0.25,
        "hybrid_mode": "overlap",
        "cpu_threads": 8,
        "pretouch": false,
        "staging_pinned": true,
        "window": 16,
        "queue_depth": 8
      },
      "workload": {
        "copy_counts": [
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300,
          300
        ],
        "copied_tokens": 7200,
        "cpu_tokens": 1800,
        "payload_bytes_per_iteration": 4723200
      },
      "correctness": {
        "data_exact": true,
        "guard_unchanged": true,
        "zero_count_unchanged": true,
        "first_fill_capacity": true,
        "metadata_unchanged": true
      },
      "summary": {
        "cards": 1,
        "batch_size": 24,
        "copy_count": 300,
        "avg_us_mean": 161.3727399999998,
        "avg_us_max": 161.3727399999998,
        "avg_bandwidth": 29.268883951527414
      },
      "performance": {
        "timer": "perf_counter",
        "avg_us": 161.3727399999998,
        "avg_us_host_synced": null,
        "latency_us": {
          "mean": 161.37273999999957,
          "p50": 161.25,
          "p90": 165.185625,
          "p99": 205.66,
          "min": 149.761875,
          "max": 205.66,
          "n": 1000
        },
        "window": 16,
        "phases": {
          "launch_to_gather_done_us": 155.39473000000007,
          "h2d_scatter_tail_us": 5.978009999999999,
          "kernel_event_us": 155.36250507831573
        }
      },
      "rank": 7,
      "logical_device_index": 7
    }
  ]
}

```

**breakeven 回填（w16 实测 T0_cpu 重算 ρ＊）**：`python3 tools/breakeven.py` 于 R4 base+anchor 与 §R3 anchor 合并目录（R4 同轮优先，cards1 缺同轮 npu 用 §R3 anchor 值，已注）。输出（节选 crossover）：
```
cards1 bs24 cpu copy300: T0=5.1us T_full=184.2us marginal=24.88ns/token
cards1 bs24 npu copy300: T0=11.0us T_full=139.0us marginal=17.77ns/token
  crossover cards1 bs24 copy300: npu_full=139.0us vs cpu(T0=5.1, span=179.1) => rho*=0.25 (cpu-delta wins for rho > 0.25)
cards8 bs24 cpu copy300: T0=7.2us T_full=277.1us marginal=37.49ns/token
cards8 bs24 npu copy300: T0=11.6us T_full=222.6us marginal=29.31ns/token
  crossover cards8 bs24 copy300: npu_full=222.6us vs cpu(T0=7.2, span=269.9) => rho*=0.20 (cpu-delta wins for rho > 0.20)
```
T0_cpu(w16) 实测 5.102/7.190µs（D 组 copy0，cards1/8）。对照 drafts/breakeven_r2_preview.md 预测（copy300 档 cards1 0.64→0.37），实际 ρ＊ 左移至 0.25/0.20。

**观察（只事实，判读留蓝区）**：
- A 组 frac（hybrid w16 overlap，repeat 折叠 avg_us_mean / 带宽 GB/s）：cards8 copy300 = cf0.1 212.06µs/178.41、cf0.25 254.01µs/157.39、cf0.4 216.91µs/178.90、cf0.6 267.31µs/146.37；cards4 copy300 = 72.73/75.40/53.84/55.41（cf0.1/0.25/0.4/0.6）。同轮 E 组 npu anchor cards8 copy300 = 221.86µs / 171.26 GB/s。cf0.25（max 302.4 vs mean 254.0）与 cf0.6（max 303.5 vs 267.3）档 cards8 波动较大。
- B pretouch（cpu w16，cpu_gather_us）：cards1 copy100 = 26.731（§R3 w16 同坐标 28.264，-5.4%，跨轮参考）；同轮 copy300：cards1 69.053 vs D base 69.029（持平）、cards8 136.195 vs D base r1 253.258（-46.2%）。B cards8 copy300 折叠 255.303µs/154.05 GB/s vs D 折叠 277.124µs/144.53 GB/s。
- C THP+pretouch（cpu w16，cpu_gather_us）：cards1 copy100 = 28.057 vs B 26.731（+5.0%）；copy300 cards1 69.077 vs B 69.053（持平）；cards8 179.394 vs B 136.195（+31.7%，仍低于 D base r1 253.258 的 -29.2%）。
- p99/p50（latency_us）：B cards1 copy100 138.2/75.3=1.83、C 127.8/85.8=1.49、D cards1 copy300 242.1/181.6=1.33、A cards8 cf0.25 die0 397.3/296.5=1.34——均 <2，无坐标触发「波动大」标注；但 cards8 copy300 档 avg_us_max 明显高于 mean（D 357.5 vs 277.1、B 313.4 vs 255.3、C 399.4 vs 319.3），cards8 长尾显著。

**异常/备注**：
- D 组（base）派单命令为 `--copy-count 0 300`，无 copy100 坐标；回传格式「B/C/D 组 cpu cards1 copy100 各一」中 D 组无法提供 copy100，改用 D 组 cpu cards1 copy300 case（同组同坐标看 gather 相位），特此注明。
- 缺页判据「B 组 cpu_gather 较 D 组同坐标降 >15%」：D 组无 copy100，copy100 档缺同轮 D 坐标可比；同轮可比的为 copy300（B vs D：cards8 -46.2%、cards1 持平）；B copy100 vs §R3 w16 copy100 为跨轮参考（-5.4%）。判读权在蓝区。
- R4-G4 参考值取 results/r3/w16 同坐标 case（repeat 折叠）。
- breakeven cards1 的 npu_full 139.0µs 取自 §R3 anchor（跨轮，R4 E 组仅 cards8）；cards8 为 R4 同轮。

### 判读（§R4，2026-10-15，蓝区）

对照 §R4「判读预案」（派单时写死）逐条裁决（除注明外均为绿区**实测值**，
repeat 折叠后均值）：

**门槛**：R4-G1 ✓（39 项 OK，绿区 pull 的 c6e5f62 即 39 项）/ R4-G2 ✓（五
manifest 全 passed、106 case correctness 全 true、window=16 与 pretouch
分档核验无串组）/ R4-G3 ✓（THP orig=madvise → 双 `[always]` → 恢复
madvise，三次 cat 原文在案）/ R4-G4 ✓（D 对 R3 w16 同坐标最大偏差
9.58% ≤15%）。

**波动口径**：p99/p50 均 <2（1.33~1.83），无坐标触发「波动大」标注；
但 cards8 copy300 档 avg_us_max 明显高于 mean（D 357.5 vs 277.1、C 399.4
vs 319.3），**cards8 长尾显著**；A 组 cf0.25/cf0.6 档 max/mean 差 ~19%/13%。

**裁决 1：S2 阳性（弱阳性）——判据命中，边际在噪声带内**

- 写死判据「A 组最优 cf 的 hybrid copy300 cards8 带宽 ≥ 同轮 E 组 npu
  anchor」：最优 cf0.4 = **178.897 GB/s**、次优 cf0.1 = 178.414，均 ≥
  anchor **171.264** ⇒ **S2 阳性**（边际 +4.5%/+4.2%）。
- 延迟口径互证：cf0.1 avg_us_mean 212.06 < anchor 221.86µs（-4.4%）；
  cf0.4 216.91 < 221.86（-2.2%）。
- **弱阳性标注**：frac 曲线非单调——cf0.25 凹陷至 157.39（相邻档摆动
  ±10%），说明 run 级噪声与边际同量级；判据是「≥」故裁决为阳性，但证据
  强度不足以直接指导生产集成，按预案进入确认跑（见 §R5）。
- cf* 记录：cards8 copy300 吞吐口径 cf*=0.4（178.90）、延迟口径 cf*=0.1
  （212.06µs 且 avg_us_max 219.6 全档最稳，**生产推荐 0.1**）；cards8
  copy100 cf*=0.25（81.46，内点最优）；cards4 copy100/300 cf*=0.25
  （33.04/75.40，内点最优）；copy0 档各 cf 无差异（33.6~36.6µs）。
- cards4 未过锚：hybrid cards4 copy300 最优 75.40 < §R3 npu cards4 锚
  76.70（跨轮，且 cards4 档有连续两轮漂移史，证据弱）——S2 目前仅
  cards8 成立。

**裁决 2：缺页实锤（cards8 限定），pretouch 纳入正式配置候选**

- 写死判据「B 组 cpu_gather_us 较 D 组同坐标降 >15%」：cards8 copy300
  **136.195 vs 253.258 = -46.2%** ⇒ **实锤**；cards1 copy300 持平
  （69.053 vs 69.029）⇒ 小池无效应。
- 机制解读（推测，与数据一致）：8 die 池地址空间 8 倍于单 die，run 内
  first-touch 缺页持续发生；pretouch 把该成本移出计时区。cards1 池小，
  warmup 即触完，故无差。
- 端到端收益（实测，folded）：cards8 copy300 总时 255.30 vs 277.12µs
  = -7.9%；cards1 -1.0%。缺页是 cards8 真实成本但非全部；gather 剩余
  部分仍为带宽 bound。
- 注意：-46.2% 为 B 折叠值 vs D r1 值（绿区已注明 D 组相位数据仅 r1 回
  传）；即使保守按 r1 比 r1，降幅远超 15% 门槛，结论方向不依赖该口径。

**裁决 3：TLB 实锤不成立，THP=always 在 cards8 显著有害，不采用**

- 写死判据「C 组 cpu_gather_us 较 B 组同坐标再降 >10%」：全坐标不降——
  cards1 copy100 +5.0%、cards1 copy300 持平、cards8 copy300 **+31.7%**
  （179.394 vs 136.195）⇒ **TLB 实锤不成立**。
- THP=always 有害（实测）：C 组 cards4/8 copy300 总时较 B 反升
  16.4%/25.1%（307.7 vs 264.4 / 319.3 vs 255.3µs）。2MB 大页分配+
  defrag 路径在大池高并发下引入新开销（机制推测）。**THP=always 不纳入
  任何后续配置**，环境维持 madvise。

**裁决 4：breakeven 回填（同轮 w16 T0_cpu 实测）**

- ρ*（copy300 档，cpu-delta vs npu-full）：cards1 **0.25** / cards8
  **0.20**（R4 同轮；T0=5.102/7.190µs 来自 D 组 copy0）。对照
  drafts/breakeven_r2_preview.md 预测 0.64→0.37，实际进一步左移；与 §R3
  回填（0.32/0.16）同量级互洽。
- 结论加强：驻留+增量路线（churn 稳态 ρ=0.85~0.9）深度过盈亏点；
  即使 ρ=0.3 的激进换出场景，cards1/8 也已越界进入 cpu-delta 收益区。

**预测对照**（drafts/r4_prediction.md，派单前写死）：① cf* 低端——部分
命中（cards8 延迟口径 cf0.1 命中，吞吐口径 cf0.4 未命中）；② S2 不翻阳——
**证伪**（翻阳，弱阳性；预判自注「翻阳即最有价值的证伪」，正是）；③ gather
纯带宽 bound——**证伪一半**（cards8 缺页实锤 -46.2%，非纯带宽 bound；C 方向
对——TLB 无收益——但形式错：不是不动而是显著变差）；④ D 对 R3 偏差 <10%
——命中（9.58%）。

**下一步**：R5 = S2 弱阳性**同轮高重复确认跑**（最优区 cf0.1/0.4 + 曲线加密
cf0.15/0.3，repeat 6，配同轮 npu anchor；cards4 次要确认）——边际 4.5% 与
run 噪声同量级，必须先确认再投入生产形态设计。蓝区并行产出生产形态设计稿
（hybrid 嵌入 vLLM 层间流水）。pretouch 确认为 cpu/hybrid 正式配置候选，
R6 起纳入默认；队列深度扫描顺延 R6 候选。

---

## §R3-旧 派单：窗口化流水压 host 开销 + cpu/hybrid 同坐标复试（2026-10-15，蓝区）

### 目标

R2 判读 S1 阴性（host 开销主导：cpu 未归类 host 开销 34.9%>30%，copy0 纯固定
开销 56.9~119.8µs 随 die 数上涨）。本轮验证写死分支的下一步：worker 新增
`--window N`（每窗口 N 次迭代共享一次同步，每迭代独占 staging slot），
**window=16（吞吐模式）vs window=1（R2 语义，轮内基线）**同轮对比。

### 前置核验

1. 本仓 `git pull --ff-only` 后 `git log --oneline -1` 标题为
   "R3: §R3 派单（host 压减复试 window 1 vs 16）+ drafts 状态更新"。
2. 蓝图仓不变：`git -C ../nanovllm-scatter_copy log --oneline -1` = `bb062d2`；
   `QUEUE_DEPTH = 8`；**不需要重编**。
3. 环境变量无残留（同 §R1 前置核验第 5 条）。

### 执行命令

逐字执行（工作目录 /home/h2d_test/copy-scheme-bench）：

```bash
git pull --ff-only && git log --oneline -1
cd tests && python3 test_scheme_tools.py && cd ..
# A: window=1 轮内基线（与 R2 同语义，48 case）
bash run_scheme_sweep.sh --schemes cpu hybrid --cpu-fracs 0.5 --hybrid-modes overlap \
  --cards 1 2 4 8 --batch-size 24 --copy-count 0 100 300 --repeat 2 \
  --results-dir results/r3/w1
# B: window=16 吞吐模式（48 case）
bash run_scheme_sweep.sh --schemes cpu hybrid --cpu-fracs 0.5 --hybrid-modes overlap \
  --cards 1 2 4 8 --batch-size 24 --copy-count 0 100 300 --repeat 2 --window 16 \
  --results-dir results/r3/w16
# C: npu 锚点（12 case；window 对 npu 无影响，只作轮内对照）
bash run_scheme_sweep.sh --schemes npu --cards 1 4 8 --batch-size 24 \
  --copy-count 0 300 --repeat 2 --results-dir results/r3/anchor
```

### 通过标准

- R3-G1：自检末两行 `Ran 38 tests` / `OK`。
- R3-G2：三个 manifest 全 `status=="passed"`；108 个 case JSON 全 passed、
  correctness 全 true；`w16` 目录 case JSON 的 `config.window==16`，
  `w1` 目录 `==1`（防窗口串组）。
- R3-G3（跨轮一致性，非门槛）：w1 的 cpu/hybrid 坐标与 §R2 交付 summary 同
  坐标偏差 ≤15%；超出原样回传注明。

### 回传格式

同 §R2：交付模板 + 三个目录的 `copy_scheme_timing_summary.md` 全文 +
manifest 全文 + 4 个 JSON 全文（cpu cards1 copy100 的 w1/w16 各一、hybrid
cards1 copy100 的 w1/w16 各一，看 phases 用）。

### 判读预案（派单时写死）

- 比较口径：同轮同坐标，avg_us_mean 用 repeat 折叠值；引用分位数时用 p50；
  `p99/p50 > 2` 的坐标标注「波动大，证据弱」。
- 若 w16 cpu 的未归类 host 开销（= avg_us − cpu_gather_us − device_wall_us）
  占 avg_us 从 w1 的 ~35% 降到 <10% ⇒ **host 压减有效**。
- 若 w16 cpu 在 copy300 的 cards4/cards8 坐标 ≥ 同轮 npu 锚点带宽 ⇒
  **S1 翻正（窗口化形态）**，下一轮做生产形态评估（流水线化集成）。
- 若 w16 未归类占比仍 >30% ⇒ host 开销不是同步主导（是 Python/torch 调用
  本身），cpu 路径判死，资源转集合层方向（churn 工具链已就绪）。
- 若 w16 hybrid < 同坐标 min(npu, w16 cpu) ⇒ S2 重开候选，下轮扫细 frac。
- 任何 case correctness 失败 ⇒ 该 case 无效；窗口化破坏正确性（如
  assert_copied 失败集中出现在 w16）⇒ 窗口实现有竞态，蓝区修复后重派。

### 交付（§R3，2026-10-15，绿区）

**执行环境**：机器 work21（141.61.33.21）openEuler aarch64；8× Ascend950DT_9572（可见设备 0-7）；宿主 root；CANN 9.2.0（/usr/local/Ascend/ascend-toolkit/latest）；时间 2026-10-14T17:56:27Z–18:18:29Z（A w1 17:56:27–18:06:14Z、B w16 18:06:14–18:15:57Z、C npu 锚点 18:15:57–18:18:29Z）。
**前置核验**：逐条实际值——
1. 本仓 `git log --oneline -1` = `0bb950d R3: §R3 派单（host 压减复试 window 1 vs 16）+ drafts 状态更新` ✓
2. 蓝图仓 `git -C ../nanovllm-scatter_copy log --oneline -1` = `bb062d2` ✓；`QUEUE_DEPTH = 8` 计数 1 ✓；`_custom_opp_c8/` 构建产物仍在 ✓；**未重编**（派单注明不需要）✓
3. 环境变量无残留：ASCEND_CUSTOM_OPP_PATH/PYTHONPATH/ASCEND_AICPU_PATH 空，LD_LIBRARY_PATH 仅 driver 基础路径 ✓
**执行**：命令逐字执行，无偏差。自检 `test_scheme_tools.py` 38 tests OK；A `--window` 缺省=1（w1 轮内基线）48 case；B `--window 16`（w16 吞吐模式）48 case；C npu 锚点 12 case；均 `--repeat 2` iters=1000 默认。三组 manifest 全 passed。
**通过标准命中**：
- R3-G1 ✓：`Ran 38 tests` / `OK`，RC=0。
- R3-G2 ✓：三个 manifest（w1/w16/anchor）全 `status=="passed"`；108 case JSON 全 passed、correctness 全 true（脚本逐 case 核验，bad=0）；window 分档正确——w1 目录 48×window=1、w16 目录 48×window=16、anchor 12×window=1（防串组）✓。
- R3-G3 ✓（跨轮一致性，非门槛）：w1 cpu/hybrid 24 坐标 vs §R2 交付 summary 同坐标（cf0.5）偏差最大 14.77%（hybrid cards8 copy100），全部 ≤15%，未触发超限。逐坐标偏差见下表（观察节）。
**原始数据**：

`results/r3/w1/copy_scheme_timing_summary.md` 全文：

```
| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 0 | 69.195 | 69.195 | 0.000 |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 100 | 191.005 | 191.005 | 8.262 |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 300 | 272.334 | 272.334 | 17.344 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 0 | 74.827 | 77.288 | 0.000 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 100 | 205.370 | 208.145 | 15.335 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 300 | 303.942 | 305.154 | 31.102 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 0 | 92.351 | 99.582 | 0.000 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 100 | 246.993 | 267.213 | 25.744 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 300 | 361.316 | 371.806 | 52.872 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 0 | 114.162 | 134.178 | 0.000 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 100 | 236.409 | 248.794 | 53.384 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 300 | 356.267 | 382.240 | 106.944 |
| hybrid | 0 | 0.5 | overlap | 1 | 24 | 0 | 111.906 | 111.906 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 1 | 24 | 100 | 263.792 | 263.792 | 5.969 |
| hybrid | 0 | 0.5 | overlap | 1 | 24 | 300 | 277.943 | 277.943 | 17.001 |
| hybrid | 0 | 0.5 | overlap | 2 | 24 | 0 | 117.609 | 119.623 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 2 | 24 | 100 | 271.237 | 285.175 | 11.668 |
| hybrid | 0 | 0.5 | overlap | 2 | 24 | 300 | 317.671 | 326.270 | 29.776 |
| hybrid | 0 | 0.5 | overlap | 4 | 24 | 0 | 121.440 | 125.782 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 4 | 24 | 100 | 296.753 | 314.578 | 21.280 |
| hybrid | 0 | 0.5 | overlap | 4 | 24 | 300 | 399.800 | 422.604 | 47.729 |
| hybrid | 0 | 0.5 | overlap | 8 | 24 | 0 | 145.630 | 164.356 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 8 | 24 | 100 | 302.638 | 349.403 | 41.914 |
| hybrid | 0 | 0.5 | overlap | 8 | 24 | 300 | 419.553 | 453.436 | 90.441 |
```

`results/r3/w16/copy_scheme_timing_summary.md` 全文：

```
| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 0 | 5.053 | 5.053 | 0.000 |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 100 | 89.672 | 89.672 | 17.576 |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 300 | 202.924 | 202.924 | 23.326 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 0 | 5.216 | 5.330 | 0.000 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 100 | 99.417 | 107.567 | 31.948 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 300 | 199.888 | 200.237 | 47.259 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 0 | 5.941 | 6.626 | 0.000 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 100 | 123.758 | 137.662 | 51.195 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 300 | 290.081 | 324.430 | 67.380 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 0 | 6.561 | 7.084 | 0.000 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 100 | 92.090 | 108.910 | 138.021 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 300 | 263.169 | 297.314 | 151.735 |
| hybrid | 0 | 0.5 | overlap | 1 | 24 | 0 | 32.354 | 32.354 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 1 | 24 | 100 | 162.861 | 162.861 | 9.668 |
| hybrid | 0 | 0.5 | overlap | 1 | 24 | 300 | 177.072 | 177.072 | 26.674 |
| hybrid | 0 | 0.5 | overlap | 2 | 24 | 0 | 33.604 | 34.679 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 2 | 24 | 100 | 168.225 | 170.275 | 18.721 |
| hybrid | 0 | 0.5 | overlap | 2 | 24 | 300 | 246.809 | 260.858 | 38.478 |
| hybrid | 0 | 0.5 | overlap | 4 | 24 | 0 | 37.337 | 48.561 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 4 | 24 | 100 | 193.934 | 198.821 | 32.485 |
| hybrid | 0 | 0.5 | overlap | 4 | 24 | 300 | 359.362 | 377.229 | 52.657 |
| hybrid | 0 | 0.5 | overlap | 8 | 24 | 0 | 34.972 | 36.379 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 8 | 24 | 100 | 162.180 | 175.098 | 77.846 |
| hybrid | 0 | 0.5 | overlap | 8 | 24 | 300 | 275.195 | 319.800 | 144.464 |
```

`results/r3/anchor/copy_scheme_timing_summary.md` 全文：

```
| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| npu | 0 | 0.5 | overlap | 1 | 24 | 0 | 11.007 | 11.007 | 0.000 |
| npu | 0 | 0.5 | overlap | 1 | 24 | 300 | 138.970 | 138.970 | 33.987 |
| npu | 0 | 0.5 | overlap | 4 | 24 | 0 | 11.033 | 11.468 | 0.000 |
| npu | 0 | 0.5 | overlap | 4 | 24 | 300 | 256.536 | 278.526 | 76.696 |
| npu | 0 | 0.5 | overlap | 8 | 24 | 0 | 11.574 | 16.890 | 0.000 |
| npu | 0 | 0.5 | overlap | 8 | 24 | 300 | 222.595 | 238.419 | 170.740 |
```

三目录 `copy_scheme_run_manifest.json` 全文：

```json
w1: {"schema_version":2,"status":"passed","dtype":"c8","timestamp_utc":"2026-10-14T17:56:27.697103+00:00","visible_devices":"0,1,2,3,4,5,6,7","queue_depth":"default","case_files":[<48 files: cpu/hybrid × cards1,2,4,8 × copy0,100,300 × _r1,_r2>]}
w16: {"schema_version":2,"status":"passed","dtype":"c8","timestamp_utc":"2026-10-14T18:06:14.246201+00:00","visible_devices":"0,1,2,3,4,5,6,7","queue_depth":"default","case_files":[<48 files: 同 w1 命名>]}
anchor: {"schema_version":2,"status":"passed","dtype":"c8","timestamp_utc":"2026-10-14T18:15:57.596503+00:00","visible_devices":"0,1,2,3,4,5,6,7","queue_depth":"default","case_files":[<12 files: npu × cards1,4,8 × copy0,300 × _r1,_r2>]}
```

（manifest case_files 完整 48/48/12 清单见仓库 `results/r3/{w1,w16,anchor}/copy_scheme_run_manifest.json`，gitignore 不入库；文件名模式：w1/w16 为 `{cpu,hybrid}_cards{c}_bs24_copy{k}_rf0p0[_cf0p5_overlap]_r{r}.json`，anchor 为 `npu_cards{c}_bs24_copy{k}_rf0p0_r{r}.json`。）

4 个 case JSON 全文（看 phases 用）：

`results/r3/w1/cpu_cards1_bs24_copy100_rf0p0_r1.json`：

```json
{
  "schema_version": 2, "test": "a5_kvcache_copy_scheme_multiprocess", "status": "passed",
  "timestamp_utc": "2026-10-14T17:56:58.129522+00:00", "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1, "devices": [0], "same_seed": true,
  "config": {
    "dtype": "c8", "row_bytes": 656, "batch_size": 24, "source_len": 65536, "hbm_slots": 8192,
    "copy_min": 100, "copy_max": 100, "copy_cap": 16384, "warmup": 10, "iters": 1000, "seed": 7,
    "allow_non_a5": false, "scheme": "cpu", "run_frac": 0.0, "cpu_frac": 0.5, "hybrid_mode": "overlap",
    "cpu_threads": 8, "pretouch": false, "window": 1, "numa_nodes": ""
  },
  "summary": {"avg_us_mean": 181.7163899999999, "avg_us_max": 181.7163899999999,
    "avg_bandwidth": 8.664050612055417, "total_payload_bytes_per_iteration": 1574400,
    "copied_tokens_sum_per_iteration": 2400, "all_correct": true},
  "per_device": [
    {
      "schema_version": 2, "test": "a5_kvcache_copy_scheme_singlecard", "status": "passed",
      "timestamp_utc": "2026-10-14T17:56:55.335847+00:00", "device_count": 1,
      "config": {
        "device": "npu:0", "device_name": "Ascend950DT_9572", "dtype": "c8", "row_bytes": 656,
        "batch_size": 24, "source_len": 65536, "hbm_slots": 8192, "copy_min": 100, "copy_max": 100,
        "copy_cap": 16384, "warmup": 10, "iters": 1000, "seed": 7, "scheme": "cpu", "run_frac": 0.0,
        "cpu_frac": 0.5, "hybrid_mode": "overlap", "cpu_threads": 8, "pretouch": false,
        "staging_pinned": true, "window": 1, "queue_depth": 8
      },
      "workload": {"copy_counts": [100×24], "copied_tokens": 2400, "cpu_tokens": 0,
        "payload_bytes_per_iteration": 1574400},
      "correctness": {"data_exact": true, "guard_unchanged": true},
      "summary": {"cards": 1, "batch_size": 24, "copy_count": 100,
        "avg_us_mean": 181.7163899999999, "avg_us_max": 181.7163899999999,
        "avg_bandwidth": 8.664050612055417},
      "performance": {"timer": "perf_counter", "avg_us": 181.7163899999999, "avg_us_host_synced": null,
        "latency_us": {"mean": 181.7163899999999, "p50": 179.45, "p90": 196.57, "p99": 229.67,
          "min": 154.38, "max": 647.53, "n": 1000},
        "window": 1,
        "phases": {"cpu_gather_us": 46.09559999999996, "device_wall_us": 135.6207900000002,
          "device_event_us": 76.81902299076319, "device_overhead_us": 58.801767009237025}},
      "rank": 0, "logical_device_index": 0
    }
  ]
}
```

`results/r3/w16/cpu_cards1_bs24_copy100_rf0p0_r1.json`：

```json
{
  "schema_version": 2, "test": "a5_kvcache_copy_scheme_multiprocess", "status": "passed",
  "timestamp_utc": "2026-10-14T18:06:47.565361+00:00", "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1, "devices": [0], "same_seed": true,
  "config": {
    "dtype": "c8", "row_bytes": 656, "batch_size": 24, "source_len": 65536, "hbm_slots": 8192,
    "copy_min": 100, "copy_max": 100, "copy_cap": 16384, "warmup": 10, "iters": 1000, "seed": 7,
    "allow_non_a5": false, "scheme": "cpu", "run_frac": 0.0, "cpu_frac": 0.5, "hybrid_mode": "overlap",
    "cpu_threads": 8, "pretouch": false, "window": 16, "numa_nodes": ""
  },
  "summary": {"avg_us_mean": 86.71812000000014, "avg_us_max": 86.71812000000014,
    "avg_bandwidth": 18.155375139590173, "total_payload_bytes_per_iteration": 1574400,
    "copied_tokens_sum_per_iteration": 2400, "all_correct": true},
  "per_device": [
    {
      "schema_version": 2, "test": "a5_kvcache_copy_scheme_singlecard", "status": "passed",
      "timestamp_utc": "2026-10-14T18:06:44.721865+00:00", "device_count": 1,
      "config": {
        "device": "npu:0", "device_name": "Ascend950DT_9572", "dtype": "c8", "row_bytes": 656,
        "batch_size": 24, "source_len": 65536, "hbm_slots": 8192, "copy_min": 100, "copy_max": 100,
        "copy_cap": 16384, "warmup": 10, "iters": 1000, "seed": 7, "scheme": "cpu", "run_frac": 0.0,
        "cpu_frac": 0.5, "hybrid_mode": "overlap", "cpu_threads": 8, "pretouch": false,
        "staging_pinned": true, "window": 16, "queue_depth": 8
      },
      "workload": {"copy_counts": [100×24], "copied_tokens": 2400, "cpu_tokens": 0,
        "payload_bytes_per_iteration": 1574400},
      "correctness": {"data_exact": true, "guard_unchanged": true},
      "summary": {"cards": 1, "batch_size": 24, "copy_count": 100,
        "avg_us_mean": 86.71812000000014, "avg_us_max": 86.71812000000014,
        "avg_bandwidth": 18.155375139590173},
      "performance": {"timer": "perf_counter", "avg_us": 86.71812000000014, "avg_us_host_synced": null,
        "latency_us": {"mean": 86.71811999999981, "p50": 86.75125, "p90": 91.89875, "p99": 135.565,
          "min": 78.430625, "max": 135.565, "n": 1000},
        "window": 16,
        "phases": {"cpu_gather_us": 28.264360000000003, "device_wall_us": 58.45375999999999,
          "device_event_us": 52.43560868501663, "device_overhead_us": 6.018151314983355}},
      "rank": 0, "logical_device_index": 0
    }
  ]
}
```

`results/r3/w1/hybrid_cards1_bs24_copy100_rf0p0_cf0p5_overlap_r1.json`：

```json
{
  "schema_version": 2, "test": "a5_kvcache_copy_scheme_multiprocess", "status": "passed",
  "timestamp_utc": "2026-10-14T18:01:44.560236+00:00", "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1, "devices": [0], "same_seed": true,
  "config": {
    "dtype": "c8", "row_bytes": 656, "batch_size": 24, "source_len": 65536, "hbm_slots": 8192,
    "copy_min": 100, "copy_max": 100, "copy_cap": 16384, "warmup": 10, "iters": 1000, "seed": 7,
    "allow_non_a5": false, "scheme": "hybrid", "run_frac": 0.0, "cpu_frac": 0.5, "hybrid_mode": "overlap",
    "cpu_threads": 8, "pretouch": false, "window": 1, "numa_nodes": ""
  },
  "summary": {"avg_us_mean": 266.2583300000001, "avg_us_max": 266.2583300000001,
    "avg_bandwidth": 5.913054438522164, "total_payload_bytes_per_iteration": 1574400,
    "copied_tokens_sum_per_iteration": 2400, "all_correct": true},
  "per_device": [
    {
      "schema_version": 2, "test": "a5_kvcache_copy_scheme_singlecard", "status": "passed",
      "timestamp_utc": "2026-10-14T18:01:41.553346+00:00", "device_count": 1,
      "config": {
        "device": "npu:0", "device_name": "Ascend950DT_9572", "dtype": "c8", "row_bytes": 656,
        "batch_size": 24, "source_len": 65536, "hbm_slots": 8192, "copy_min": 100, "copy_max": 100,
        "copy_cap": 16384, "warmup": 10, "iters": 1000, "seed": 7, "scheme": "hybrid", "run_frac": 0.0,
        "cpu_frac": 0.5, "hybrid_mode": "overlap", "cpu_threads": 8, "pretouch": false,
        "staging_pinned": true, "window": 1, "queue_depth": 8
      },
      "workload": {"copy_counts": [100×24], "copied_tokens": 2400, "cpu_tokens": 1200,
        "payload_bytes_per_iteration": 1574400},
      "correctness": {"data_exact": true, "guard_unchanged": true, "zero_count_unchanged": true,
        "first_fill_capacity": true, "metadata_unchanged": true},
      "summary": {"cards": 1, "batch_size": 24, "copy_count": 100,
        "avg_us_mean": 266.2583300000001, "avg_us_max": 266.2583300000001,
        "avg_bandwidth": 5.913054438522164},
      "performance": {"timer": "perf_counter", "avg_us": 266.2583300000001, "avg_us_host_synced": null,
        "latency_us": {"mean": 266.2583300000002, "p50": 264.44, "p90": 280.36, "p99": 311.09,
          "min": 220.4, "max": 683.04, "n": 1000},
        "window": 1,
        "phases": {"launch_to_gather_done_us": 183.00110999999995, "h2d_scatter_tail_us": 83.25722000000016,
          "kernel_event_us": 182.72431115806103}},
      "rank": 0, "logical_device_index": 0
    }
  ]
}
```

`results/r3/w16/hybrid_cards1_bs24_copy100_rf0p0_cf0p5_overlap_r1.json`：

```json
{
  "schema_version": 2, "test": "a5_kvcache_copy_scheme_multiprocess", "status": "passed",
  "timestamp_utc": "2026-10-14T18:11:31.452317+00:00", "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1, "devices": [0], "same_seed": true,
  "config": {
    "dtype": "c8", "row_bytes": 656, "batch_size": 24, "source_len": 65536, "hbm_slots": 8192,
    "copy_min": 100, "copy_max": 100, "copy_cap": 16384, "warmup": 10, "iters": 1000, "seed": 7,
    "allow_non_a5": false, "scheme": "hybrid", "run_frac": 0.0, "cpu_frac": 0.5, "hybrid_mode": "overlap",
    "cpu_threads": 8, "pretouch": false, "window": 16, "numa_nodes": ""
  },
  "summary": {"avg_us_mean": 161.67691999999928, "avg_us_max": 161.67691999999928,
    "avg_bandwidth": 9.737939094831884, "total_payload_bytes_per_iteration": 1574400,
    "copied_tokens_sum_per_iteration": 2400, "all_correct": true},
  "per_device": [
    {
      "schema_version": 2, "test": "a5_kvcache_copy_scheme_singlecard", "status": "passed",
      "timestamp_utc": "2026-10-14T18:11:28.333248+00:00", "device_count": 1,
      "config": {
        "device": "npu:0", "device_name": "Ascend950DT_9572", "dtype": "c8", "row_bytes": 656,
        "batch_size": 24, "source_len": 65536, "hbm_slots": 8192, "copy_min": 100, "copy_max": 100,
        "copy_cap": 16384, "warmup": 10, "iters": 1000, "seed": 7, "scheme": "hybrid", "run_frac": 0.0,
        "cpu_frac": 0.5, "hybrid_mode": "overlap", "cpu_threads": 8, "pretouch": false,
        "staging_pinned": true, "window": 16, "queue_depth": 8
      },
      "workload": {"copy_counts": [100×24], "copied_tokens": 2400, "cpu_tokens": 1200,
        "payload_bytes_per_iteration": 1574400},
      "correctness": {"data_exact": true, "guard_unchanged": true, "zero_count_unchanged": true,
        "first_fill_capacity": true, "metadata_unchanged": true},
      "summary": {"cards": 1, "batch_size": 24, "copy_count": 100,
        "avg_us_mean": 161.67691999999928, "avg_us_max": 161.67691999999928,
        "avg_bandwidth": 9.737939094831884},
      "performance": {"timer": "perf_counter", "avg_us": 161.67691999999928, "avg_us_host_synced": null,
        "latency_us": {"mean": 161.67691999999892, "p50": 160.945625, "p90": 165.375625, "p99": 194.01625,
          "min": 153.176875, "max": 194.01625, "n": 1000},
        "window": 16,
        "phases": {"launch_to_gather_done_us": 156.25639999999999, "h2d_scatter_tail_us": 5.420520000000001,
          "kernel_event_us": 156.0201358795166}},
      "rank": 0, "logical_device_index": 0
    }
  ]
}
```

**结果文件**：宿主机 21 `/home/h2d_test/copy-scheme-bench/results/r3/{w1,w16,anchor}/`（各含 48/48/12 case JSON + manifest + summary + timing_summary.csv/md + 逐 case .log）；`results/` gitignore 未提交入库。
**观察**（只事实、不结论）：
- 主键对比（同坐标 avg_us_mean/带宽，repeat 折叠值，均 cards1/bs24/copy100 起算）：
  - cpu w1→w16：copy100 181.716→86.718µs（8.664→18.155 GB/s）；copy300 272.334→202.924µs（17.344→23.326 GB/s）；copy0 69.195→5.053µs。
  - cpu w16 带宽全坐标 > w1（cards8 copy100 53.384→138.021、copy300 106.944→151.735 GB/s）。
  - hybrid w1→w16：copy100 263.792→162.861µs（5.969→9.668 GB/s）；copy300 277.943→177.072µs（17.001→26.674 GB/s）；copy0 111.906→32.354µs。
- phases（cpu copy100 cards1，看 host 开销口径）：w1 cpu_gather 46.096µs + device_wall 135.621µs（其中 device_event 76.819、device_overhead 58.802）；w16 cpu_gather 28.264µs + device_wall 58.454µs（device_event 52.436、device_overhead 6.018）。未归类 host 开销（= avg_us − cpu_gather − device_wall）：w1 ≈ 0.000µs（0.0%）、w16 ≈ 0.000µs（0.0%）。
- hybrid phases（copy100 cards1）：w1 launch_to_gather_done 183.001µs + h2d_scatter_tail 83.257µs；w16 156.256µs + 5.421µs。
- R3-G3 逐坐标偏差（w1 vs §R2 cf0.5，%）：cpu cards1 -3.60/0.17/4.71、cards2 0.79/-2.75/11.18、cards4 8.28/13.42/5.17、cards8 -4.73/-1.28/3.30（copy0/100/300）；hybrid cards1 0.01/8.45/2.11、cards2 -2.57/6.77/-7.75、cards4 -1.69/-3.49/-5.77、cards8 -4.77/14.77/5.24。最大 14.77%。
- npu 锚点（同轮）：copy300 cards1 33.987/cards4 76.696/cards8 170.740 GB/s；copy0 11.0-11.6µs。
**异常**：无。

### 判读（§R3，2026-10-15，蓝区）

对照 §R3「判读预案」（派单时写死）逐条裁决（除注明外均为绿区**实测值**，
repeat 折叠后均值）：

**门槛**：R3-G1 ✓（38 项 OK）/ R3-G2 ✓（108 case 全 passed、correctness 全
true、window 分档正确）/ R3-G3 ✓（w1 对 R2 同坐标最大偏差 14.77% ≤15%）。

**口径修正（蓝区自我纠偏）**：§R2 判读备注的相位映射 `h2d_scatter_us ≡
device_wall_us` 不准确。R2 数据的数值证据给出正确映射：`h2d_scatter_us
(75.6) ≈ device_event_us (76.8)`（同坐标 w1，差 1.6%），`R2 未归类开销
(65.4) ≈ device_overhead_us (58.8)`（同一量级）——旧口径的「未归类」
主体是逐迭代同步等待，新口径已并入 device_wall 并以 device_overhead
单列（实测值互洽，非口径游戏）。

**裁决 1：host 压减有效（写死判据命中，超预期）**

- 判据「w16 未归类 host 开销占比 <10%」：w16 cpu cards1 copy100 的
  device_overhead=6.0µs，占 avg 86.7µs 的 **6.9% < 10%** ✓（w1 为
  58.8/181.7=32.4%）。
- copy0 纯固定开销（实测）：cpu 69.2/74.8/92.4/114.2µs（w1，cards1/2/4/8）
  → **5.1/5.2/5.9/6.6µs（w16）**，压缩 ~94%，已低于 npu launch 量级（~11µs）。
- 附带效应：gather 相位 46.1→28.3µs（w1→w16，同坐标）——去掉交错同步后
  host 侧 gather 本身也提速 ~39%（实测值；机制推测为线程调度/缓存连续性，
  标注为**推测**）。
- 延迟分布健康：w16 p99/p50=1.56（cpu copy100 cards1），无长尾恶化。

**裁决 2：S1 翻正未达成，但差距收敛到 0.88~0.89x**

- 写死判据「w16 cpu ≥ 同轮 npu 锚点（copy300, cards4/8）」：cards4
  67.4 < 76.7 GB/s（0.88x）；cards8 151.7 < 170.7 GB/s（0.89x）⇒ **未翻正**。
- 注意 cards4 锚点本轮 76.7 vs R2 65.7 vs R1 82.0 GB/s——cards4 档连续
  两轮漂移，该坐标证据弱；cards8 锚点稳定（168.5→170.7）。
- 趋势（实测）：w1→w16 后 cpu/npu 比从 0.53~0.84x 收敛到 0.88~0.89x；
  剩余差距主要在 device_event（H2D+scatter 实传段，52.4µs vs npu kernel
  全程 ~48.5µs/同 tokens 档——cpu 路径的 PCIe 大包 DMA + 设备侧 scatter
  两次写 vs kernel 直写一次，结构性多一遍）。

**裁决 3：S2 重开候选成立（cards4/8）**

- 写死判据「w16 hybrid < 同坐标 min(npu, w16 cpu)」（copy300）：cards1
  26.7 > 23.3 ✗；cards4 52.7 < 67.4 ✓；cards8 144.5 < 151.7 ✓ ⇒
  **候选成立（2/3 坐标）**，且 hybrid w16 的 h2d_scatter_tail 相位仅
  5.4µs（cards1 copy100）——overlap 在窗口化下真正藏住了 CPU 段。
- 按预案「下轮扫细 frac」执行，见 §R4。

**下一步**：R4 = hybrid 细 frac 扫描（w16，找最优分流点+能否过 npu）
+ pretouch/THP 查 w16 cpu gather 相位（28.3µs）的缺页/TLB 成分。
队列深度（npu 侧余量）顺延为 R5 候选。

---

## §R2-旧 派单：修复后重跑主矩阵（2026-10-15，蓝区）

### 目标

拿到 npu / cpu / hybrid 同轮完整的 60 case 主矩阵，支撑 S1/S2 裁决
（判据沿用 §R1「判读预案」，未移动）。

### 背景（蓝区已做的修复）

R1 崩溃根因：`copy=0` 时 staging 未分配但 `cpu_gather` 无条件使用（NoneType）。
修复：`cpu_gather` / `cpu_device_pass` 对本方案份额为空（`numel()==0`）时直接
返回；新增 stdlib 回归测试 `test_copy_zero_rows_are_empty_everywhere`。
蓝图仓不需要任何改动，**不需要重新 clone / apply / build**。

### 前置核验

1. 本仓 `git pull --ff-only` 后 `git log --oneline -1` 标题为
   "R2: 修复 cpu/hybrid 空份额崩溃 + §R1 判读 + §R2 派单"。
2. 蓝图仓保持 R1 状态：`git -C ../nanovllm-scatter_copy log --oneline -1` = `bb062d2`；
   工作区两个 M 文件仍在；`QUEUE_DEPTH = 8`；`_custom_opp_c8/` 构建产物仍在。
3. 环境变量无残留（同 §R1 前置核验第 5 条）。

### 执行命令

逐字执行（工作目录任意，脚本自定位；回归结果目录相对 cwd 解析）：

```bash
cd /home/h2d_test/copy-scheme-bench
git pull --ff-only && git log --oneline -1
cd tests && python3 test_scheme_tools.py && cd ..
# 定点回归：copy=0 在 cpu/hybrid 下必须不再崩溃（4 个 case）
bash run_scheme_sweep.sh --cards 1 --batch-size 24 --copy-count 0 100 \
  --schemes cpu hybrid --cpu-fracs 0.5 --iters 200 \
  --results-dir results/r2_regression
# 全量主矩阵（60 case；npu 12 坐标兼作跨轮一致性检查）
bash run_scheme_sweep.sh
```

### 通过标准

- R2-G1：自检末两行 `Ran 22 tests` / `OK`。
- R2-G2：回归 manifest `status=="passed"`；4 个 case JSON 全部 passed 且
  correctness 全 true；`cpu_cards1_bs24_copy0_rf0p0.log` 无 `AttributeError`。
- R2-G3：主矩阵 manifest `status=="passed"`，`copy_scheme_summary.json`
  `case_count==60`，每个 case JSON correctness 全 true。
- R2-G4（跨轮一致性，非验收门槛）：npu 12 坐标与同坐标 R1 值（见 §R1 交付
  附表）偏差 ≤15%；超出则原样回传并注明，不自行重跑调参。

### 回传格式

同 §R1：AGENTS.md 交付模板 + `copy_scheme_timing_summary.md` 全文 + manifest
全文 + 回归 4 个 JSON 全文；任何一步失败：日志末 30 行原文，停止后续步骤照常交付。

### 判读预案（派单时写死）

- S1/S2 判据沿用 §R1「判读预案」，逐字不变。
- R2-G2 失败 ⇒ 修复不完整，蓝区继续修；绿区只回传日志，不改代码。
- R2-G4 失败 ⇒ 环境漂移：npu 基线跨轮不可比，一切对比以 R2 轮内坐标为准。
- 补充裁决（由 R1 冒烟信号引出，写死）：若 `cpu` 全坐标 < `npu`，且
  `phases` 中既非 `cpu_gather_us` 也非 `h2d_scatter_us` 的未归类 host 开销
  （= avg_us − 两相位之和）占 `avg_us` >30% ⇒ 记 **S1 阴性（host 开销主导）**，
  下一步是先压 host 开销（减少 launch 次数/图捕获）再复试一次，
  而不是直接判 CPU 路径死刑。

### 交付（§R2，2026-10-15，绿区）

**执行环境**：机器 work21（141.61.33.21）openEuler aarch64；8× Ascend950DT_9572（可见设备 0-7）；宿主 root；CANN 9.2.0（/usr/local/Ascend/ascend-toolkit/latest）；时间 2026-10-14T16:5x–17:0xZ（回归 17:04Z、主矩阵 17:05Z 起）。
**前置核验**：逐条实际值——
1. 本仓 `git log --oneline -1` = `2d77dab R2: 修复 cpu/hybrid 空份额崩溃 + §R1 判读 + §R2 派单` ✓
2. 蓝图仓 `git -C ../nanovllm-scatter_copy log --oneline -1` = `bb062d2` ✓；工作区两 M 文件仍在 ✓；`QUEUE_DEPTH = 8` 计数 1 ✓；`_custom_opp_c8/` 构建产物（_custom_opp_c8/vendors 等）仍在 ✓
3. 环境变量无残留：四变量 grep 无匹配（RC=1）✓
**执行**：命令逐字执行，无偏差。`git pull --ff-only` 已是最新 `2d77dab`；自检 `test_scheme_tools.py` 22 tests OK；定点回归 `run_scheme_sweep.sh --cards 1 --batch-size 24 --copy-count 0 100 --schemes cpu hybrid --cpu-fracs 0.5 --iters 200 --results-dir results/r2_regression` 4 case 全 passed；全量主矩阵 `bash run_scheme_sweep.sh`（iters=1000 默认）60 case 全 passed。
**通过标准命中**：
- R2-G1 ✓：`Ran 22 tests` / `OK`，RC=0。
- R2-G2 ✓：回归 manifest `status=="passed"`；4 case JSON 全部 passed 且 correctness 全 true（cpu 两 case 合法字段集 {data_exact, guard_unchanged} 全 true；hybrid 两 case 5 字段全 true）；`cpu_cards1_bs24_copy0_rf0p0.log` 无 `AttributeError`。
- R2-G3 ✓：主矩阵 manifest `status=="passed"`；`copy_scheme_summary.json` `case_count==60`；60 case JSON 全部 passed、correctness 全 true（bad cases 0）。
- R2-G4 ✗（环境漂移，非验收门槛，未自行重跑调参）：npu 12 坐标对 §R1 交付附表偏差——cards1 copy100 32.493（0.48%）、copy300 33.997（0.16%）；cards2 63.563（2.59%）、65.515（3.72%）；cards4 **copy100 66.662（25.01%）**、**copy300 65.714（19.89%）**；cards8 179.363（0.41%）、168.492（3.70%）；copy0 全 0。cards4 档超 15% 阈值 ⇒ 按预案记环境漂移，npu 基线跨轮不可比，一切对比以 R2 轮内坐标为准。
**原始数据**：

`copy_scheme_timing_summary.md` 全文：

```
| scheme | run_frac | cpu_frac | hybrid_mode | cards | batch_size | copy_count | avg_us_mean | avg_us_max | avg_bandwidth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 0 | 71.781 | 71.781 | 0.000 |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 100 | 190.685 | 190.685 | 8.257 |
| cpu | 0 | 0.5 | overlap | 1 | 24 | 300 | 260.077 | 260.077 | 18.161 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 0 | 74.243 | 76.745 | 0.000 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 100 | 211.170 | 234.148 | 15.090 |
| cpu | 0 | 0.5 | overlap | 2 | 24 | 300 | 273.383 | 280.955 | 34.580 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 0 | 85.293 | 94.960 | 0.000 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 100 | 217.762 | 240.631 | 29.155 |
| cpu | 0 | 0.5 | overlap | 4 | 24 | 300 | 343.550 | 359.708 | 55.117 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 0 | 119.826 | 134.134 | 0.000 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 100 | 239.464 | 257.474 | 52.732 |
| cpu | 0 | 0.5 | overlap | 8 | 24 | 300 | 344.895 | 385.145 | 109.785 |
| hybrid | 0 | 0.25 | overlap | 1 | 24 | 0 | 107.145 | 107.145 | 0.000 |
| hybrid | 0 | 0.25 | overlap | 1 | 24 | 100 | 246.618 | 246.618 | 6.384 |
| hybrid | 0 | 0.25 | overlap | 1 | 24 | 300 | 246.763 | 246.763 | 19.141 |
| hybrid | 0 | 0.25 | overlap | 2 | 24 | 0 | 120.630 | 120.822 | 0.000 |
| hybrid | 0 | 0.25 | overlap | 2 | 24 | 100 | 234.544 | 247.660 | 13.467 |
| hybrid | 0 | 0.25 | overlap | 2 | 24 | 300 | 293.843 | 303.706 | 32.184 |
| hybrid | 0 | 0.25 | overlap | 4 | 24 | 0 | 122.324 | 124.675 | 0.000 |
| hybrid | 0 | 0.25 | overlap | 4 | 24 | 100 | 282.981 | 285.975 | 22.257 |
| hybrid | 0 | 0.25 | overlap | 4 | 24 | 300 | 336.862 | 374.488 | 57.278 |
| hybrid | 0 | 0.25 | overlap | 8 | 24 | 0 | 136.938 | 145.796 | 0.000 |
| hybrid | 0 | 0.25 | overlap | 8 | 24 | 100 | 269.347 | 304.514 | 46.940 |
| hybrid | 0 | 0.25 | overlap | 8 | 24 | 300 | 395.060 | 417.433 | 95.921 |
| hybrid | 0 | 0.5 | overlap | 1 | 24 | 0 | 111.891 | 111.891 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 1 | 24 | 100 | 243.247 | 243.247 | 6.472 |
| hybrid | 0 | 0.5 | overlap | 1 | 24 | 300 | 272.193 | 272.193 | 17.352 |
| hybrid | 0 | 0.5 | overlap | 2 | 24 | 0 | 120.706 | 121.577 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 2 | 24 | 100 | 254.040 | 262.082 | 12.407 |
| hybrid | 0 | 0.5 | overlap | 2 | 24 | 300 | 344.361 | 360.606 | 27.493 |
| hybrid | 0 | 0.5 | overlap | 4 | 24 | 0 | 123.525 | 132.205 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 4 | 24 | 100 | 307.483 | 315.025 | 20.495 |
| hybrid | 0 | 0.5 | overlap | 4 | 24 | 300 | 424.295 | 476.019 | 44.742 |
| hybrid | 0 | 0.5 | overlap | 8 | 24 | 0 | 152.927 | 184.405 | 0.000 |
| hybrid | 0 | 0.5 | overlap | 8 | 24 | 100 | 263.691 | 279.450 | 47.812 |
| hybrid | 0 | 0.5 | overlap | 8 | 24 | 300 | 398.678 | 423.074 | 95.088 |
| hybrid | 0 | 0.75 | overlap | 1 | 24 | 0 | 116.221 | 116.221 | 0.000 |
| hybrid | 0 | 0.75 | overlap | 1 | 24 | 100 | 254.717 | 254.717 | 6.181 |
| hybrid | 0 | 0.75 | overlap | 1 | 24 | 300 | 259.914 | 259.914 | 18.172 |
| hybrid | 0 | 0.75 | overlap | 2 | 24 | 0 | 120.895 | 126.559 | 0.000 |
| hybrid | 0 | 0.75 | overlap | 2 | 24 | 100 | 259.088 | 267.802 | 12.167 |
| hybrid | 0 | 0.75 | overlap | 2 | 24 | 300 | 338.421 | 340.603 | 27.914 |
| hybrid | 0 | 0.75 | overlap | 4 | 24 | 0 | 142.223 | 171.494 | 0.000 |
| hybrid | 0 | 0.75 | overlap | 4 | 24 | 100 | 274.167 | 289.801 | 23.037 |
| hybrid | 0 | 0.75 | overlap | 4 | 24 | 300 | 425.837 | 444.694 | 44.402 |
| hybrid | 0 | 0.75 | overlap | 8 | 24 | 0 | 151.150 | 164.536 | 0.000 |
| hybrid | 0 | 0.75 | overlap | 8 | 24 | 100 | 275.477 | 303.979 | 45.859 |
| hybrid | 0 | 0.75 | overlap | 8 | 24 | 300 | 406.986 | 445.485 | 93.451 |
| npu | 0 | 0.5 | overlap | 1 | 24 | 0 | 11.183 | 11.183 | 0.000 |
| npu | 0 | 0.5 | overlap | 1 | 24 | 100 | 48.454 | 48.454 | 32.493 |
| npu | 0 | 0.5 | overlap | 1 | 24 | 300 | 138.930 | 138.930 | 33.997 |
| npu | 0 | 0.5 | overlap | 2 | 24 | 0 | 9.720 | 11.436 | 0.000 |
| npu | 0 | 0.5 | overlap | 2 | 24 | 100 | 49.538 | 49.543 | 63.563 |
| npu | 0 | 0.5 | overlap | 2 | 24 | 300 | 144.189 | 144.742 | 65.515 |
| npu | 0 | 0.5 | overlap | 4 | 24 | 0 | 10.930 | 11.591 | 0.000 |
| npu | 0 | 0.5 | overlap | 4 | 24 | 100 | 97.069 | 105.666 | 66.662 |
| npu | 0 | 0.5 | overlap | 4 | 24 | 300 | 296.185 | 323.833 | 65.714 |
| npu | 0 | 0.5 | overlap | 8 | 24 | 0 | 10.876 | 11.952 | 0.000 |
| npu | 0 | 0.5 | overlap | 8 | 24 | 100 | 70.257 | 72.149 | 179.363 |
| npu | 0 | 0.5 | overlap | 8 | 24 | 300 | 224.450 | 236.431 | 168.492 |
```

主矩阵 `copy_scheme_run_manifest.json` 全文：

```json
{
  "schema_version": 2,
  "status": "passed",
  "dtype": "c8",
  "timestamp_utc": "2026-10-14T17:05:41.312631+00:00",
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

回归 4 case JSON 全文：

`results/r2_regression/cpu_cards1_bs24_copy0_rf0p0.json`：

```json
{
  "schema_version": 2, "test": "a5_kvcache_copy_scheme_multiprocess", "status": "passed",
  "timestamp_utc": "2026-10-14T17:04:10.182857+00:00", "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1, "devices": [0], "same_seed": true,
  "config": {
    "dtype": "c8", "row_bytes": 656, "batch_size": 24, "source_len": 65536, "hbm_slots": 8192,
    "copy_min": 0, "copy_max": 0, "copy_cap": 16384, "warmup": 10, "iters": 200, "seed": 7,
    "allow_non_a5": false, "scheme": "cpu", "run_frac": 0.0, "cpu_frac": 0.5, "hybrid_mode": "overlap",
    "cpu_threads": 8, "pretouch": false, "numa_nodes": ""
  },
  "summary": {"avg_us_mean": 68.50475, "avg_us_max": 68.50475, "avg_bandwidth": 0.0,
    "total_payload_bytes_per_iteration": 0, "copied_tokens_sum_per_iteration": 0, "all_correct": true},
  "per_device": [
    {
      "schema_version": 2, "test": "a5_kvcache_copy_scheme_singlecard", "status": "passed",
      "timestamp_utc": "2026-10-14T17:04:08.166364+00:00", "device_count": 1,
      "config": {
        "device": "npu:0", "device_name": "Ascend950DT_9572", "dtype": "c8", "row_bytes": 656,
        "batch_size": 24, "source_len": 65536, "hbm_slots": 8192, "copy_min": 0, "copy_max": 0,
        "copy_cap": 16384, "warmup": 10, "iters": 200, "seed": 7, "scheme": "cpu", "run_frac": 0.0,
        "cpu_frac": 0.5, "hybrid_mode": "overlap", "cpu_threads": 8, "pretouch": false,
        "staging_pinned": false, "queue_depth": 8
      },
      "workload": {"copy_counts": [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        "copied_tokens": 0, "cpu_tokens": 0, "payload_bytes_per_iteration": 0},
      "correctness": {"data_exact": true, "guard_unchanged": true},
      "summary": {"cards": 1, "batch_size": 24, "copy_count": 0,
        "avg_us_mean": 68.50475, "avg_us_max": 68.50475, "avg_bandwidth": 0.0},
      "performance": {"timer": "perf_counter", "avg_us": 68.50475, "avg_us_host_synced": null,
        "phases": {"cpu_gather_us": 0.2672, "h2d_scatter_us": 11.325885022524744}},
      "rank": 0, "logical_device_index": 0
    }
  ]
}
```

`results/r2_regression/cpu_cards1_bs24_copy100_rf0p0.json`：

```json
{
  "schema_version": 2, "test": "a5_kvcache_copy_scheme_multiprocess", "status": "passed",
  "timestamp_utc": "2026-10-14T17:04:21.608988+00:00", "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1, "devices": [0], "same_seed": true,
  "config": {
    "dtype": "c8", "row_bytes": 656, "batch_size": 24, "source_len": 65536, "hbm_slots": 8192,
    "copy_min": 100, "copy_max": 100, "copy_cap": 16384, "warmup": 10, "iters": 200, "seed": 7,
    "allow_non_a5": false, "scheme": "cpu", "run_frac": 0.0, "cpu_frac": 0.5, "hybrid_mode": "overlap",
    "cpu_threads": 8, "pretouch": false, "numa_nodes": ""
  },
  "summary": {"avg_us_mean": 187.58935, "avg_us_max": 187.58935, "avg_bandwidth": 8.392800550777537,
    "total_payload_bytes_per_iteration": 1574400, "copied_tokens_sum_per_iteration": 2400, "all_correct": true},
  "per_device": [
    {
      "schema_version": 2, "test": "a5_kvcache_copy_scheme_singlecard", "status": "passed",
      "timestamp_utc": "2026-10-14T17:04:18.616613+00:00", "device_count": 1,
      "config": {
        "device": "npu:0", "device_name": "Ascend950DT_9572", "dtype": "c8", "row_bytes": 656,
        "batch_size": 24, "source_len": 65536, "hbm_slots": 8192, "copy_min": 100, "copy_max": 100,
        "copy_cap": 16384, "warmup": 10, "iters": 200, "seed": 7, "scheme": "cpu", "run_frac": 0.0,
        "cpu_frac": 0.5, "hybrid_mode": "overlap", "cpu_threads": 8, "pretouch": false,
        "staging_pinned": true, "queue_depth": 8
      },
      "workload": {"copy_counts": [100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100],
        "copied_tokens": 2400, "cpu_tokens": 0, "payload_bytes_per_iteration": 1574400},
      "correctness": {"data_exact": true, "guard_unchanged": true},
      "summary": {"cards": 1, "batch_size": 24, "copy_count": 100,
        "avg_us_mean": 187.58935, "avg_us_max": 187.58935, "avg_bandwidth": 8.392800550777537},
      "performance": {"timer": "perf_counter", "avg_us": 187.58935, "avg_us_host_synced": null,
        "phases": {"cpu_gather_us": 46.533449999999995, "h2d_scatter_us": 75.64373468980193}},
      "rank": 0, "logical_device_index": 0
    }
  ]
}
```

`results/r2_regression/hybrid_cards1_bs24_copy0_rf0p0_cf0p5_overlap.json`：

```json
{
  "schema_version": 2, "test": "a5_kvcache_copy_scheme_multiprocess", "status": "passed",
  "timestamp_utc": "2026-10-14T17:04:33.057827+00:00", "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1, "devices": [0], "same_seed": true,
  "config": {
    "dtype": "c8", "row_bytes": 656, "batch_size": 24, "source_len": 65536, "hbm_slots": 8192,
    "copy_min": 0, "copy_max": 0, "copy_cap": 16384, "warmup": 10, "iters": 200, "seed": 7,
    "allow_non_a5": false, "scheme": "hybrid", "run_frac": 0.0, "cpu_frac": 0.5, "hybrid_mode": "overlap",
    "cpu_threads": 8, "pretouch": false, "numa_nodes": ""
  },
  "summary": {"avg_us_mean": 109.968, "avg_us_max": 109.968, "avg_bandwidth": 0.0,
    "total_payload_bytes_per_iteration": 0, "copied_tokens_sum_per_iteration": 0, "all_correct": true},
  "per_device": [
    {
      "schema_version": 2, "test": "a5_kvcache_copy_scheme_singlecard", "status": "passed",
      "timestamp_utc": "2026-10-14T17:04:30.749097+00:00", "device_count": 1,
      "config": {
        "device": "npu:0", "device_name": "Ascend950DT_9572", "dtype": "c8", "row_bytes": 656,
        "batch_size": 24, "source_len": 65536, "hbm_slots": 8192, "copy_min": 0, "copy_max": 0,
        "copy_cap": 16384, "warmup": 10, "iters": 200, "seed": 7, "scheme": "hybrid", "run_frac": 0.0,
        "cpu_frac": 0.5, "hybrid_mode": "overlap", "cpu_threads": 8, "pretouch": false,
        "staging_pinned": false, "queue_depth": 8
      },
      "workload": {"copy_counts": [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        "copied_tokens": 0, "cpu_tokens": 0, "payload_bytes_per_iteration": 0},
      "correctness": {"data_exact": true, "guard_unchanged": true,
        "zero_count_unchanged": true, "first_fill_capacity": true, "metadata_unchanged": true},
      "summary": {"cards": 1, "batch_size": 24, "copy_count": 0,
        "avg_us_mean": 109.968, "avg_us_max": 109.968, "avg_bandwidth": 0.0},
      "performance": {"timer": "perf_counter", "avg_us": 109.968, "avg_us_host_synced": null,
        "phases": {"launch_to_gather_done_us": 30.65945, "kernel_event_us": 43.357339981012046}},
      "rank": 0, "logical_device_index": 0
    }
  ]
}
```

`results/r2_regression/hybrid_cards1_bs24_copy100_rf0p0_cf0p5_overlap.json`：

```json
{
  "schema_version": 2, "test": "a5_kvcache_copy_scheme_multiprocess", "status": "passed",
  "timestamp_utc": "2026-10-14T17:04:44.497010+00:00", "visible_devices": "0,1,2,3,4,5,6,7",
  "device_count": 1, "devices": [0], "same_seed": true,
  "config": {
    "dtype": "c8", "row_bytes": 656, "batch_size": 24, "source_len": 65536, "hbm_slots": 8192,
    "copy_min": 100, "copy_max": 100, "copy_cap": 16384, "warmup": 10, "iters": 200, "seed": 7,
    "allow_non_a5": false, "scheme": "hybrid", "run_frac": 0.0, "cpu_frac": 0.5, "hybrid_mode": "overlap",
    "cpu_threads": 8, "pretouch": false, "numa_nodes": ""
  },
  "summary": {"avg_us_mean": 257.27655, "avg_us_max": 257.27655, "avg_bandwidth": 6.119485044400665,
    "total_payload_bytes_per_iteration": 1574400, "copied_tokens_sum_per_iteration": 2400, "all_correct": true},
  "per_device": [
    {
      "schema_version": 2, "test": "a5_kvcache_copy_scheme_singlecard", "status": "passed",
      "timestamp_utc": "2026-10-14T17:04:42.268927+00:00", "device_count": 1,
      "config": {
        "device": "npu:0", "device_name": "Ascend950DT_9572", "dtype": "c8", "row_bytes": 656,
        "batch_size": 24, "source_len": 65536, "hbm_slots": 8192, "copy_min": 100, "copy_max": 100,
        "copy_cap": 16384, "warmup": 10, "iters": 200, "seed": 7, "scheme": "hybrid", "run_frac": 0.0,
        "cpu_frac": 0.5, "hybrid_mode": "overlap", "cpu_threads": 8, "pretouch": false,
        "staging_pinned": true, "queue_depth": 8
      },
      "workload": {"copy_counts": [100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100],
        "copied_tokens": 2400, "cpu_tokens": 1200, "payload_bytes_per_iteration": 1574400},
      "correctness": {"data_exact": true, "guard_unchanged": true,
        "zero_count_unchanged": true, "first_fill_capacity": true, "metadata_unchanged": true},
      "summary": {"cards": 1, "batch_size": 24, "copy_count": 100,
        "avg_us_mean": 257.27655, "avg_us_max": 257.27655, "avg_bandwidth": 6.119485044400665},
      "performance": {"timer": "perf_counter", "avg_us": 257.27655, "avg_us_host_synced": null,
        "phases": {"launch_to_gather_done_us": 86.87589999999999, "kernel_event_us": 175.21119460463524}},
      "rank": 0, "logical_device_index": 0
    }
  ]
}
```

**结果文件**：`results/copy_scheme_a5_c8/`（主矩阵 60 case + manifest + summary + timing_summary.csv/md）与 `results/r2_regression/`（回归 4 case + manifest + summary + csv）均在宿主机 21；`results/` 已 gitignore，未提交入库。
**观察**（只事实、不结论）：
- 主矩阵 60 case 全 passed、correctness 全 true，含此前 §R1 崩溃的 cpu×copy0 坐标（修复后不再 AttributeError）。
- npu 档 cards1/2/8 与 §R1 偏差 ≤3.72%，cards4 档偏差 25.01%/19.89% 超 15%（见 R2-G4）。
- cpu 档 copy100/copy300 单卡 8.257/18.161 GB/s；cards8 52.732/109.785 GB/s。hybrid 档 cf 三档单卡 6.2-6.5/17.4-19.1 GB/s。
- 回归 cpu copy0：avg_us 68.505µs，phases cpu_gather 0.267µs + h2d_scatter 11.326µs，未归类 host 开销 ≈ 68.505 − 0.267 − 11.326 = 56.912µs（占 83.1%）；cpu copy100：avg_us 187.589µs，cpu_gather 46.533µs + h2d_scatter 75.644µs，未归类 host 开销 ≈ 65.412µs（占 34.9%）。
**异常**：无。

### 判读（§R2，2026-10-15，蓝区）

对照 §R1「判读预案」与 §R2「判读预案」逐条裁决（除注明外均为绿区**实测值**）：

**门槛**

- R2-G1 ✓ / R2-G2 ✓ / R2-G3 ✓：自检、回归（含 R1 崩溃坐标 cpu×copy0，
  修复生效）、主矩阵 60 case 全 passed、correctness 全 true。
- R2-G4 ✗（非门槛）：npu cards4 两坐标偏差 25.01%/19.89% > 15% ⇒ 按预案记
  **环境漂移**，npu 基线跨轮不可比，一切对比以 R2 轮内坐标为准；cards1/2/8
  偏差 ≤3.72%，与 R1 互洽。

**S1 裁决：阴性（host 开销主导）——按预案不判死刑，先压 host 开销再复试**

- cpu 在 copy300 全 cards 坐标 < npu（GB/s，轮内实测）：cards1 18.2/34.0、
  cards2 34.6/65.5、cards4 55.1/65.7、cards8 109.8/168.5。S1 阳性条件不满足。
- 分支判据命中「host 开销主导」（§R2 补充判据）：回归同坐标（cards1/bs24）
  cpu copy100 的未归类 host 开销 = 187.6 − 46.5(gather) − 75.6(h2d) ≈
  **65.4µs，占 34.9% > 30%**；copy0 时 avg=68.5µs 中未归类 **56.9µs（83.1%）**
  ——零负载下仍存在的纯固定开销，与 R1 冒烟估算（~72µs/37%）互洽。
- 固定开销随 die 数上涨（主矩阵 cpu copy0：71.8/74.2/85.3/119.8µs，
  cards1/2/4/8；npu copy0 ≈11µs 不涨）⇒ 开销主体是每迭代 host 侧
  launch/sync 串行成本，不是搬运本身。
- 边际成本（模型反推值，(T(copy)−T0)/tokens）：cpu 26.2/27.7/35.9/31.3
  ns/token，npu 17.7/18.7/39.6/29.7（cards1/2/4/8）——**cards4/8 时两者
  边际已持平**，cpu 的净输在固定开销。压掉固定开销后 cpu 路径在高 die 数
  坐标有翻正可能，这正是复试要验证的。

**S2 裁决：阳性候选不成立**

- hybrid(overlap) 无任何坐标 < min(npu, cpu)（copy300 最好坐标
  cards4/cf0.25=336.9µs vs 同坐标 npu 296.2µs）；多数坐标 hybrid 甚至
  差于两个父方案（如 cards2 copy300：293.8 vs cpu 273.4）。
- hybrid copy0 固定开销 107~152µs，高于 cpu 的 68~120µs——双流结构本身
  再加一层 host 开销。结论：当前实现形态下 overlap 不藏反伤；host 开销
  压减后是否复测 hybrid 由复试数据决定。

**下一步（按 §R2 预案写死的分支执行）**

S1 阴性（host 开销主导）⇒ R3 = **压 host 开销（窗口化流水：每窗口 N 次
迭代共享一次同步，消除每迭代全设备同步）+ cpu/hybrid 同坐标复试**。
判读口径备忘：R2 数据相位名 `h2d_scatter_us` ≡ 合并后代码的
`device_wall_us`；跨轮比较只对 R2 轮内坐标做。

---

## §R1-旧 派单：A5 首轮主矩阵（2026-10-14，蓝区）

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

### 判读（§R1，2026-10-15，蓝区）

对照 §R1「通过标准」与「判读预案」逐条裁决（数据均为绿区**实测值**）：

- G1 ✓ / G2 ✓ / G3 ✓ / G4 ✓：构建、补丁、自检、冒烟全过（绿区实测，冒烟两
  case 字节级正确性全 true）。冒烟两 case 坐标一致（cards1/bs24/copy100），
  同轮可比。
- G5 ✗ ⇒ 按预案「数据缺失 ⇒ 本轮无效」裁决：**R1 主矩阵目标无效**。根因是
  蓝区脚本缺陷（`cpu_gather`/`cpu_device_pass` 未处理空份额，copy=0 触发
  NoneType），非被测对象问题；修复与回归开关已随 §R2 下发。
- 已完成的 12 个 npu case correctness 全 true、冒烟与主矩阵同坐标一致
  （32.485 vs 32.649 GB/s，偏差 0.5%）、G6 与该机历史曲线同量级
  ⇒ **npu 基线 12 坐标有效落袋**（实测值）：
  cards1 32.6/34.1，cards2 65.3/68.0，cards4 88.9/82.0，cards8 178.6/175.0
  GB/s（copy100/copy300）；copy0 纯 launch 开销 ~11µs。
- S1/S2 主裁决：**顺延至 R2**（cpu/hybrid 本轮无数据，不裁决）。

观察（事实，非裁决，供 R2 后对照）：

- 多 die 聚合亚线性：1→2 die 线性（32.6→65.3 GB/s），2→4 die 仅 1.36×，
  单 die 速率从 34 跌至 ~21 GB/s（copy300）⇒ ≥4 die 时共享链路出现竞争
  （实测值）。这强化了换路径/分流的动机；R2 中 cpu/hybrid 在 cards4/8 的
  表现是最关键坐标。
- 冒烟同坐标：cpu 192.4µs vs npu 48.5µs（event）/ 75.6µs（synced 墙钟）。
  cpu 的 `cpu_gather_us`=47.9µs/2400 行 ≈ 20.0ns/行，与 npu kernel 的
  20.2ns/行持平；差距在 `h2d_scatter_us`=72.4µs 与未归类 host 开销 ~72µs
  （占 avg_us 的 37%）（实测值；host 开销为 avg_us 减两相位的**模型反推值**）。
  ⇒ §R2 判读预案已补充「host 开销主导」分支。
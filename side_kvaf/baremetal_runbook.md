# A5 空环境从零搭建：KVAF(URMA) vs KSC(PCIe) H2D 带宽对比 runbook

目标：同一台 A5、同会话，测两条搬运路径的 656B/token 有效 H2D 带宽。
坐标写死：batch-size 24 × 每请求搬运 {300, 2048} token（每迭代 payload 4.7 MB / 32.2 MB）。
不需要 docker、不需要装 vLLM。每个阶段开头有 Go/No-Go 检查，卡住就停、把输出贴回来。

约定：下文 `<BASE>` = 你放代码的目录，建议 `/home/$USER/ab_test`：

```bash
export BASE=/home/$USER/ab_test && mkdir -p $BASE && cd $BASE
```

---

## 阶段 0：Go/No-Go 核验（5 分钟，不过就别往下走）

```bash
uname -m                                  # 期望 aarch64
cat /etc/os-release | head -3
npu-smi info | head -20                   # 期望看到 8×Ascend950；没有 => 驱动没装,停
ls /dev/davinci* | head                   # 期望 davinci0..7 + davinci_manager
ls /usr/local/Ascend/                     # 看有没有 cann / ascend-toolkit
python3.11 --version || python3 --version # 期望 3.11.x
ls /dev/uburma                            # 【KVAF 生死线】不存在 => KVAF 侧在这台机器跑不了
ldconfig -p 2>/dev/null | grep -i urma || find /usr -name "liburma.so*" 2>/dev/null | head -3
curl -sI https://github.com -o /dev/null -w "github:%{http_code}\n" --max-time 10
curl -sI https://gitcode.com -o /dev/null -w "gitcode:%{http_code}\n" --max-time 10
curl -sI https://pypi.org -o /dev/null -w "pypi:%{http_code}\n" --max-time 10
```

判读：
- `/dev/davinci*` 没有 → NPU 驱动未装，超出手册范围，找机器管理员。
- `/dev/uburma` 或 `liburma.so` 没有 → **KVAF 侧无法在这台机器测**（UB/URMA 是硬依赖，装不了就换有 UB 的机器；KSC 侧仍可测）。
- 不出网 → 需要离线包/内部镜像，把缺什么列出来贴回来。
- CANN 目录不存在 → 阶段 1 装；存在则跳过安装只做 source。

---

## 阶段 1：基础软件（CANN + python 包）

### 1.1 CANN 9.1（已有则跳过安装）

```bash
# 从内部镜像或官网拿 aarch64 toolkit 包，文件名形如：
#   Ascend-cann-toolkit_9.1.0_linux-aarch64.run
# 无 root 就装到 home：
bash Ascend-cann-toolkit_9.1.0_linux-aarch64.run --quiet --install-path=$HOME/Ascend
# 有 root 建议装标准路径 /usr/local/Ascend（后续脚本默认找这里）
```

装完验证：

```bash
export ASCEND_HOME_PATH=/usr/local/Ascend/cann    # 装 home 则改为 $HOME/Ascend/cann
[ -d "$ASCEND_HOME_PATH" ] || export ASCEND_HOME_PATH=$(dirname $(find /usr/local/Ascend $HOME/Ascend -maxdepth 2 -name set_env.sh 2>/dev/null | head -1))
source "$ASCEND_HOME_PATH/set_env.sh"
which msopgen && echo CANN-OK    # 后面编译算子要用 msopgen
```

### 1.2 python 3.11 + torch/torch-npu

```bash
# openEuler 24.03:
sudo dnf install -y python3.11 python3.11-pip 2>/dev/null || true
python3.11 -m venv ~/venv-a5 && source ~/venv-a5/bin/activate
pip install --upgrade pip
pip install torch==2.10.0
pip install torch-npu==2.10.0.post2
python3 -c "import torch, torch_npu; print(torch.__version__, torch_npu.__version__); torch.npu.set_device(0); print('NPU-OK')"
```

`NPU-OK` 打不出来就停，贴报错。

---

## 阶段 2：拉代码（三个仓）

```bash
cd $BASE
git clone -b scatter_copy_a5_c8 https://github.com/xieqiang-hw/nanovllm-DSA-offload_scatter_copy.git nanovllm-scatter_copy
git clone https://github.com/JiJiaF1020/DSA-offload-KVAF-mtp_xzw_0903.git dsa-kvaf
git clone -b ak_mtp_yq --single-branch https://gitcode.com/CacheOS/KVAF.git KVAF
# gitcode 若要鉴权：GIT_TERMINAL_PROMPT=0 git -c 'credential.helper=!f() { printf "username=%s\npassword=%s\n" "$GITCODE_USERNAME" "$GITCODE_KEY"; }; f' clone -b ak_mtp_yq --single-branch https://gitcode.com/CacheOS/KVAF.git KVAF
```

---

## 阶段 3：KSC 侧（PCIe）构建 + 测量

```bash
cd $BASE/nanovllm-scatter_copy
unset ASCEND_CUSTOM_OPP_PATH NANOVLLM_CUST_OPAPI_LIB NANOVLLM_A5_INSTALL_OPP_PATH
source "$ASCEND_HOME_PATH/set_env.sh"
export A5_SOC_VERSION=ascend950 NANOVLLM_A5_OPS_BUILD_JOBS=$(nproc)
export PYTHONPATH=$PWD/torch_extension:$PYTHONPATH
bash build_c8.sh
# 通过标准：末尾打印 "[c8_build] torch extension import: OK"
```

测量（两点，每点几分钟）：

```bash
export ASCEND_RT_VISIBLE_DEVICES=0
for CC in 300 2048; do
python3 tests/test_kvcache_scatter_copy.py --device npu:0 \
  --batch-size 24 --copy-count $CC \
  --source-len 65536 --hbm-slots 8192 --warmup 10 --iters 500 \
  --json-output results/ab_ksc_bs24_copy$CC.json 2>&1 | tee results/ab_ksc_bs24_copy$CC.log
done
```

取数：日志末尾六列表的 `avg_bandwidth`（十进制 GB/s）。正确性门槛：日志含 `ok=1` 与 `A5_KVCACHE_SCATTER_COPY_C8_UT_OK`。

---

## 阶段 4：KVAF 侧（URMA）构建 + 起 CPU service

### 4.1 构建 KVAF CPU + NPU Runtime

```bash
cd $BASE/dsa-kvaf
cat > .env <<EOF
KVAF_ROOT=$BASE/KVAF
KVAF_GIT_BRANCH=ak_mtp_yq
KVAF_CANN_PATH=$ASCEND_HOME_PATH
KVAF_NPU_BUILD_DIR=$BASE/KVAF/build-npu
KVAF_CPU_BUILD_DIR=$BASE/KVAF/build-cpu
EOF
bash scripts/a5_dsa_install_kvaf.sh cpu   # 产物: $BASE/KVAF/build-cpu/runtime/kvaf_cpu_service
bash scripts/a5_dsa_install_kvaf.sh npu   # 产物: build-npu/bin/*.o + build-npu/python/kvaf/
# npu 构建末尾会自检 binding（NpuRuntime/link_to/scalar miss_count ABI），报错就停
```

### 4.2 构建 standalone DSA registration（KVAF bench 的 Prepare 算子）

```bash
cd $BASE/dsa-kvaf/csrc/attention/nanovllm_a5_ops
source "$ASCEND_HOME_PATH/set_env.sh"
export A5_SOC_VERSION=ascend950 NANOVLLM_A5_OPS_BUILD_JOBS=$(nproc)
bash build_nanovllm_ops.sh
export PYTHONPATH=$PWD/torch_extension:$PYTHONPATH
python3 -c "import torch, torch_npu; import nanovllm_dsa_a5; print(hasattr(torch.ops.nanovllm_dsa,'kvaf_batch_get_prepare_out'))"
# 期望 True
```

### 4.3 起 KVAF CPU service（常驻，另开一个终端或 nohup）

```bash
cd $BASE/dsa-kvaf
nohup bash scripts/a5_dsa_kvaf_cpu_service.sh > kvaf_cpu_service.log 2>&1 &
sleep 5
ss -ltnp | grep 28999   # 看到监听即 OK
```

---

## 阶段 5：KVAF 侧测量

```bash
cd $BASE/dsa-kvaf/csrc/attention/nanovllm_a5_ops/tests
source ~/venv-a5/bin/activate
export PYTHONPATH=$BASE/KVAF/build-npu/python:$BASE/dsa-kvaf/csrc/attention/nanovllm_a5_ops/torch_extension:$PYTHONPATH
export ASCEND_RT_VISIBLE_DEVICES=0

for MC in 300 2048; do
python3 benchmark_kvaf_batch_get.py --device npu:0 --batch-size 24 \
  --miss-count $MC --qcap 64 --warmup 20 --iters 500 \
  --batch-get-kernel $BASE/KVAF/build-npu/bin/kvaf_execute_batch_get_kernels.o \
  --batch-put-kernel $BASE/KVAF/build-npu/bin/kvaf_execute_batch_put_kernels.o \
  --cpu-service-addr 127.0.0.1:28999 \
  2>&1 | tee kvaf_ab_bs24_miss$MC.log
done
```

取数：
- 正确性门槛：日志含 `KVAF_SUBGRAPH_C_BENCHMARK_CORRECTNESS ok=1`。
- 主指标：`operation=batch_get_npu_event ... payload_gibps=X.XXX`，**×1.0737 换成十进制 GB/s**。
- 副指标：`batch_get_call_to_stream_completion` 的 payload_gibps（host 墙钟口径）。

## 阶段 6：防漂移复跑

按上面 KSC 的命令再跑一遍两点。两遍同坐标差 >5% 说明机器在漂，数据标注后慎用。

---

## 回报模板（贴回这六项 + 所有 config 行）

| 坐标 | KSC avg_bandwidth (GB/s) | KSC 复跑 | KVAF payload_gibps (GiB/s) | KVAF×1.0737 (GB/s) | 比值 |
|---|---|---|---|---|---|
| bs24 × 300 | | | | | |
| bs24 × 2048 | | | | | |

判读口径（事先写死）：比值 ≥1.2 → URMA 优势实锤；0.8~1.2 → 同档，带宽不是决策变量；≤0.8 → KVAF 劣势，加跑 `benchmark_lidu_fused_batch_get.py` 看 post/transfer_window 分解定位。

## 常见卡点速查

- `msopgen not found` → CANN 没 source 或没装 toolkit（只有 runtime 不够）。
- KVAF npu 构建报 `CANN path is absent` → `.env` 里 KVAF_CANN_PATH 指错。
- gitcode clone 401/403 → 需要 GITCODE_USERNAME/GITCODE_KEY。
- bench 报 `KVAF CPU service is unreachable` → 4.3 的 service 没起来，看 kvaf_cpu_service.log。
- `import kvaf` 找不到 → PYTHONPATH 没含 `$BASE/KVAF/build-npu/python`。
- 任一处 correctness 失败 → 该点数据无效，照常把日志贴回来。

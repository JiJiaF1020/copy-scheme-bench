# A5 空环境：URMA(KVAF BatchGet)带宽极限测试 runbook

目标：测 UB/URMA 路径 DDR→HBM 的**有效带宽极限**（UDMA 引擎，656B/token 口径）。
bench 为蓝区自研 `side_kvaf/urma_ceiling_bench.py`，只依赖 KVAF NPU binding，
**不需要** 0903 仓、vLLM、DSA 算子、docker。

## 依赖边界（什么东西从哪来）

| 内容 | 来源 | 公开? |
|---|---|---|
| 本手册 + bench 脚本 | `copy-scheme-bench`（github） | 公开 |
| torch 2.10.0 / torch-npu 2.10.0.post2 | pypi | 公开 |
| CANN 9.1 toolkit(.run 安装包） | 内部镜像/官网 | 公开但体积大，不入仓 |
| KVAF 运行时源码（ak_mtp_yq 分支） | gitcode `CacheOS/KVAF` | **私有**，需凭据 clone 或用户直接放 tarball 到机器上 |

除 KVAF 源码供给外全链路自包含。KVAF 是第三方私有代码，**不要**拷进公开仓。

约定 `<BASE>` 为工作目录：

```bash
export BASE=/home/$USER/urma_test && mkdir -p $BASE && cd $BASE
```

---

## 阶段 0：Go/No-Go 核验（逐条原文回传）

```bash
uname -m                                  # 期望 aarch64
npu-smi info | head -20                   # 8×Ascend950；没有 => 驱动没装,停
ls /dev/davinci* | head
ls /usr/local/Ascend/ 2>/dev/null || ls $HOME/Ascend/ 2>/dev/null
ls /dev/uburma                            # 【生死线】没有 => URMA 路径不存在,停
ldconfig -p 2>/dev/null | grep -i urma || find /usr -name "liburma.so*" 2>/dev/null | head -3
python3.11 --version || python3 --version
curl -sI https://pypi.org -o /dev/null -w "pypi:%{http_code}\n" --max-time 10
# KVAF 供给方式二选一，确认哪种可行：
#   a) gitcode 凭据 clone: GIT_TERMINAL_PROMPT=0 git ls-remote https://gitcode.com/CacheOS/KVAF.git
#   b) 用户已把 KVAF tarball 放到机器上: ls <tarball路径>
```

判读：`/dev/davinci*` 缺 → 找管理员装驱动；`/dev/uburma` 或 `liburma.so` 缺 →
本机测不了 URMA，停；pypi 不通 → 需要离线 wheel；KVAF 两种供给都不通 → 停，
向蓝区要供给方式。

## 阶段 1：CANN + python 环境

```bash
# CANN（已有则跳过安装）：装 home 或 /usr/local 均可
bash Ascend-cann-toolkit_9.1.0_linux-aarch64.run --quiet --install-path=$HOME/Ascend
export ASCEND_HOME_PATH=$HOME/Ascend/cann   # 或 /usr/local/Ascend/cann
source "$ASCEND_HOME_PATH/set_env.sh"

sudo dnf install -y python3.11 python3.11-pip cmake make gcc-c++ 2>/dev/null || true
python3.11 -m venv ~/venv-urma && source ~/venv-urma/bin/activate
pip install --upgrade pip && pip install torch==2.10.0 torch-npu==2.10.0.post2
python3 -c "import torch, torch_npu; torch.npu.set_device(0); print('NPU-OK')"
```

## 阶段 2：拉代码

```bash
cd $BASE
git clone https://github.com/JiJiaF1020/copy-scheme-bench.git bench
# KVAF 二选一：
#   a) git clone -b ak_mtp_yq --single-branch https://gitcode.com/CacheOS/KVAF.git KVAF   (需凭据)
#   b) tar xf <KVAF tarball> && mv <解包目录> KVAF
```

## 阶段 3：构建 KVAF（cpu + npu 两个 role)

```bash
cd $BASE/KVAF
bash build.sh cpu --build-dir $BASE/KVAF/build-cpu --jobs $(nproc)
source "$ASCEND_HOME_PATH/set_env.sh"
ASCEND_CANN_PACKAGE_PATH="$ASCEND_HOME_PATH" PYTHON="$(command -v python3)" \
  bash build.sh npu --build-dir $BASE/KVAF/build-npu --jobs $(nproc)

# 通过标准（三条都成立）：
ls -l $BASE/KVAF/build-cpu/runtime/kvaf_cpu_service
ls -l $BASE/KVAF/build-npu/bin/kvaf_execute_batch_get_kernels.o $BASE/KVAF/build-npu/bin/kvaf_execute_batch_put_kernels.o
PYTHONPATH=$BASE/KVAF/build-npu/python python3 -c "import kvaf; assert hasattr(kvaf,'NpuRuntime'); print('KVAF-BINDING-OK')"
```

## 阶段 4：起 KVAF CPU service（常驻）

```bash
nohup $BASE/KVAF/build-cpu/runtime/kvaf_cpu_service --listen 0.0.0.0 --port 28999 \
  > $BASE/kvaf_cpu_service.log 2>&1 &
sleep 5
ss -ltnp | grep 28999    # 看到监听即 OK；起不来先看 $BASE/kvaf_cpu_service.log
```

## 阶段 5：跑 URMA 带宽扫描

```bash
source ~/venv-urma/bin/activate
export PYTHONPATH=$BASE/KVAF/build-npu/python${PYTHONPATH:+:$PYTHONPATH}
export ASCEND_RT_VISIBLE_DEVICES=0
cd $BASE/bench/side_kvaf
python3 urma_ceiling_bench.py --device npu:0 \
  --batch-get-kernel $BASE/KVAF/build-npu/bin/kvaf_execute_batch_get_kernels.o \
  --batch-put-kernel $BASE/KVAF/build-npu/bin/kvaf_execute_batch_put_kernels.o \
  --cpu-service-addr 127.0.0.1:28999 \
  2>&1 | tee $BASE/urma_ceiling.log
```

默认扫 5 档 payload × 2 布局 = 10 个点：tokens {7200, 16384, 49152, 131072,
262144}（≈4.7MB ~ 172MB/迭代）× {sequential, random}。可加档：
`--tokens 7200 16384 49152 131072 262144 524288`。

## 取数与判读

- 正确性门槛：每行 `URMA_CEILING_RESULT ... ok=1`；有 ok=0 该点无效。
- **极限 = sequential 布局最高档的 `gbps`**（十进制 GB/s，已由 gibps 换算好）。
- `random` 布局是生产（LIDU 随机 miss）代表值；random 比 sequential 低 >30%
  说明随机行惩罚大，单独标注。
- 最高档带宽仍在随 payload 上升 ⇒ 没摸到顶，加大 --tokens 复测。

## 可选：KSC(PCIe）对照

公开仓 `xieqiang-hw/nanovllm-DSA-offload_scatter_copy`（branch
`scatter_copy_a5_c8`）`build_c8.sh` 构建后跑
`tests/test_kvcache_scatter_copy.py --device npu:0 --batch-size 24
--copy-count {300,2048} --source-len 65536 --hbm-slots 8192 --warmup 10
--iters 500`，取 `avg_bandwidth` 与本 bench 的 random 档同坐标比。

## 回报模板

阶段 0 全部原文 + 阶段 3 三条通过标准证据 + `ss -ltnp` 行 +
`URMA_CEILING_CONFIG` 行 + 全部 `URMA_CEILING_RESULT` 行 + 各阶段时间戳。

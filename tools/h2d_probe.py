#!/usr/bin/env python3
"""连续 H2D 带宽探针：pinned host -> device 大块拷贝，Event 计时。

用途：区分「PCIe 链路差」与「随机读路径差」——连续大块 H2D 几乎只受链路
（PCIe 速率/拓扑）影响；若本探针正常但 scatter_copy 差，则嫌疑在随机读路径
（IOMMU/swapped-memory 驱动/NUMA/CANN 版本差）。

示例：
    ASCEND_RT_VISIBLE_DEVICES=3 python3 tools/h2d_probe.py --device npu:0
    python3 tools/h2d_probe.py --device npu:2 --mb 512 --iters 100
"""
import argparse


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="npu:0")
    ap.add_argument("--mb", type=int, default=256, help="单次拷贝大小 MiB")
    ap.add_argument("--iters", type=int, default=50)
    ap.add_argument("--warmup", type=int, default=10)
    args = ap.parse_args()

    import torch

    try:
        import torch_npu  # noqa: F401
    except ImportError:
        torch_npu = None

    n = args.mb * 1024 * 1024
    src = torch.empty(n, dtype=torch.uint8, pin_memory=True)
    dst = torch.empty(n, dtype=torch.uint8, device=args.device)

    for _ in range(args.warmup):
        dst.copy_(src, non_blocking=True)
    torch.npu.synchronize()

    start = torch.npu.Event(enable_timing=True)
    end = torch.npu.Event(enable_timing=True)
    start.record()
    for _ in range(args.iters):
        dst.copy_(src, non_blocking=True)
    end.record()
    torch.npu.synchronize()

    ms = start.elapsed_time(end)
    gbps = n * args.iters / (ms * 1e6)  # ms -> s 且 Byte -> GB(1e9)
    print(
        f"H2D_PROBE device={args.device} mb={args.mb} iters={args.iters} "
        f"event_ms={ms:.3f} bandwidth_gbps={gbps:.2f}"
    )


if __name__ == "__main__":
    main()

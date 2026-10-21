#!/usr/bin/env python3
"""URMA (KVAF BatchGet) H2D bandwidth ceiling probe.

Self-contained: depends only on the KVAF NPU Python binding (built from the
gitcode CacheOS/KVAF ak_mtp_yq branch) plus torch/torch_npu.  No vLLM, no
DSA Prepare operator, no 0903 repository.  A running kvaf_cpu_service is
required (it serves the DDR side over UB/URMA).

Sweeps active-token counts (payload = tokens x 656 B) and reports the
effective DDR->HBM bandwidth of the UDMA engine path.  Two layouts:
  sequential = source tokens 0..N-1 (best case, approximates the ceiling)
  random     = uniform random source positions (LIDU-representative)

Timing: per-iteration NPU events after warmup (pipelined-launch throughput,
same convention as the KSC scatter_copy npu benchmark).

Output lines (grep URMA_CEILING):
  URMA_CEILING_CONFIG ...
  URMA_CEILING_RESULT layout=.. tokens=.. payload_mib=.. mean_us=.. \
      p50_us=.. p99_us=.. gibps=.. gbps=.. ok=1
"""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path

import torch
import torch_npu  # type: ignore  # noqa: F401

import kvaf


BLOCK_SIZE = 128
TOKEN_BYTES = 656
ENTRY_BYTES = BLOCK_SIZE * TOKEN_BYTES
SOURCE_FILL = 0x5A


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--device", default="npu:0")
    p.add_argument(
        "--tokens",
        type=int,
        nargs="+",
        default=[7200, 16384, 49152, 131072, 262144],
        help="Active-token sweep points; payload = tokens x 656 B",
    )
    p.add_argument(
        "--layouts",
        nargs="+",
        choices=("sequential", "random"),
        default=["sequential", "random"],
    )
    p.add_argument("--warmup", type=int, default=20)
    p.add_argument("--iters", type=int, default=200)
    p.add_argument("--put-batch-size", type=int, default=128)
    p.add_argument("--npu-cores", type=int, default=32)
    p.add_argument("--jettys-per-core", type=int, default=2)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--batch-get-kernel", type=Path, required=True)
    p.add_argument("--batch-put-kernel", type=Path, required=True)
    p.add_argument("--cpu-service-addr", type=str, required=True)
    p.add_argument("--max-ddr-gib", type=float, default=4.0)
    return p.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not args.tokens or any(t <= 0 for t in args.tokens):
        raise ValueError("--tokens must be positive integers")
    if args.warmup < 0 or args.iters <= 0 or args.put_batch_size <= 0:
        raise ValueError("warmup >= 0, iters/put-batch-size > 0 required")
    if not args.batch_get_kernel.is_file():
        raise FileNotFoundError(args.batch_get_kernel)
    if not args.batch_put_kernel.is_file():
        raise FileNotFoundError(args.batch_put_kernel)
    if not hasattr(kvaf, "NpuRuntime"):
        raise RuntimeError("KVAF binding lacks NpuRuntime (need ak_mtp_yq build)")
    capacity_tokens = max(args.tokens)
    entries = -(-capacity_tokens // BLOCK_SIZE)
    ddr_gib = entries * ENTRY_BYTES / (1024.0**3)
    if ddr_gib > args.max_ddr_gib:
        raise ValueError(
            f"requested DDR {ddr_gib:.3f} GiB exceeds --max-ddr-gib {args.max_ddr_gib}"
        )


def percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def main() -> None:
    args = parse_args()
    validate_args(args)
    torch.manual_seed(args.seed)
    device = torch.device(args.device)
    torch.npu.set_device(device)
    device_id = 0 if device.index is None else int(device.index)

    capacity_tokens = max(args.tokens)
    entries = -(-capacity_tokens // BLOCK_SIZE)
    ddr_bytes = entries * ENTRY_BYTES

    runtime = kvaf.NpuRuntime(
        batch_get_kernel_object_path=str(args.batch_get_kernel),
        batch_get_token_bytes=TOKEN_BYTES,
        batch_get_tokens_per_block=BLOCK_SIZE,
        device_id=device_id,
        npu_core_count=args.npu_cores,
        batch_put_kernel_object_path=str(args.batch_put_kernel),
        jettys_per_core=args.jettys_per_core,
    )
    stream = torch.npu.current_stream()
    handle = None
    keys: list[int] = []

    print(
        "URMA_CEILING_CONFIG "
        f"device={args.device} device_name={torch_npu.npu.get_device_name(device)} "
        f"tokens={args.tokens} layouts={args.layouts} "
        f"capacity_tokens={capacity_tokens} entries={entries} "
        f"ddr_mib={ddr_bytes / (1024.0**2):.1f} "
        f"warmup={args.warmup} iters={args.iters} "
        f"npu_cores={args.npu_cores} jettys_per_core={args.jettys_per_core} "
        f"cpu_service={args.cpu_service_addr}",
        flush=True,
    )

    try:
        runtime.link_to(args.cpu_service_addr)
        runtime.initialize(ddr_bytes, ENTRY_BYTES)

        # Populate the DDR table with a known fill pattern.
        keys = list(range(1, entries + 1))
        packed_input = torch.full(
            (args.put_batch_size, ENTRY_BYTES), SOURCE_FILL,
            dtype=torch.uint8, device=device,
        )
        for start in range(0, entries, args.put_batch_size):
            key_batch = keys[start : start + args.put_batch_size]
            batch = len(key_batch)
            runtime.batch_put(
                key_batch,
                packed_input[:batch].reshape(-1),
                [row * ENTRY_BYTES for row in range(batch)],
                [ENTRY_BYTES] * batch,
            )
        torch.npu.synchronize()

        handle = runtime.prepare_access_table(
            torch.arange(1, entries + 1, dtype=torch.int64)
        )
        device_table = runtime.access_table_view(
            handle, device="npu", capacity=entries
        )
        torch.npu.synchronize()

        packed_output = torch.zeros(
            (capacity_tokens, TOKEN_BYTES), dtype=torch.uint8, device=device
        )
        perm = torch.randperm(capacity_tokens, dtype=torch.int64)

        for layout in args.layouts:
            for tokens in args.tokens:
                if layout == "sequential":
                    positions = torch.arange(tokens, dtype=torch.int64)
                else:
                    positions = perm[:tokens]
                indices = (positions // BLOCK_SIZE).to(torch.int32).to(device)
                offsets = (
                    (positions % BLOCK_SIZE) * TOKEN_BYTES
                ).to(torch.int32).to(device)
                output_indices = torch.arange(
                    tokens, dtype=torch.int32, device=device
                )
                total_miss = torch.tensor(
                    [tokens], dtype=torch.int32, device=device
                )

                def launch() -> None:
                    runtime.batch_get(
                        device_table,
                        indices,
                        offsets,
                        total_miss,
                        output_indices,
                        packed_output,
                        stream,
                        False,
                    )

                for _ in range(args.warmup):
                    launch()
                torch.npu.synchronize()

                ok = bool(
                    (packed_output[:tokens] == SOURCE_FILL).all().item()
                )

                starts = [
                    torch.npu.Event(enable_timing=True) for _ in range(args.iters)
                ]
                ends = [
                    torch.npu.Event(enable_timing=True) for _ in range(args.iters)
                ]
                for start_ev, end_ev in zip(starts, ends):
                    start_ev.record()
                    launch()
                    end_ev.record()
                ends[-1].synchronize()
                samples_us = [
                    s.elapsed_time(e) * 1000.0 for s, e in zip(starts, ends)
                ]

                mean_us = statistics.mean(samples_us)
                gib = tokens * TOKEN_BYTES / (1024.0**3)
                gibps = gib / (mean_us / 1_000_000.0) if mean_us > 0 else 0.0
                print(
                    "URMA_CEILING_RESULT "
                    f"layout={layout} tokens={tokens} "
                    f"payload_mib={tokens * TOKEN_BYTES / (1024.0**2):.2f} "
                    f"mean_us={mean_us:.3f} "
                    f"p50_us={percentile(samples_us, 0.50):.3f} "
                    f"p99_us={percentile(samples_us, 0.99):.3f} "
                    f"gibps={gibps:.3f} gbps={gibps * 1.073741824:.2f} "
                    f"ok={int(ok)}",
                    flush=True,
                )
    finally:
        try:
            if handle is not None:
                runtime.release_access_table(handle)
            for start in range(0, len(keys), args.put_batch_size):
                runtime.batch_free(keys[start : start + args.put_batch_size])
        finally:
            runtime.shutdown()


if __name__ == "__main__":
    main()

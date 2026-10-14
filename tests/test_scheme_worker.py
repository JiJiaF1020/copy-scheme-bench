#!/usr/bin/env python3
"""Ascend 950 copy-scheme worker: NPU kernel vs CPU gather+H2D vs hybrid split.

Schemes:
  npu     - baseline: the existing kvcache_scatter_copy_c8 kernel reads DRAM
            over PCIe with its depth-8 MTE2 queue (blueprint-compatible timing).
  cpu     - CPU gathers rows from the DRAM-pool mirror into a pinned staging
            buffer, then one big H2D plus an on-device index_copy_ scatter.
  hybrid  - per request, the first count-round(count*cpu_frac) tokens go to the
            kernel, the tail to the CPU path; serial or overlapped execution.

Torch/CANN imports are deferred to main() so argument parsing, validation and
the module import itself stay testable on any host (see test_scheme_tools.py).
"""

from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import _bootstrap

_bootstrap.ensure_importable()

from _common import BLOCK_SIZE, COPY_CAP, ROW_BYTES, add_case_args, validate_args, write_json  # noqa: E402
from scatter_cli import resolve_copy_count  # noqa: E402
from scatter_results import copy_label, print_result  # noqa: E402

import scheme_workload as wl  # noqa: E402
from scheme_config import (DEFAULT_QUEUE_DEPTH, HYBRID_MODES, QUEUE_DEPTH_ENV,  # noqa: E402
                           SCHEMES, SINGLE_TEST)

POISON = 65


@dataclass
class Case:
    device: "torch.device"
    device_name: str
    dram_cpu: "torch.Tensor"          # CPU mirror of the swapped DRAM pool
    dram: "torch.Tensor"              # swapped-memory pool the kernel reads
    hbm: "torch.Tensor"
    hbm_flat: "torch.Tensor"          # hbm.view(-1, ROW_BYTES)
    dram_flat_cpu: "torch.Tensor"     # dram_cpu.view(-1, ROW_BYTES)
    dram_table_cpu: "torch.Tensor"
    hbm_table_cpu: "torch.Tensor"
    dram_table: "torch.Tensor"
    hbm_table: "torch.Tensor"
    src_ids_cpu: "torch.Tensor"
    dst_slots_cpu: "torch.Tensor"
    copy_counts_cpu: "torch.Tensor"
    src_ids: "torch.Tensor"
    dst_slots: "torch.Tensor"
    copy_counts: "torch.Tensor"
    counts: list                      # per-request copy counts (python ints)
    src_rows: list                    # per-request source token ids (python)
    dst_rows: list                    # per-request destination slots (python)
    phys_src_all: "torch.Tensor"      # int64 CPU: physical DRAM rows, all tokens
    phys_dst_all: "torch.Tensor"      # int64 CPU: physical HBM rows, all tokens
    phys_dst_all_npu: "torch.Tensor"
    # hybrid-only: kernel-prefix metadata and CPU-tail flat indices
    kernel_counts: "torch.Tensor | None"
    kernel_src: "torch.Tensor | None"
    kernel_dst: "torch.Tensor | None"
    kernel_counts_cpu: "torch.Tensor | None"
    kernel_src_cpu: "torch.Tensor | None"
    kernel_dst_cpu: "torch.Tensor | None"
    cpu_phys_src: "torch.Tensor | None"
    cpu_phys_dst: "torch.Tensor | None"
    cpu_phys_dst_npu: "torch.Tensor | None"
    cpu_tokens: int
    staging: "torch.Tensor | None"    # pinned CPU staging [n, ROW_BYTES]
    staging_npu: "torch.Tensor | None"
    staging_pinned: bool
    side_stream: "torch.npu.Stream | None"


def add_scheme_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scheme", choices=SCHEMES, default="npu")
    parser.add_argument("--run-frac", type=float, default=0.0,
                        help="Fraction of adjacent source-token pairs that are consecutive (DRAM locality knob).")
    parser.add_argument("--cpu-frac", type=float, default=0.5,
                        help="Hybrid only: per-row fraction of tokens handled by the CPU path.")
    parser.add_argument("--hybrid-mode", choices=HYBRID_MODES, default="overlap")
    parser.add_argument("--cpu-threads", type=int, default=8,
                        help="Torch CPU threads for the gather (npu scheme forces 1).")
    parser.add_argument("--pretouch", action="store_true",
                        help="Touch every 4K page of the DRAM mirror and staging buffers before timing.")
    parser.add_argument("--device", default="npu:0")
    parser.add_argument("--json-output", type=Path)
    for name in ("ready-file", "start-file", "timing-ready-file", "timing-start-file"):
        parser.add_argument(f"--{name}", type=Path, help=argparse.SUPPRESS)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_case_args(parser)
    add_scheme_args(parser)
    return resolve_copy_count(parser.parse_args(argv))


def validate_scheme_args(args: argparse.Namespace) -> None:
    validate_args(args)
    if not 0.0 <= args.run_frac <= 1.0:
        raise ValueError("--run-frac must be within [0.0, 1.0].")
    if not 0.0 <= args.cpu_frac <= 1.0:
        raise ValueError("--cpu-frac must be within [0.0, 1.0].")
    if args.cpu_threads < 1:
        raise ValueError("--cpu-threads must be positive.")


def _pinned_empty(rows: int) -> tuple["torch.Tensor", bool]:
    try:
        return torch.empty((max(rows, 1), ROW_BYTES), dtype=torch.int8, pin_memory=True), True
    except RuntimeError:
        return torch.empty((max(rows, 1), ROW_BYTES), dtype=torch.int8), False


def _pretouch(tensor: "torch.Tensor") -> None:
    flat = tensor.view(-1)
    flat[::4096] += 0  # in-place read/write of one element per 4K page


def make_case(args: argparse.Namespace) -> Case:
    device = torch.device(args.device)
    torch.npu.set_device(device)
    torch.npu.config.allow_internal_format = False
    device_name = require_a5(device, args.allow_non_a5)
    import random
    rng = random.Random(args.seed)
    generator = torch.Generator().manual_seed(args.seed ^ 0x5EED)

    dram_rows, hbm_rows = wl.gen_block_tables(args.batch_size, args.source_len,
                                              args.hbm_slots, BLOCK_SIZE, rng)
    counts, src_rows, dst_rows = wl.gen_copy_lists(args.batch_size, args.source_len,
                                                   args.hbm_slots, args.copy_min,
                                                   args.copy_max, COPY_CAP,
                                                   args.seed, args.run_frac)
    dram_table_cpu = torch.tensor(dram_rows, dtype=torch.int32)
    hbm_table_cpu = torch.tensor(hbm_rows, dtype=torch.int32)
    src_ids_cpu = torch.tensor([wl.pad_row(row, COPY_CAP) for row in src_rows],
                               dtype=torch.int32).reshape(args.batch_size, 1, COPY_CAP)
    dst_slots_cpu = torch.tensor([wl.pad_row(row, COPY_CAP) for row in dst_rows],
                                 dtype=torch.int32).reshape(args.batch_size, 1, COPY_CAP)
    copy_counts_cpu = torch.tensor(counts, dtype=torch.int32)
    source_blocks = wl.block_count(args.source_len, BLOCK_SIZE)
    dram_cpu = torch.randint(-128, 128, (source_blocks, BLOCK_SIZE, 1, ROW_BYTES),
                             dtype=torch.int8, generator=generator)
    mapped_blocks = args.batch_size * wl.block_count(args.hbm_slots, BLOCK_SIZE)
    hbm = torch.empty((mapped_blocks + 1, BLOCK_SIZE, 1, ROW_BYTES), dtype=torch.int8, device=device)

    phys_src_all = [p for row, count in enumerate(counts)
                    for p in wl.resolve_phys_rows(dram_rows[row], src_rows[row][:count], BLOCK_SIZE)]
    phys_dst_all = [p for row, count in enumerate(counts)
                    for p in wl.resolve_phys_rows(hbm_rows[row], dst_rows[row][:count], BLOCK_SIZE)]

    kernel_counts = kernel_src = kernel_dst = None
    kernel_counts_cpu = kernel_src_cpu = kernel_dst_cpu = None
    cpu_phys_src = cpu_phys_dst = cpu_phys_dst_npu = None
    cpu_tokens = 0
    if args.scheme == "hybrid":
        split = wl.split_hybrid(counts, src_rows, dst_rows, args.cpu_frac)
        kernel_counts_cpu = torch.tensor(split["kernel_counts"], dtype=torch.int32)
        kernel_src_cpu = torch.tensor([wl.pad_row(row, COPY_CAP) for row in split["kernel_src"]],
                                      dtype=torch.int32).reshape(args.batch_size, 1, COPY_CAP)
        kernel_dst_cpu = torch.tensor([wl.pad_row(row, COPY_CAP) for row in split["kernel_dst"]],
                                      dtype=torch.int32).reshape(args.batch_size, 1, COPY_CAP)
        kernel_counts = kernel_counts_cpu.to(device)
        kernel_src = kernel_src_cpu.to(device)
        kernel_dst = kernel_dst_cpu.to(device)
        cpu_phys_src_list = [p for row in range(args.batch_size)
                             for p in wl.resolve_phys_rows(dram_rows[row], split["cpu_src"][row], BLOCK_SIZE)]
        cpu_phys_dst_list = [p for row in range(args.batch_size)
                             for p in wl.resolve_phys_rows(hbm_rows[row], split["cpu_dst"][row], BLOCK_SIZE)]
        cpu_phys_src = torch.tensor(cpu_phys_src_list, dtype=torch.int64)
        cpu_phys_dst = torch.tensor(cpu_phys_dst_list, dtype=torch.int64)
        cpu_phys_dst_npu = cpu_phys_dst.to(device)
        cpu_tokens = len(cpu_phys_src_list)

    staging = staging_npu = None
    staging_pinned = False
    stage_tokens = cpu_tokens if args.scheme == "hybrid" else len(phys_src_all)
    if args.scheme in ("cpu", "hybrid") and stage_tokens > 0:
        staging, staging_pinned = _pinned_empty(stage_tokens)
        staging_npu = torch.empty((stage_tokens, ROW_BYTES), dtype=torch.int8, device=device)

    case = Case(
        device=device, device_name=device_name, dram_cpu=dram_cpu,
        dram=swapped_from_cpu(dram_cpu, device), hbm=hbm,
        hbm_flat=hbm.view(-1, ROW_BYTES), dram_flat_cpu=dram_cpu.view(-1, ROW_BYTES),
        dram_table_cpu=dram_table_cpu, hbm_table_cpu=hbm_table_cpu,
        dram_table=dram_table_cpu.to(device), hbm_table=hbm_table_cpu.to(device),
        src_ids_cpu=src_ids_cpu, dst_slots_cpu=dst_slots_cpu, copy_counts_cpu=copy_counts_cpu,
        src_ids=src_ids_cpu.to(device), dst_slots=dst_slots_cpu.to(device),
        copy_counts=copy_counts_cpu.to(device),
        counts=counts, src_rows=src_rows, dst_rows=dst_rows,
        phys_src_all=torch.tensor(phys_src_all, dtype=torch.int64),
        phys_dst_all=torch.tensor(phys_dst_all, dtype=torch.int64),
        phys_dst_all_npu=torch.tensor(phys_dst_all, dtype=torch.int64).to(device),
        kernel_counts=kernel_counts, kernel_src=kernel_src, kernel_dst=kernel_dst,
        kernel_counts_cpu=kernel_counts_cpu, kernel_src_cpu=kernel_src_cpu,
        kernel_dst_cpu=kernel_dst_cpu,
        cpu_phys_src=cpu_phys_src, cpu_phys_dst=cpu_phys_dst,
        cpu_phys_dst_npu=cpu_phys_dst_npu, cpu_tokens=cpu_tokens,
        staging=staging, staging_npu=staging_npu, staging_pinned=staging_pinned,
        side_stream=torch.npu.Stream() if args.scheme == "hybrid" else None,
    )
    if args.pretouch:
        _pretouch(case.dram_cpu)
        if staging is not None:
            staging.view(-1).fill_(0)  # staging content is scratch; fill touches pages
    return case


def launch_kernel(case: Case, counts_override=None) -> None:
    """The NPU path: kvcache_scatter_copy_c8 (kernel-prefix metadata for hybrid)."""
    if case.kernel_counts is not None:
        return vllm_dsa_a5.kvcache_scatter_copy_c8(
            case.hbm, case.dram, case.hbm_table, case.dram_table,
            case.kernel_src, case.kernel_dst,
            case.kernel_counts if counts_override is None else counts_override)
    return vllm_dsa_a5.kvcache_scatter_copy_c8(
        case.hbm, case.dram, case.hbm_table, case.dram_table,
        case.src_ids, case.dst_slots,
        case.copy_counts if counts_override is None else counts_override)


def cpu_gather(case: Case) -> None:
    """CPU path phase 1: gather rows from the DRAM mirror into pinned staging.

    Reads host DRAM directly - no PCIe round trip per row. index_select is
    multithreaded by torch (see --cpu-threads). No-op when this scheme's share
    is empty (copy=0, or hybrid with cpu_frac rounding to zero).
    """
    src = case.cpu_phys_src if case.cpu_phys_src is not None else case.phys_src_all
    if src.numel() == 0:
        return
    case.staging.copy_(case.dram_flat_cpu.index_select(0, src))


def cpu_device_pass(case: Case) -> None:
    """CPU path phase 2: one big H2D of the staging buffer + scatter to dst slots."""
    dst = case.cpu_phys_dst_npu if case.cpu_phys_dst_npu is not None else case.phys_dst_all_npu
    if dst.numel() == 0:
        return
    case.staging_npu.copy_(case.staging, non_blocking=True)
    case.hbm_flat.index_copy_(0, dst, case.staging_npu)


def cpu_full_pass(case: Case) -> None:
    cpu_gather(case)
    cpu_device_pass(case)


def hybrid_pass(case: Case, mode: str) -> None:
    if mode == "serial":
        launch_kernel(case)
        torch.npu.synchronize()
        cpu_full_pass(case)
        torch.npu.synchronize()
        return
    # overlap: kernel runs on the default stream while the CPU gathers; the
    # H2D + scatter then run on a side stream, concurrent with the kernel's
    # own PCIe reads.
    launch_kernel(case)
    cpu_gather(case)
    with torch.npu.stream(case.side_stream):
        cpu_device_pass(case)
    torch.npu.synchronize()


def run_scheme_pass(case: Case, scheme: str, mode: str) -> None:
    if scheme == "npu":
        launch_kernel(case)
    elif scheme == "cpu":
        cpu_full_pass(case)
    else:
        hybrid_pass(case, mode)


def assert_copied(case: Case) -> None:
    """Byte-exact check of the full HBM cache against the CPU reference."""
    sources, destinations = [], []
    for row, count in enumerate(case.counts):
        if count == 0:
            continue
        src_tok = torch.tensor(case.src_rows[row][:count], dtype=torch.int64)
        dst_tok = torch.tensor(case.dst_rows[row][:count], dtype=torch.int64)
        sources.append(case.dram_table_cpu[row].long()[src_tok // BLOCK_SIZE] * BLOCK_SIZE
                       + src_tok % BLOCK_SIZE)
        destinations.append(case.hbm_table_cpu[row].long()[dst_tok // BLOCK_SIZE] * BLOCK_SIZE
                            + dst_tok % BLOCK_SIZE)
    source = torch.cat(sources) if sources else torch.empty(0, dtype=torch.int64)
    destination = torch.cat(destinations) if destinations else torch.empty(0, dtype=torch.int64)
    expected = torch.full((case.hbm.shape[0] * BLOCK_SIZE, ROW_BYTES), POISON, dtype=torch.int8)
    expected[destination] = case.dram_flat_cpu[source]
    if not torch.equal(case.hbm.cpu().reshape(-1, ROW_BYTES), expected):
        raise AssertionError("DRAM->HBM byte mismatch or inactive HBM bytes were modified.")


def assert_metadata_unchanged(case: Case) -> None:
    pairs = [(case.src_ids, case.src_ids_cpu), (case.dst_slots, case.dst_slots_cpu),
             (case.copy_counts, case.copy_counts_cpu),
             (case.hbm_table, case.hbm_table_cpu), (case.dram_table, case.dram_table_cpu)]
    if case.kernel_counts is not None:
        pairs += [(case.kernel_src, case.kernel_src_cpu),
                  (case.kernel_dst, case.kernel_dst_cpu),
                  (case.kernel_counts, case.kernel_counts_cpu)]
    for actual, expected in pairs:
        if not torch.equal(actual.cpu(), expected):
            raise AssertionError("Read-only copy metadata was modified.")


def check_copy(case: Case, args: argparse.Namespace, phase: str) -> None:
    case.hbm.fill_(POISON)
    torch.npu.synchronize()
    if not bool((case.hbm == POISON).all().item()):
        raise AssertionError("HBM destinations were not poisoned before the copy.")
    run_scheme_pass(case, args.scheme, args.hybrid_mode)
    torch.npu.synchronize()
    assert_copied(case)
    if args.scheme in ("npu", "hybrid"):
        assert_metadata_unchanged(case)
    print(f"A5_COPY_SCHEME_CHECK scheme={args.scheme} phase={phase} "
          f"copied_tokens={sum(case.counts)} row_bytes={ROW_BYTES} byte_exact=1 ok=1", flush=True)


def wait_for_start(ready_file: Path | None, start_file: Path | None) -> None:
    if ready_file is None and start_file is None:
        return
    if ready_file is None or start_file is None:
        raise ValueError("ready and start files must be specified together")
    ready_file.parent.mkdir(parents=True, exist_ok=True)
    ready_file.write_text("ready\n", encoding="utf-8")
    deadline = time.monotonic() + 600
    while not start_file.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("Timed out waiting for multiprocess start")
        time.sleep(0.001)


def time_npu(case: Case, args: argparse.Namespace) -> dict:
    """Blueprint-compatible event window plus a per-iteration synced wall time."""
    for _ in range(args.warmup):
        launch_kernel(case)
    torch.npu.synchronize()
    start = torch.npu.Event(enable_timing=True)
    end = torch.npu.Event(enable_timing=True)
    wait_for_start(args.timing_ready_file, args.timing_start_file)
    start.record()
    for _ in range(args.iters):
        launch_kernel(case)
    end.record()
    end.synchronize()
    avg_us = start.elapsed_time(end) * 1000 / args.iters
    synced_iters = max(1, args.iters // 4)
    total_ns = 0
    for _ in range(synced_iters):
        t0 = time.perf_counter_ns()
        launch_kernel(case)
        torch.npu.synchronize()
        total_ns += time.perf_counter_ns() - t0
    return {"timer": "npu_event", "avg_us": avg_us,
            "avg_us_host_synced": total_ns / synced_iters / 1000.0, "phases": {}}


def time_cpu(case: Case, args: argparse.Namespace) -> dict:
    for _ in range(args.warmup):
        cpu_full_pass(case)
        torch.npu.synchronize()
    wait_for_start(args.timing_ready_file, args.timing_start_file)
    start = torch.npu.Event(enable_timing=True)
    end = torch.npu.Event(enable_timing=True)
    gather_ns = device_us = total_ns = 0.0
    for _ in range(args.iters):
        t0 = time.perf_counter_ns()
        cpu_gather(case)
        t1 = time.perf_counter_ns()
        start.record()
        cpu_device_pass(case)
        end.record()
        torch.npu.synchronize()
        t2 = time.perf_counter_ns()
        gather_ns += t1 - t0
        device_us += start.elapsed_time(end) * 1000
        total_ns += t2 - t0
    return {"timer": "perf_counter", "avg_us": total_ns / args.iters / 1000.0,
            "avg_us_host_synced": None,
            "phases": {"cpu_gather_us": gather_ns / args.iters / 1000.0,
                       "h2d_scatter_us": device_us / args.iters}}


def time_hybrid(case: Case, args: argparse.Namespace) -> dict:
    serial = args.hybrid_mode == "serial"
    for _ in range(args.warmup):
        hybrid_pass(case, args.hybrid_mode)
    wait_for_start(args.timing_ready_file, args.timing_start_file)
    start = torch.npu.Event(enable_timing=True)
    end = torch.npu.Event(enable_timing=True)
    gather_ns = kernel_us = total_ns = 0.0
    for _ in range(args.iters):
        t0 = time.perf_counter_ns()
        if serial:
            start.record()
            launch_kernel(case)
            end.record()
            torch.npu.synchronize()
            t1 = time.perf_counter_ns()
            cpu_gather(case)
            cpu_device_pass(case)
            torch.npu.synchronize()
            t2 = time.perf_counter_ns()
        else:
            start.record()
            launch_kernel(case)
            cpu_gather(case)
            t1 = time.perf_counter_ns()
            with torch.npu.stream(case.side_stream):
                cpu_device_pass(case)
            end.record()
            torch.npu.synchronize()
            t2 = time.perf_counter_ns()
        gather_ns += t1 - t0
        kernel_us += start.elapsed_time(end) * 1000
        total_ns += t2 - t0
    first_phase = "kernel_wall_us" if serial else "launch_to_gather_done_us"
    return {"timer": "perf_counter", "avg_us": total_ns / args.iters / 1000.0,
            "avg_us_host_synced": None,
            "phases": {first_phase: gather_ns / args.iters / 1000.0,
                       "kernel_event_us": kernel_us / args.iters}}


def run(args: argparse.Namespace) -> dict:
    uses_kernel = args.scheme in ("npu", "hybrid")
    if uses_kernel:
        # First-fill capacity through the SAME kernel/ABI, outside timing.
        fill_args = argparse.Namespace(**vars(args))
        fill_args.batch_size = 1
        fill_args.source_len = fill_args.hbm_slots = COPY_CAP
        fill_args.copy_min = fill_args.copy_max = COPY_CAP
        fill_args.scheme = "npu"
        fill_case = make_case(fill_args)
        check_copy(fill_case, fill_args, "first_fill_capacity")
        del fill_case
        torch.npu.empty_cache()

    case = make_case(args)
    copied_tokens = sum(case.counts)
    payload_bytes = copied_tokens * ROW_BYTES
    print(f"A5_COPY_SCHEME_CONFIG device={case.device} device_name={case.device_name!r} "
          f"scheme={args.scheme} run_frac={args.run_frac} cpu_frac={args.cpu_frac} "
          f"hybrid_mode={args.hybrid_mode} cpu_threads={args.cpu_threads} "
          f"pretouch={args.pretouch} staging_pinned={case.staging_pinned} "
          f"batch={args.batch_size} copy_range=[{args.copy_min},{args.copy_max}] "
          f"copied_tokens={copied_tokens} cpu_tokens={case.cpu_tokens} "
          f"queue_depth={os.environ.get(QUEUE_DEPTH_ENV, DEFAULT_QUEUE_DEPTH)}", flush=True)

    check_copy(case, args, "requested_workload")
    if uses_kernel:
        case.hbm.fill_(POISON)
        if launch_kernel(case, torch.zeros_like(
                case.kernel_counts if case.kernel_counts is not None else case.copy_counts)) is not None:
            raise AssertionError("Zero-copy kernel call must return None.")
        torch.npu.synchronize()
        if not bool((case.hbm == POISON).all().item()):
            raise AssertionError("copy_count=0 modified the HBM cache.")
        print("A5_COPY_SCHEME_ZERO_COUNT_CHECK all_hbm_unchanged=1 ok=1", flush=True)

    wait_for_start(args.ready_file, args.start_file)
    if args.scheme == "npu":
        performance = time_npu(case, args)
    elif args.scheme == "cpu":
        performance = time_cpu(case, args)
    else:
        performance = time_hybrid(case, args)
    assert_copied(case)

    row = {"cards": 1, "batch_size": args.batch_size, "copy_count": copy_label(vars(args)),
           "avg_us_mean": performance["avg_us"], "avg_us_max": performance["avg_us"],
           "avg_bandwidth": payload_bytes / (performance["avg_us"] * 1000.0) if performance["avg_us"] > 0 else 0.0}
    print_result(row)
    result = {
        "schema_version": 2, "test": SINGLE_TEST,
        "status": "passed", "timestamp_utc": datetime.now(timezone.utc).isoformat(), "device_count": 1,
        "config": {
            "device": str(case.device), "device_name": case.device_name,
            "dtype": "c8", "row_bytes": ROW_BYTES, "batch_size": args.batch_size,
            "source_len": args.source_len, "hbm_slots": args.hbm_slots,
            "copy_min": args.copy_min, "copy_max": args.copy_max, "copy_cap": COPY_CAP,
            "warmup": args.warmup, "iters": args.iters, "seed": args.seed,
            "scheme": args.scheme, "run_frac": args.run_frac, "cpu_frac": args.cpu_frac,
            "hybrid_mode": args.hybrid_mode, "cpu_threads": args.cpu_threads,
            "pretouch": bool(args.pretouch), "staging_pinned": case.staging_pinned,
            "queue_depth": int(os.environ.get(QUEUE_DEPTH_ENV, DEFAULT_QUEUE_DEPTH)),
        },
        "workload": {
            "copy_counts": case.counts, "copied_tokens": copied_tokens,
            "cpu_tokens": case.cpu_tokens,
            "payload_bytes_per_iteration": payload_bytes,
        },
        "correctness": {
            "data_exact": True, "guard_unchanged": True,
            **({"zero_count_unchanged": True, "first_fill_capacity": True,
                "metadata_unchanged": True} if uses_kernel else {}),
        },
        "summary": row,
        "performance": performance,
    }
    if args.json_output is not None:
        write_json(args.json_output, result)
    print("A5_KVCACHE_COPY_SCHEME_UT_OK", flush=True)
    return result


def main() -> None:
    args = parse_args()
    validate_scheme_args(args)
    global torch, torch_npu, vllm_dsa_a5, require_a5, swapped_from_cpu
    # Select the blueprint checkout's OPP before torch_npu initializes.
    import vllm_dsa_a5
    import torch
    import torch_npu
    import sys
    sys.path.insert(0, str(_bootstrap.scatter_root() / "tests"))
    from _utils import require_a5, swapped_from_cpu
    torch.set_num_threads(1 if args.scheme == "npu" else args.cpu_threads)
    run(args)


if __name__ == "__main__":
    main()

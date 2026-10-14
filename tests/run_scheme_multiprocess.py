#!/usr/bin/env python3
"""Run one independent copy-scheme worker per selected NPU die.

Forked from the blueprint's test_kvcache_scatter_copy_multiprocess.py with the
scheme flags added; the two-phase file handshake, NUMA binding convention and
result aggregation stay identical.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import _bootstrap

_bootstrap.ensure_importable()

from _common import ROW_BYTES, add_case_args, validate_args, write_json  # noqa: E402
from scatter_cli import add_device_args, resolve_copy_count, selected_devices, validate_workload  # noqa: E402
from scatter_results import copy_label, print_result, summarize_devices  # noqa: E402

from scheme_config import MULTIPROCESS_TEST, NUMA_ENV, RESULTS_SUBDIR, SINGLE_TEST  # noqa: E402
from test_scheme_worker import add_scheme_args, validate_scheme_args  # noqa: E402


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_case_args(parser)
    add_scheme_args(parser)
    add_device_args(parser, "0")
    parser.add_argument("--output", type=Path, help="Case JSON path (default: scheme results directory).")
    parser.add_argument("--same-seed", action="store_true")
    args = parser.parse_args(argv)
    user_output = args.output
    args = resolve_copy_count(args)  # sets copy_min/max; may fill a blueprint-style default output
    args.output = user_output
    if args.output is None:
        cards = args.cards if args.cards is not None else len(args.devices.split(","))
        copies = str(args.copy_min) if args.copy_min == args.copy_max else f"{args.copy_min}-{args.copy_max}"
        frac = f"{args.run_frac:g}".replace(".", "p")
        name = f"{args.scheme}_cards{cards}_bs{args.batch_size}_copy{copies}_rf{frac}"
        if args.scheme == "hybrid":
            name += f"_cf{str(args.cpu_frac).replace('.', 'p')}_{args.hybrid_mode}"
        args.output = Path(__file__).resolve().parents[1] / RESULTS_SUBDIR / f"{name}.json"
    return args


def wait_until_ready(ready_files: list[Path], processes: list, phase: str) -> None:
    deadline = time.monotonic() + 600
    while not all(path.exists() for path in ready_files):
        failed = [
            (rank, process.returncode)
            for (rank, process, _), ready in zip(processes, ready_files)
            if process.poll() is not None and (process.returncode != 0 or not ready.exists())
        ]
        if failed:
            raise RuntimeError(f"Workers exited during {phase}: {failed}")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Timed out waiting for workers during {phase}")
        time.sleep(0.01)


def stop_workers(processes: list) -> None:
    for _, process, _ in processes:
        if process.poll() is None:
            process.terminate()
    for _, process, _ in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def numactl_nodes(devices: list[int]) -> list[str]:
    """Optional per-rank NUMA binding via SCATTER_C8_NUMA_NODES="n0,n1,..."."""
    value = os.environ.get(NUMA_ENV, "").strip()
    if not value:
        return []
    nodes = [item.strip() for item in value.split(",")]
    if len(nodes) != len(devices) or any(not node.isdigit() for node in nodes):
        raise ValueError(f"{NUMA_ENV} must list one non-negative node id per device.")
    return nodes


def run_workers(args: argparse.Namespace, devices: list[int]) -> list[dict]:
    worker = Path(__file__).with_name("test_scheme_worker.py")
    numa_nodes = numactl_nodes(devices)
    with tempfile.TemporaryDirectory(prefix="a5_copy_scheme_") as name:
        temp = Path(name)
        start_file, timing_start_file = temp / "start", temp / "timing_start"
        initial_ready, timing_ready, processes = [], [], []
        try:
            for rank, device in enumerate(devices):
                result_file = temp / f"result_{rank}.json"
                ready_file, timing_ready_file = temp / f"ready_{rank}", temp / f"timing_ready_{rank}"
                initial_ready.append(ready_file)
                timing_ready.append(timing_ready_file)
                seed = args.seed if args.same_seed else args.seed + rank
                command = [
                    sys.executable, str(worker), "--device", f"npu:{device}", "--dtype", args.dtype,
                    "--batch-size", str(args.batch_size), "--source-len", str(args.source_len),
                    "--hbm-slots", str(args.hbm_slots), "--copy-min", str(args.copy_min),
                    "--copy-max", str(args.copy_max), "--copy-cap", str(args.copy_cap),
                    "--warmup", str(args.warmup), "--iters", str(args.iters), "--seed", str(seed),
                    "--scheme", args.scheme, "--run-frac", str(args.run_frac),
                    "--cpu-frac", str(args.cpu_frac), "--hybrid-mode", args.hybrid_mode,
                    "--cpu-threads", str(args.cpu_threads), "--window", str(args.window),
                    "--json-output", str(result_file), "--ready-file", str(ready_file),
                    "--start-file", str(start_file), "--timing-ready-file", str(timing_ready_file),
                    "--timing-start-file", str(timing_start_file),
                ]
                if args.pretouch:
                    command.append("--pretouch")
                if args.allow_non_a5:
                    command.append("--allow-non-a5")
                if numa_nodes:
                    node = numa_nodes[rank]
                    command = ["numactl", f"--cpunodebind={node}", f"--membind={node}"] + command
                print(f"A5_COPY_SCHEME_LAUNCH rank={rank} device=npu:{device} scheme={args.scheme} "
                      f"seed={seed} numa_node={numa_nodes[rank] if numa_nodes else 'unbound'}", flush=True)
                processes.append((rank, subprocess.Popen(command), result_file))
            wait_until_ready(initial_ready, processes, "initialization")
            start_file.write_text("start\n", encoding="utf-8")
            print("A5_COPY_SCHEME_WARMUP_START all_workers_ready=1", flush=True)
            wait_until_ready(timing_ready, processes, "warmup")
            timing_start_file.write_text("start\n", encoding="utf-8")
            print("A5_COPY_SCHEME_TIMING_START all_workers_ready=1", flush=True)
            while True:
                codes = [(rank, process.poll()) for rank, process, _ in processes]
                failures = [(rank, code) for rank, code in codes if code not in (None, 0)]
                if failures:
                    raise RuntimeError(f"Workers failed: {failures}")
                if all(code is not None for _, code in codes):
                    break
                time.sleep(0.05)
            results = []
            for device, (rank, _, path) in zip(devices, processes):
                result = json.loads(path.read_text(encoding="utf-8"))
                if result.get("status") != "passed" or result.get("test") != SINGLE_TEST:
                    raise RuntimeError(f"Worker {rank} did not produce a passing scheme result.")
                if not all(result["correctness"].values()):
                    raise RuntimeError(f"Worker {rank} failed a correctness check.")
                result.update(rank=rank, logical_device_index=device)
                results.append(result)
            return results
        finally:
            stop_workers(processes)


def summarize(args: argparse.Namespace, devices: list[int], per_device: list[dict]) -> dict:
    total_bytes = sum(int(item["workload"]["payload_bytes_per_iteration"]) for item in per_device)
    total_tokens = sum(int(item["workload"]["copied_tokens"]) for item in per_device)
    return {
        "schema_version": 2, "test": MULTIPROCESS_TEST,
        "status": "passed", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "visible_devices": os.environ.get("ASCEND_RT_VISIBLE_DEVICES"),
        "device_count": len(devices), "devices": devices, "same_seed": args.same_seed,
        "config": {
            "dtype": args.dtype, "row_bytes": ROW_BYTES, "batch_size": args.batch_size,
            "source_len": args.source_len, "hbm_slots": args.hbm_slots,
            "copy_min": args.copy_min, "copy_max": args.copy_max, "copy_cap": args.copy_cap,
            "warmup": args.warmup, "iters": args.iters, "seed": args.seed,
            "allow_non_a5": args.allow_non_a5,
            "scheme": args.scheme, "run_frac": args.run_frac, "cpu_frac": args.cpu_frac,
            "hybrid_mode": args.hybrid_mode, "cpu_threads": args.cpu_threads,
            "pretouch": bool(args.pretouch), "window": args.window,
            "numa_nodes": os.environ.get(NUMA_ENV, ""),
        },
        "summary": {
            **summarize_devices(per_device),
            "total_payload_bytes_per_iteration": total_bytes,
            "copied_tokens_sum_per_iteration": total_tokens, "all_correct": True,
        },
        "per_device": per_device,
    }


def main() -> None:
    args = parse_args()
    validate_scheme_args(args)
    validate_workload(args)
    devices = selected_devices(args)
    # Invalidate a previous successful result if this rerun subsequently fails.
    write_json(args.output, {"status": "running", "devices": devices, "scheme": args.scheme})
    try:
        output = summarize(args, devices, run_workers(args, devices))
    except BaseException as error:
        write_json(args.output, {"status": "failed", "devices": devices,
                                 "scheme": args.scheme, "error": str(error)})
        raise
    write_json(args.output, output)
    print_result({"cards": len(devices), "batch_size": args.batch_size,
                  "copy_count": copy_label(vars(args)), **{key: output["summary"][key]
                      for key in ("avg_us_mean", "avg_us_max", "avg_bandwidth")}})
    print("A5_KVCACHE_COPY_SCHEME_MULTIPROCESS_UT_OK", flush=True)


if __name__ == "__main__":
    main()

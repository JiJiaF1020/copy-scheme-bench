#!/usr/bin/env python3
"""Sweep copy schemes x die counts x batch sizes x copy counts x locality.

Same conventions as the blueprint's run_scatter_copy_sweep.py: --dry-run
validates and prints commands on any host (no Torch/CANN needed), failures
invalidate previous results, and a manifest scopes the final analysis.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import _bootstrap

SCATTER_ROOT = _bootstrap.ensure_importable()

from scatter_cli import parse_ids, validate_workload  # noqa: E402
from scatter_config import COPY_CAP_DEFAULT, DEFAULT_VISIBLE_DEVICES, DTYPE, LEGACY_VISIBLE_ENV  # noqa: E402

import scheme_report  # noqa: E402
from scheme_config import (HYBRID_MODES, MANIFEST_NAME, NUMA_ENV,  # noqa: E402
                           QUEUE_DEPTH_ENV, RESULTS_SUBDIR, SCHEMES)

ROOT = Path(__file__).resolve().parents[1]


def number_list(value: str, name: str, minimum: float, kind=int) -> list:
    try:
        values = [kind(part) for part in value.split()]
    except ValueError as error:
        raise ValueError(f"{name} must contain space-separated numbers.") from error
    if not values or min(values) < minimum or len(set(values)) != len(values):
        raise ValueError(f"{name} must contain distinct values >= {minimum}.")
    return values


def scheme_list(value: str) -> list[str]:
    values = value.split()
    if not values or any(item not in SCHEMES for item in values) or len(set(values)) != len(values):
        raise ValueError(f"schemes must be distinct entries of {SCHEMES}.")
    return values


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visible-devices", default=os.getenv("TEST_VISIBLE_DEVICES", os.getenv(LEGACY_VISIBLE_ENV,
                        os.getenv("ASCEND_RT_VISIBLE_DEVICES", DEFAULT_VISIBLE_DEVICES))))
    parser.add_argument("--cards", nargs="+", type=int, help="Logical die counts; environment: CARD_COUNTS.")
    parser.add_argument("--batch-size", nargs="+", type=int, help="Batch sizes per die; environment: BATCH_SIZES.")
    parser.add_argument("--copy-count", nargs="+", type=int, help="Fixed copies per request; environment: COPY_COUNTS.")
    parser.add_argument("--schemes", nargs="+", help=f"Subset of {SCHEMES}; environment: SCHEMES.")
    parser.add_argument("--run-fracs", nargs="+", type=float, help="DRAM locality knob; environment: RUN_FRACS.")
    parser.add_argument("--cpu-fracs", nargs="+", type=float, help="Hybrid CPU share; environment: CPU_FRACS.")
    parser.add_argument("--hybrid-modes", nargs="+", help=f"Subset of {HYBRID_MODES}; environment: HYBRID_MODES.")
    for flag, env, default in (("source-len", "SOURCE_LEN", 65536), ("hbm-slots", "HBM_SLOTS", 8192),
                               ("copy-cap", "COPY_CAP", COPY_CAP_DEFAULT), ("warmup", "WARMUP", 10),
                               ("iters", "ITERS", 1000), ("seed", "SEED", 7), ("cpu-threads", "CPU_THREADS", 8)):
        parser.add_argument(f"--{flag}", type=int, default=os.getenv(env, str(default)))
    parser.add_argument("--numa-nodes", default=os.getenv("NUMA_NODES", ""),
                        help='Space/comma-separated node ids, e.g. "0 1 2 3"; when set, every case runs twice (unbound and bound).')
    parser.add_argument("--pretouch", action="store_true", default=os.getenv("PRETOUCH") == "1")
    parser.add_argument("--results-dir", type=Path, default=Path(os.getenv("RESULTS_DIR", str(ROOT / RESULTS_SUBDIR))))
    parser.add_argument("--dry-run", action="store_true", default=os.getenv("DRY_RUN") == "1",
                        help="Validate and print commands without importing Torch, loading CANN or starting NPUs.")
    args = parser.parse_args(argv)
    visible = parse_ids(args.visible_devices)
    args.visible_devices = ",".join(map(str, visible))
    defaults = " ".join(str(n) for n in (1, 2, 4, 8) if n <= len(visible))
    for key, env, default, minimum in (("cards", "CARD_COUNTS", defaults, 1),
                                      ("batch_size", "BATCH_SIZES", "24", 1),
                                      ("copy_count", "COPY_COUNTS", "0 100 300", 0)):
        command_values = getattr(args, key)
        value = " ".join(map(str, command_values)) if command_values is not None else os.getenv(env, default)
        setattr(args, key, number_list(value, env, minimum))
    args.schemes = scheme_list(" ".join(args.schemes) if args.schemes is not None else os.getenv("SCHEMES", "npu cpu hybrid"))
    args.run_fracs = number_list(" ".join(map(str, args.run_fracs)) if args.run_fracs is not None
                                 else os.getenv("RUN_FRACS", "0"), "RUN_FRACS", 0.0, float)
    args.cpu_fracs = number_list(" ".join(map(str, args.cpu_fracs)) if args.cpu_fracs is not None
                                 else os.getenv("CPU_FRACS", "0.25 0.5 0.75"), "CPU_FRACS", 0.0, float)
    modes = " ".join(args.hybrid_modes) if args.hybrid_modes is not None else os.getenv("HYBRID_MODES", "overlap")
    args.hybrid_modes = modes.split()
    if not args.hybrid_modes or any(mode not in HYBRID_MODES for mode in args.hybrid_modes):
        raise ValueError(f"hybrid modes must be entries of {HYBRID_MODES}.")
    if any(frac > 1.0 for frac in args.run_fracs + args.cpu_fracs):
        raise ValueError("run-fracs and cpu-fracs must not exceed 1.0.")
    if max(args.cards) > len(visible):
        raise ValueError(f"Requested {max(args.cards)} dies, but only {len(visible)} devices are visible.")
    args.numa_nodes = [int(part) for part in args.numa_nodes.replace(",", " ").split()]
    if args.numa_nodes and max(args.cards) > len(args.numa_nodes):
        raise ValueError("NUMA sweep needs at least as many node ids as the largest --cards value.")
    if os.getenv("DTYPES", DTYPE).split() != [DTYPE]:
        raise ValueError(f"The scheme sweep uses {DTYPE}; DTYPES must be {DTYPE} if set.")
    for batch in args.batch_size:
        for count in args.copy_count:
            validate_workload(argparse.Namespace(**{**vars(args), "batch_size": batch,
                                                    "copy_min": count, "copy_max": count}))
    args.results_dir = args.results_dir.resolve()
    return args


def case_name(scheme: str, cards: int, batch: int, copies: int, run_frac: float,
              cpu_frac: float | None, hybrid_mode: str | None, numa: bool) -> str:
    name = f"{scheme}_cards{cards}_bs{batch}_copy{copies}_rf{str(run_frac).replace('.', 'p')}"
    if scheme == "hybrid":
        name += f"_cf{str(cpu_frac).replace('.', 'p')}_{hybrid_mode}"
    if numa:
        name += "_numa"
    return name


def cases(args):
    numa_options = (False, True) if args.numa_nodes else (False,)
    for scheme in args.schemes:
        for run_frac in args.run_fracs:
            cpu_options = [(frac, mode) for frac in args.cpu_fracs for mode in args.hybrid_modes] \
                if scheme == "hybrid" else [(None, None)]
            for cpu_frac, hybrid_mode in cpu_options:
                for numa in numa_options:
                    for cards in args.cards:
                        for batch in args.batch_size:
                            for copies in args.copy_count:
                                name = case_name(scheme, cards, batch, copies, run_frac, cpu_frac, hybrid_mode, numa)
                                output = args.results_dir / f"{name}.json"
                                command = [sys.executable, str(ROOT / "tests/run_scheme_multiprocess.py"),
                                           "--cards", str(cards), "--batch-size", str(batch),
                                           "--copy-count", str(copies),
                                           "--source-len", str(args.source_len), "--hbm-slots", str(args.hbm_slots),
                                           "--copy-cap", str(args.copy_cap), "--warmup", str(args.warmup),
                                           "--iters", str(args.iters), "--seed", str(args.seed), "--same-seed",
                                           "--scheme", scheme, "--run-frac", str(run_frac),
                                           "--cpu-threads", str(args.cpu_threads),
                                           "--output", str(output)]
                                if scheme == "hybrid":
                                    command += ["--cpu-frac", str(cpu_frac), "--hybrid-mode", hybrid_mode]
                                if args.pretouch:
                                    command.append("--pretouch")
                                env_extra = {}
                                if numa:
                                    env_extra[NUMA_ENV] = ",".join(str(node) for node in args.numa_nodes[:cards])
                                yield name, output, command, env_extra


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def run(args) -> None:
    planned = list(cases(args))
    if args.dry_run:
        print(f"ASCEND_RT_VISIBLE_DEVICES={args.visible_devices} dtype={DTYPE} "
              f"queue_depth={os.environ.get(QUEUE_DEPTH_ENV, 'default')} cases={len(planned)}")
        for name, _, command, env_extra in planned:
            prefix = " ".join(f"{key}={value}" for key, value in env_extra.items())
            print(f"{prefix + ' ' if prefix else ''}{shlex.join(command)}")
        return
    args.results_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.results_dir / MANIFEST_NAME
    manifest = {"schema_version": 2, "status": "running", "dtype": DTYPE,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "visible_devices": args.visible_devices,
                "queue_depth": os.environ.get(QUEUE_DEPTH_ENV, "default"),
                "case_files": [output.name for _, output, _, _ in planned]}
    write_json(manifest_path, manifest)
    env = os.environ.copy()
    env["ASCEND_RT_VISIBLE_DEVICES"] = args.visible_devices
    env["SCATTER_ROOT"] = str(SCATTER_ROOT)
    env["PYTHONPATH"] = str(SCATTER_ROOT / "torch_extension") + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    try:
        for name, output, command, env_extra in planned:
            print(f"Running {name}; log={output.with_suffix('.log')}", flush=True)
            # A failed rerun must never leave a prior successful result behind.
            write_json(output, {"status": "running"})
            case_env = {**env, **env_extra}
            with output.with_suffix(".log").open("w", encoding="utf-8") as log:
                completed = subprocess.run(command, cwd=ROOT, env=case_env, stdout=log,
                                           stderr=subprocess.STDOUT, check=False)
            if completed.returncode:
                write_json(output, {"status": "failed", "returncode": completed.returncode})
                print("".join(output.with_suffix(".log").read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)[-30:]), end="", file=sys.stderr)
                raise RuntimeError(f"{name} failed; see {output.with_suffix('.log')}")
        manifest["status"] = "passed"
        write_json(manifest_path, manifest)
        scheme_report.analyze(args.results_dir)
    except BaseException:
        manifest["status"] = "failed"
        write_json(manifest_path, manifest)
        raise


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""CPU-only regression tests for the scheme bench: workload semantics, hybrid
splitting, report math and CLI surfaces. No Torch, no CANN, no NPU required."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import _bootstrap

_bootstrap.ensure_importable()

from scatter_config import BYTES_PER_TOKEN, COPY_CAP_DEFAULT  # noqa: E402

import run_scheme_sweep  # noqa: E402
import scheme_churn  # noqa: E402
import scheme_churn_synth  # noqa: E402
import scheme_report  # noqa: E402
import scheme_workload as wl  # noqa: E402
import test_scheme_worker  # noqa: E402
from run_scheme_multiprocess import numactl_nodes  # noqa: E402
from run_scheme_multiprocess import parse_args as runner_parse_args  # noqa: E402
from scheme_config import MANIFEST_NAME, MULTIPROCESS_TEST, NUMA_ENV, SINGLE_TEST  # noqa: E402

BLOCK = 128


def fixture(latencies=(10.0, 30.0), batch=3, copies=7, scheme="cpu", run_frac=0.0, cpu_frac=0.0):
    config = dict(dtype="c8", batch_size=batch, source_len=65536, hbm_slots=8192,
                  copy_min=copies, copy_max=copies, copy_cap=COPY_CAP_DEFAULT,
                  warmup=0, iters=5, seed=7, scheme=scheme, run_frac=run_frac,
                  cpu_frac=cpu_frac, hybrid_mode="overlap")
    workers = []
    for rank, latency in enumerate(latencies):
        workers.append({
            "status": "passed", "test": SINGLE_TEST,
            "config": {**config, "device": f"npu:{rank}"}, "rank": rank,
            "correctness": {"data_exact": True},
            "workload": {"copied_tokens": batch * copies,
                         "payload_bytes_per_iteration": batch * copies * BYTES_PER_TOKEN},
            "performance": {"avg_us": latency},
        })
    return {"status": "passed", "test": MULTIPROCESS_TEST, "device_count": len(workers),
            "config": config, "summary": {"all_correct": True}, "per_device": workers}


class WorkloadTests(unittest.TestCase):
    def test_determinism_and_uniqueness_and_bounds(self):
        kwargs = dict(batch_size=4, source_len=4096, hbm_slots=1024,
                      copy_min=0, copy_max=50, copy_cap=COPY_CAP_DEFAULT, seed=7)
        first = wl.gen_copy_lists(**kwargs)
        second = wl.gen_copy_lists(**kwargs)
        self.assertEqual(first, second)
        counts, src_rows, dst_rows = first
        self.assertEqual(counts[0], 0)   # row 0 pins copy_min
        self.assertEqual(counts[1], 50)  # row 1 pins copy_max
        for count, src, dst in zip(counts, src_rows, dst_rows):
            self.assertEqual((len(src), len(dst)), (count, count))
            self.assertEqual(len(set(src)), count)
            self.assertEqual(len(set(dst)), count)
            self.assertTrue(all(0 <= t < 4096 for t in src))
            self.assertTrue(all(0 <= t < 1024 for t in dst))

    def test_run_frac_locality(self):
        _, src_rows, _ = wl.gen_copy_lists(batch_size=2, source_len=1 << 20, hbm_slots=2048,
                                           copy_min=2000, copy_max=2000, copy_cap=COPY_CAP_DEFAULT,
                                           seed=3, run_frac=0.8)
        measured = wl.measured_run_frac(src_rows[0])
        self.assertGreater(measured, 0.7)
        self.assertLess(measured, 0.9)
        _, discrete, _ = wl.gen_copy_lists(batch_size=2, source_len=1 << 20, hbm_slots=2048,
                                           copy_min=2000, copy_max=2000, copy_cap=COPY_CAP_DEFAULT,
                                           seed=3, run_frac=0.0)
        self.assertLess(wl.measured_run_frac(discrete[0]), 0.01)

    def test_invalid_requests(self):
        with self.assertRaises(ValueError):
            wl.gen_copy_lists(batch_size=1, source_len=100, hbm_slots=100,
                              copy_min=0, copy_max=101, copy_cap=COPY_CAP_DEFAULT, seed=7)
        with self.assertRaises(ValueError):
            wl.gen_src_row(5, 10, __import__("random").Random(0), run_frac=1.5)
        with self.assertRaises(ValueError):
            wl.split_hybrid([1], [[1]], [[2]], 1.5)

    def test_resolve_and_gather_reference(self):
        table = [5, 0, 7, 1]
        self.assertEqual(wl.resolve_phys_rows(table, [0, 129, 257], BLOCK),
                         [5 * BLOCK + 0, 0 * BLOCK + 1, 7 * BLOCK + 1])
        pool = [bytes([i]) * 4 for i in range(8)]
        self.assertEqual(wl.gather_rows(pool, [3, 0, 3]), [pool[3], pool[0], pool[3]])

    def test_block_tables(self):
        import random
        dram, hbm = wl.gen_block_tables(3, 512, 256, BLOCK, random.Random(1))
        self.assertEqual(len(dram), 3)
        self.assertEqual(sorted(dram[0]), [0, 1, 2, 3])
        flat = [block for row in hbm for block in row]
        self.assertEqual(len(flat), 3 * 2)
        self.assertEqual(len(set(flat)), 3 * 2)  # private destinations + guard


class HybridSplitTests(unittest.TestCase):
    def test_copy_zero_rows_are_empty_everywhere(self):
        # R1 regression: cpu/hybrid at copy=0 must see empty shares end to end.
        counts, src, dst = wl.gen_copy_lists(batch_size=3, source_len=1024, hbm_slots=256,
                                             copy_min=0, copy_max=0, copy_cap=COPY_CAP_DEFAULT, seed=7)
        self.assertEqual(counts, [0, 0, 0])
        self.assertTrue(all(not row for row in src + dst))
        split = wl.split_hybrid(counts, src, dst, 0.5)
        self.assertEqual(split["kernel_counts"], [0, 0, 0])
        self.assertEqual(split["cpu_counts"], [0, 0, 0])

    def test_prefix_tail_partition(self):
        counts = [10, 0, 7]
        src = [list(range(10)), [], list(range(100, 107))]
        dst = [list(range(50, 60)), [], list(range(200, 207))]
        split = wl.split_hybrid(counts, src, dst, 0.3)
        self.assertEqual(split["kernel_counts"], [7, 0, 5])
        self.assertEqual(split["cpu_counts"], [3, 0, 2])
        for row in range(3):
            self.assertEqual(split["kernel_src"][row] + split["cpu_src"][row], src[row])
            self.assertEqual(split["kernel_dst"][row] + split["cpu_dst"][row], dst[row])

    def test_extreme_fracs(self):
        counts, src, dst = [4], [[1, 2, 3, 4]], [[5, 6, 7, 8]]
        self.assertEqual(wl.split_hybrid(counts, src, dst, 0.0)["kernel_counts"], [4])
        split = wl.split_hybrid(counts, src, dst, 1.0)
        self.assertEqual(split["kernel_counts"], [0])
        self.assertEqual(split["cpu_src"], src)

    def test_row_length_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            wl.split_hybrid([2], [[1]], [[1, 2]], 0.5)


class ChurnTests(unittest.TestCase):
    def test_constant_set_full_overlap(self):
        lines = [json.dumps(list(range(100))) for _ in range(10)]
        report = scheme_churn.analyze_trace(lines, 128, (1.0, 2.0))
        stats = report["None"]
        self.assertEqual(stats["adjacent_overlap"]["mean"], 1.0)
        # LRU cold start: the first step misses, the remaining 9 hit.
        self.assertAlmostEqual(stats["residency"]["1x"]["hit_rate"], 0.9)

    def test_cyclic_lru_sharp_threshold(self):
        # Four disjoint sets cycled forever: 3x capacity never hits, 4x always hits
        # after the first cycle (cold-start misses = 4/40 of all accesses).
        sets = [list(range(i * 50, (i + 1) * 50)) for i in range(4)]
        lines = [json.dumps(sets[i % 4]) for i in range(40)]
        report = scheme_churn.analyze_trace(lines, 128, (3.0, 4.0))
        self.assertEqual(report["None"]["residency"]["3x"]["hit_rate"], 0.0)
        self.assertAlmostEqual(report["None"]["residency"]["4x"]["hit_rate"], 0.9)
        self.assertEqual(report["None"]["adjacent_overlap"]["mean"], 0.0)

    def test_partial_overlap_and_blocks(self):
        lines = [json.dumps({"step": 0, "layer": 3, "indices": [0, 1, 128, 200]}),
                 json.dumps({"step": 1, "layer": 3, "indices": [0, 1, 300, 400]})]
        report = scheme_churn.analyze_trace(lines, 128, (1.0,))
        stats = report["3"]
        self.assertEqual(stats["adjacent_overlap"]["mean"], 0.5)
        self.assertEqual(stats["blocks"]["mean_blocks_per_step"], 2.5)

    def test_bad_input_rejected(self):
        with self.assertRaises(ValueError):
            scheme_churn.analyze_trace([], 128, (1.0,))
        with self.assertRaises(ValueError):
            scheme_churn.analyze_trace(['{"no_indices": 1}'], 128, (1.0,))
        with self.assertRaises(ValueError):
            scheme_churn.analyze_trace(['[1,2]'], 0, (1.0,))


class ChurnSynthTests(unittest.TestCase):
    def test_keep_one_constant_set(self):
        records = scheme_churn_synth.gen_trace(steps=10, k=100, keep=1.0, seed=7)
        report = scheme_churn.analyze_trace([json.dumps(r) for r in records], 128, (1.0,))
        self.assertEqual(report["None"]["adjacent_overlap"]["mean"], 1.0)

    def test_keep_zero_near_zero_overlap(self):
        records = scheme_churn_synth.gen_trace(steps=10, k=100, keep=0.0, seed=7)
        report = scheme_churn.analyze_trace([json.dumps(r) for r in records], 128, (1.0,))
        self.assertLess(report["None"]["adjacent_overlap"]["mean"], 0.05)

    def test_regime_shift_drops_overlap_once_per_period(self):
        # keep=1 within a regime, shift every 10 steps, 20 steps ->
        # 19 adjacent pairs: 18 kept, 1 broken.
        records = scheme_churn_synth.gen_trace(steps=20, k=100, keep=1.0,
                                               shift_every=10, seed=7)
        report = scheme_churn.analyze_trace([json.dumps(r) for r in records], 128, (1.0,))
        self.assertAlmostEqual(report["None"]["adjacent_overlap"]["mean"], 18 / 19)

    def test_determinism_and_uniqueness(self):
        first = scheme_churn_synth.gen_trace(steps=10, k=100, seed=7)
        second = scheme_churn_synth.gen_trace(steps=10, k=100, seed=7)
        self.assertEqual(first, second)
        for record in first:
            self.assertEqual(len(set(record["indices"])), 100)

    def test_layers_group_independently(self):
        records = scheme_churn_synth.gen_trace(steps=10, k=50, layers=3, seed=7)
        report = scheme_churn.analyze_trace([json.dumps(r) for r in records], 128, (1.0,))
        self.assertEqual(sorted(report), ["0", "1", "2"])
        for stats in report.values():
            self.assertEqual(stats["steps"], 10)

    def test_invalid_requests(self):
        for kwargs in ({"keep": 1.5}, {"hot_pool": 50}, {"vocab": 50, "hot_pool": 100},
                       {"steps": 0}, {"shift_every": -1}):
            base = {"steps": 10, "k": 100}
            base.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                scheme_churn_synth.gen_trace(**base)


class ReportTests(unittest.TestCase):
    def test_bandwidth_math_matches_blueprint(self):
        row = scheme_report.normalize_scheme_case(fixture())
        # Same numbers as the blueprint fixture: 21 tokens per die at 10/30 us.
        self.assertAlmostEqual(row["avg_bandwidth"], BYTES_PER_TOKEN * 0.0028)
        self.assertEqual((row["avg_us_mean"], row["avg_us_max"]), (20, 30))
        self.assertEqual((row["scheme"], row["run_frac"], row["cpu_frac"]), ("cpu", 0.0, 0.0))
        self.assertEqual(tuple(row), scheme_report.SCHEME_COLUMNS)

    def test_scheme_coordinates_and_defaults(self):
        row = scheme_report.normalize_scheme_case(fixture(scheme="hybrid", cpu_frac=0.5))
        self.assertEqual((row["scheme"], row["cpu_frac"]), ("hybrid", 0.5))
        legacy = fixture()
        del legacy["config"]["scheme"]
        del legacy["config"]["run_frac"]
        del legacy["config"]["cpu_frac"]
        del legacy["config"]["hybrid_mode"]
        for worker in legacy["per_device"]:
            for key in ("scheme", "run_frac", "cpu_frac", "hybrid_mode"):
                worker["config"].pop(key, None)
        row = scheme_report.normalize_scheme_case(legacy)
        self.assertEqual((row["scheme"], row["run_frac"]), ("npu", 0.0))

    def test_worker_scheme_mismatch_rejected(self):
        case = fixture()
        case["per_device"][0]["config"]["scheme"] = "npu"
        with self.assertRaisesRegex(ValueError, "inconsistent scheme"):
            scheme_report.normalize_scheme_case(case)

    def test_breakeven_model_math(self):
        import subprocess
        tool = Path(__file__).resolve().parents[1] / "tools/breakeven.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "npu0.json").write_text(json.dumps(fixture(scheme="npu", copies=0, latencies=(11.0,))))
            (root / "npu300.json").write_text(json.dumps(fixture(scheme="npu", copies=300, latencies=(138.7,))))
            (root / "cpu0.json").write_text(json.dumps(fixture(scheme="cpu", copies=0, latencies=(20.0,))))
            (root / "cpu300.json").write_text(json.dumps(fixture(scheme="cpu", copies=300, latencies=(500.0,))))
            out = subprocess.run([sys.executable, str(tool), str(root)],
                                 capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        # npu: T0=11, T_full=138.7, tokens=900 -> marginal=(138.7-11)/900=0.1419us=141.89ns
        self.assertIn("marginal=141.89ns/token", out.stdout)
        # rho=0.9 -> T_delta = 11 + 0.1*127.7 = 23.77 -> speedup 5.84x
        self.assertIn("rho=0.9  T_delta=    23.8us  speedup_vs_full= 5.84x", out.stdout)
        # crossover: rho* = 1 - (138.7-20)/(500-20) = 1 - 0.2473 = 0.7527
        self.assertIn("rho*=0.75 (cpu-delta wins for rho > 0.75)", out.stdout)

    def test_breakeven_skips_nonpassed_and_missing_endpoints(self):
        import subprocess
        tool = Path(__file__).resolve().parents[1] / "tools/breakeven.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failed = fixture(scheme="npu", copies=0)
            failed["status"] = "failed"
            (root / "failed.json").write_text(json.dumps(failed))
            out = subprocess.run([sys.executable, str(tool), str(root)],
                                 capture_output=True, text=True)
        self.assertIn("no passed case JSONs", out.stdout + out.stderr)

    def test_repeats_fold_into_one_row_with_std(self):
        import statistics
        from scatter_results import effective_bandwidth
        run1 = fixture(scheme="cpu", latencies=(10.0, 30.0))
        run2 = fixture(scheme="cpu", latencies=(20.0, 20.0))
        rows = scheme_report.build_rows([run1, run2])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["n_runs"], 2)
        tokens = 21  # batch 3 * copies 7, per die
        b1 = effective_bandwidth(tokens * BYTES_PER_TOKEN, 10.0) + effective_bandwidth(tokens * BYTES_PER_TOKEN, 30.0)
        b2 = 2 * effective_bandwidth(tokens * BYTES_PER_TOKEN, 20.0)
        self.assertAlmostEqual(row["avg_bandwidth"], statistics.fmean([b1, b2]))
        self.assertAlmostEqual(row["avg_bandwidth_std"], statistics.stdev([b1, b2]))
        distinct = scheme_report.build_rows([fixture(scheme="npu"), fixture(scheme="cpu")])
        self.assertEqual([row["scheme"] for row in distinct], ["cpu", "npu"])

    def test_analyze_writes_csv_md_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.json").write_text(json.dumps(fixture(scheme="npu")))
            (root / "b.json").write_text(json.dumps(fixture(scheme="cpu", latencies=(5.0,))))
            # b has a different device_count; fix device_count mismatch.
            with contextlib.redirect_stdout(io.StringIO()):
                rows = scheme_report.analyze(root)
            self.assertEqual(len(rows), 2)
            for suffix in (".csv", ".md"):
                self.assertTrue((root / f"copy_scheme_timing_summary{suffix}").exists())
            summary = json.loads((root / "copy_scheme_summary.json").read_text())
            self.assertEqual(tuple(summary["rows"][0]), scheme_report.SCHEME_COLUMNS)


class SweepCliTests(unittest.TestCase):
    def test_case_count_and_command_shape(self):
        with patch.dict(os.environ, {"TEST_VISIBLE_DEVICES": "0,1"}, clear=True):
            args = run_scheme_sweep.parse_args(
                ["--cards", "1", "2", "--batch-size", "3", "--copy-count", "0", "7",
                 "--cpu-fracs", "0.5"])
            planned = list(run_scheme_sweep.cases(args))
        # 2 cards * 1 bs * 2 copies * (npu + cpu + hybrid) = 12
        self.assertEqual(len(planned), 12)
        hybrid = [cmd for name, _, cmd, _ in planned if name.startswith("hybrid")]
        self.assertIn("--cpu-frac", hybrid[0])
        self.assertIn("--hybrid-mode", hybrid[0])

    def test_numa_doubles_matrix_and_binds_prefix(self):
        with patch.dict(os.environ, {"TEST_VISIBLE_DEVICES": "0,1"}, clear=True):
            args = run_scheme_sweep.parse_args(
                ["--cards", "2", "--batch-size", "3", "--copy-count", "7",
                 "--schemes", "npu", "--numa-nodes", "0 1"])
            planned = list(run_scheme_sweep.cases(args))
        self.assertEqual(len(planned), 2)
        bound = [extra for _, _, _, extra in planned if extra]
        self.assertEqual(bound[0][NUMA_ENV], "0,1")

    def test_invalid_requests_fail_before_launch(self):
        base = ["--cards", "1", "--batch-size", "3", "--copy-count", "7"]
        for extra in (["--schemes", "bogus"], ["--run-fracs", "1.5"], ["--cpu-fracs", "-0.5"],
                      ["--hybrid-modes", "bogus"], ["--cards", "9"],
                      ["--cards", "2", "--numa-nodes", "0"]):
            with self.subTest(extra=extra), patch.dict(os.environ, {"TEST_VISIBLE_DEVICES": "0,1"}, clear=True):
                with self.assertRaises(ValueError):
                    run_scheme_sweep.parse_args(base + extra)

    def test_repeat_expands_cases(self):
        with patch.dict(os.environ, {"TEST_VISIBLE_DEVICES": "0,1"}, clear=True):
            args = run_scheme_sweep.parse_args(
                ["--cards", "1", "--batch-size", "3", "--copy-count", "7",
                 "--schemes", "npu", "--repeat", "3"])
            planned = list(run_scheme_sweep.cases(args))
        self.assertEqual(len(planned), 3)
        self.assertEqual([name.rsplit("_r", 1)[1] for name, _, _, _ in planned], ["1", "2", "3"])

    def test_dry_run_prints_without_touching_results_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"TEST_VISIBLE_DEVICES": "0,1"}, clear=True):
                args = run_scheme_sweep.parse_args(
                    ["--cards", "1", "--batch-size", "3", "--copy-count", "7",
                     "--schemes", "npu", "cpu", "--results-dir", directory, "--dry-run"])
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    run_scheme_sweep.run(args)
            self.assertIn("cases=2", out.getvalue())
            self.assertEqual(list(Path(directory).iterdir()), [])


class RunnerCliTests(unittest.TestCase):
    def test_default_output_naming(self):
        argv = ["test", "--cards", "2", "--batch-size", "17", "--copy-count", "321",
                "--scheme", "hybrid", "--cpu-frac", "0.25"]
        with patch.object(sys, "argv", argv), patch.dict(os.environ, {}, clear=True):
            args = runner_parse_args()
        self.assertEqual(args.output.name, "hybrid_cards2_bs17_copy321_rf0_cf0p25_overlap.json")
        argv = ["test", "--cards", "1", "--copy-count", "10", "--scheme", "npu", "--run-frac", "0.5"]
        with patch.object(sys, "argv", argv), patch.dict(os.environ, {}, clear=True):
            args = runner_parse_args()
        self.assertEqual(args.output.name, "npu_cards1_bs24_copy10_rf0p5.json")

    def test_numactl_node_validation(self):
        with patch.dict(os.environ, {NUMA_ENV: "0,1"}, clear=True):
            self.assertEqual(numactl_nodes([0, 1]), ["0", "1"])
            with self.assertRaises(ValueError):
                numactl_nodes([0])
        with patch.dict(os.environ, {NUMA_ENV: ""}, clear=True):
            self.assertEqual(numactl_nodes([0]), [])

    def test_runner_aggregates_simulated_workers(self):
        import run_scheme_multiprocess as runner
        commands = []

        class FakeProcess:
            returncode = 0

            def __init__(self, command, **kwargs):
                commands.append(command)
                values = dict(zip(command[2::2], command[3::2]))
                rank = int(values["--device"].split(":")[1])
                data = fixture(scheme=values["--scheme"])["per_device"][rank]
                for key in ("batch-size", "source-len", "hbm-slots", "copy-min", "copy-max",
                            "copy-cap", "warmup", "iters", "seed", "cpu-threads"):
                    data["config"][key.replace("-", "_")] = int(values[f"--{key}"])
                for key in ("--run-frac", "--cpu-frac"):
                    data["config"][key[2:].replace("-", "_")] = float(values[key])
                data["config"]["hybrid_mode"] = values["--hybrid-mode"]
                for name in ("--ready-file", "--timing-ready-file"):
                    Path(values[name]).write_text("ready\n")
                Path(values["--json-output"]).write_text(json.dumps(data))

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return 0

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "case.json"
            argv = ["test", "--cards", "2", "--batch-size", "3", "--copy-count", "7",
                    "--scheme", "cpu", "--cpu-threads", "4",
                    "--warmup", "0", "--iters", "5", "--same-seed", "--output", str(output)]
            with patch.object(sys, "argv", argv), \
                    patch.dict(os.environ, {"ASCEND_RT_VISIBLE_DEVICES": "4,9"}, clear=True), \
                    patch.object(runner.subprocess, "Popen", FakeProcess), \
                    contextlib.redirect_stdout(io.StringIO()) as log:
                runner.main()
            result = json.loads(output.read_text())
            self.assertEqual(result["test"], MULTIPROCESS_TEST)
            self.assertEqual(result["devices"], [0, 1])
            self.assertEqual(result["config"]["scheme"], "cpu")
            self.assertEqual(result["summary"]["avg_us_mean"], 20)
            self.assertAlmostEqual(result["summary"]["avg_bandwidth"], BYTES_PER_TOKEN * 0.0028)
            self.assertEqual(tuple(scheme_report.normalize_scheme_case(result)),
                             scheme_report.SCHEME_COLUMNS)
            self.assertIn("avg_bandwidth", log.getvalue())
            self.assertEqual(len(commands), 2)
            self.assertIn("--cpu-threads", commands[0])


class WorkerCliTests(unittest.TestCase):
    def test_quantiles_helper(self):
        q = test_scheme_worker._quantiles([float(i) for i in range(1, 101)])
        self.assertEqual((q["min"], q["max"], q["n"]), (1.0, 100.0, 100))
        self.assertAlmostEqual(q["mean"], 50.5)
        self.assertEqual((q["p50"], q["p90"], q["p99"]), (51.0, 91.0, 100.0))

    def test_parse_and_validate_without_torch(self):
        args = test_scheme_worker.parse_args(["--scheme", "cpu", "--cpu-threads", "16",
                                              "--run-frac", "0.5", "--copy-count", "200"])
        self.assertEqual((args.scheme, args.cpu_threads, args.copy_min, args.copy_max),
                         ("cpu", 16, 200, 200))
        test_scheme_worker.validate_scheme_args(args)
        for bad in (["--run-frac", "1.5"], ["--cpu-frac", "-0.1"], ["--cpu-threads", "0"]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    test_scheme_worker.validate_scheme_args(test_scheme_worker.parse_args(bad))


if __name__ == "__main__":
    unittest.main()

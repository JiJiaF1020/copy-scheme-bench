#!/usr/bin/env python3
"""First-order break-even model for top-K residency (delta copy).

Per-token marginal copy cost is read off the measured matrix: the copy=0 case
of a scheme gives its fixed per-step overhead T0 (launch + sync), and
c = (T(copy) - T0) / tokens gives the marginal cost per token. Delta copying at
adjacent-step overlap rho then predicts

    T_delta(rho) = T0 + (1 - rho) * (T_full - T0)

per scheme. Also prints rho*, the overlap at which cpu-delta crosses npu-full.

Input: a results directory of case JSONs (status=="passed" only; the sweep
manifest is not required, so partially-completed runs are analyzable).
Pure stdlib; runs anywhere.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

import scheme_report  # noqa: E402

RHOS = (0.0, 0.2, 0.4, 0.6, 0.8, 0.9, 0.95)


def load_passed_rows(results_dir: Path) -> list[dict]:
    cases = []
    for path in sorted(results_dir.glob("*.json")):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(case, dict) and case.get("status") == "passed" and "per_device" in case:
            cases.append(case)
    if not cases:
        return []
    return scheme_report.build_rows(cases)


def model(rows: list[dict]) -> list[str]:
    lines = []
    by_key = {(row["scheme"], int(row["cards"]), int(row["batch_size"])): row for row in rows}
    schemes = sorted({row["scheme"] for row in rows})
    coords = sorted({(int(row["cards"]), int(row["batch_size"])) for row in rows})
    for cards, batch in coords:
        for scheme in schemes:
            zero = next((row for row in rows
                         if row["scheme"] == scheme and int(row["cards"]) == cards
                         and int(row["batch_size"]) == batch and str(row["copy_count"]) == "0"), None)
            if zero is None:
                continue
            t0 = float(zero["avg_us_mean"])
            for row in rows:
                if (row["scheme"], int(row["cards"]), int(row["batch_size"])) != (scheme, cards, batch):
                    continue
                copy_count = row["copy_count"]
                if not isinstance(copy_count, int) or copy_count <= 0:
                    continue
                tokens = batch * copy_count
                t_full = float(row["avg_us_mean"])
                marginal = (t_full - t0) / tokens
                if marginal <= 0:
                    lines.append(f"cards{cards} bs{batch} {scheme} copy{copy_count}: "
                                 f"T0={t0:.1f}us >= T_full={t_full:.1f}us; overhead-dominated, modeling skipped")
                    continue
                lines.append(f"cards{cards} bs{batch} {scheme} copy{copy_count}: "
                             f"T0={t0:.1f}us T_full={t_full:.1f}us marginal={marginal * 1000:.2f}ns/token")
                for rho in RHOS:
                    t_delta = t0 + (1 - rho) * (t_full - t0)
                    lines.append(f"    rho={rho:<4} T_delta={t_delta:8.1f}us  speedup_vs_full={t_full / t_delta:5.2f}x")
        # crossover: cpu-delta vs npu-full at the largest copy count available
        npu_rows = [row for row in rows if row["scheme"] == "npu"
                    and int(row["cards"]) == cards and int(row["batch_size"]) == batch
                    and isinstance(row["copy_count"], int) and row["copy_count"] > 0]
        cpu_rows = [row for row in rows if row["scheme"] == "cpu"
                    and int(row["cards"]) == cards and int(row["batch_size"]) == batch
                    and isinstance(row["copy_count"], int) and row["copy_count"] > 0]
        npu_zero = next((row for row in rows if row["scheme"] == "npu" and int(row["cards"]) == cards
                         and int(row["batch_size"]) == batch and str(row["copy_count"]) == "0"), None)
        cpu_zero = next((row for row in rows if row["scheme"] == "cpu" and int(row["cards"]) == cards
                         and int(row["batch_size"]) == batch and str(row["copy_count"]) == "0"), None)
        if npu_rows and cpu_rows and npu_zero and cpu_zero:
            cpu_by_copy = {row["copy_count"]: row for row in cpu_rows}
            for npu_row in sorted(npu_rows, key=lambda r: r["copy_count"]):
                cpu_row = cpu_by_copy.get(npu_row["copy_count"])
                if cpu_row is None:
                    continue  # pair strictly by copy_count; zip would misalign asymmetric sets
                t_npu = float(npu_row["avg_us_mean"])
                t0_cpu = float(cpu_zero["avg_us_mean"])
                span_cpu = float(cpu_row["avg_us_mean"]) - t0_cpu
                if span_cpu <= 0:
                    continue
                rho_star = 1 - (t_npu - t0_cpu) / span_cpu
                # rho* < 0: cpu-full (rho=0) already beats npu-full; rho* > 1:
                # even cpu's fixed cost T0 exceeds npu-full.
                verdict = ("cpu-delta wins for rho > " f"{rho_star:.2f}" if 0 <= rho_star <= 1
                           else ("cpu-delta always wins" if rho_star < 0 else "cpu-delta never wins"))
                lines.append(f"  crossover cards{cards} bs{batch} copy{npu_row['copy_count']}: "
                             f"npu_full={t_npu:.1f}us vs cpu(T0={t0_cpu:.1f}, span={span_cpu:.1f}) "
                             f"=> rho*={rho_star:.2f} ({verdict})")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_dir", type=Path)
    args = parser.parse_args()
    rows = load_passed_rows(args.results_dir)
    if not rows:
        raise SystemExit(f"no passed case JSONs in {args.results_dir}")
    for line in model(rows):
        print(line)


if __name__ == "__main__":
    main()

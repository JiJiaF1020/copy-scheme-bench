#!/usr/bin/env python3
"""Per-coordinate repeat spread (极差) for sweep results.

Folds repeats of one coordinate and reports, per coordinate: n_runs, the
individual avg_bandwidth values, mean, sample stddev, and spread
((max-min)/min) — the exact metric the R5+ 判读预案 uses to flag
「不稳」(spread > 10%). Non-invasive companion to scheme_report (which folds
to mean+std only); reads the same case JSONs, so it can analyze any past
results directory retroactively.

Usage: tools/repeat_spread.py <results_dir> [<results_dir> ...]
Pure stdlib; runs anywhere (no NPU needed).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

import scheme_report  # noqa: E402


def collect(results_dir: Path) -> dict[tuple, list[float]]:
    groups: dict[tuple, list[float]] = {}
    for path in sorted(results_dir.rglob("*.json")):
        try:
            case = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(case, dict) or "summary" not in case or "config" not in case:
            continue
        try:
            row = scheme_report.normalize_scheme_case(case)
        except (KeyError, TypeError, ValueError):
            continue
        key = scheme_report.sort_key(row)
        groups.setdefault(key, []).append(float(row["avg_bandwidth"]))
    return groups


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_dirs", nargs="+", type=Path)
    args = parser.parse_args()

    for results_dir in args.results_dirs:
        groups = collect(results_dir)
        print(f"# {results_dir}")
        print(f"{'coordinate':<44} {'n':>2} {'mean':>9} {'std':>8} {'spread%':>8}  runs")
        for key in sorted(groups):
            bandwidths = groups[key]
            mean = statistics.fmean(bandwidths)
            std = statistics.stdev(bandwidths) if len(bandwidths) > 1 else 0.0
            low, high = min(bandwidths), max(bandwidths)
            spread = (high - low) / low * 100.0 if low > 0 else 0.0
            label = "/".join(str(part) for part in key)
            runs = " ".join(f"{b:.2f}" for b in bandwidths)
            flag = "  <-- UNSTABLE" if spread > 10.0 else ""
            print(f"{label:<44} {len(bandwidths):>2} {mean:>9.3f} {std:>8.3f} "
                  f"{spread:>7.2f}%  {runs}{flag}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

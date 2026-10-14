#!/usr/bin/env python3
"""CLI for top-K churn / residency analysis. Pure stdlib; runs anywhere.

  python3 tools/churn_analysis.py trace.jsonl [--block-size 128] [--json out.json]

Trace format: one JSON per line, {"step": int, "layer": int (optional),
"indices": [token ids]}; a bare list of indices per line also works.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

import scheme_churn  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--block-size", type=int, default=128)
    parser.add_argument("--multipliers", nargs="+", type=float, default=[1.0, 1.5, 2.0, 3.0, 4.0])
    parser.add_argument("--json", type=Path, help="Also write the full report here.")
    args = parser.parse_args()
    report = scheme_churn.analyze_trace(args.trace.read_text(encoding="utf-8").splitlines(),
                                        args.block_size, tuple(args.multipliers))
    for layer, stats in report.items():
        print(f"layer={layer} steps={stats['steps']} k_mean={stats['k_mean']}")
        overlap = stats["adjacent_overlap"]
        print(f"  adjacent-step overlap rho: mean={overlap['mean']:.3f} "
              f"min={overlap['min']:.3f} max={overlap['max']:.3f}")
        for mult, residency in stats["residency"].items():
            print(f"  hot buffer {mult} (cap {residency['capacity']}): "
                  f"hit_rate={residency['hit_rate']:.3f} "
                  f"(hits={residency['hits']} misses={residency['misses']})")
        blocks = stats["blocks"]
        print(f"  blocks/step={blocks['mean_blocks_per_step']:.1f} "
              f"tokens/touched-block={blocks['mean_tokens_per_touched_block']:.2f}")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
        print(f"Saved: {args.json}")


if __name__ == "__main__":
    main()

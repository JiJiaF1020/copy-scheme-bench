#!/usr/bin/env python3
"""CLI for the synthetic top-K trace generator. Pure stdlib; runs anywhere.

  python3 tools/churn_synth.py --steps 2000 --k 2048 --keep 0.85 \
      --layers 61 --out trace.jsonl

Feed the output to tools/churn_analysis.py. All knobs map to serving
phenomena: --keep = per-step retention (adjacent overlap rho), --hot-pool =
active vocabulary size, --shift-every = regime-change period (0 = never),
--layers = independent per-layer indexer chains.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

import scheme_churn_synth  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, required=True)
    parser.add_argument("--k", type=int, required=True, help="top-K per step")
    parser.add_argument("--vocab", type=int, default=1 << 20)
    parser.add_argument("--keep", type=float, default=0.85)
    parser.add_argument("--hot-pool", type=int, default=None)
    parser.add_argument("--shift-every", type=int, default=0)
    parser.add_argument("--layers", type=int, default=1)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    records = scheme_churn_synth.gen_trace(args.steps, args.k, args.vocab,
                                           args.keep, args.hot_pool,
                                           args.shift_every, args.layers,
                                           args.seed)
    with args.out.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")
    print(f"Saved: {args.out} ({len(records)} records)")


if __name__ == "__main__":
    main()

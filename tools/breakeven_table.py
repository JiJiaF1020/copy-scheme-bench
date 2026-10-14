#!/usr/bin/env python3
"""Break-even model from a pasted copy_scheme_timing_summary markdown table.

results/ is gitignored, so green-zone deliveries carry the summary as pasted
markdown; this parses that table (or any copy_scheme_timing_summary.md) into
rows and runs the same model as tools/breakeven.py. Pure stdlib.

  python3 tools/breakeven_table.py table.md   # or pipe: ... | breakeven_table.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))          # tools/ (breakeven)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

import breakeven  # noqa: E402
import scheme_report  # noqa: E402

TYPES = {"scheme": str, "run_frac": float, "cpu_frac": float,
         "hybrid_mode": str, "cards": int, "batch_size": int,
         "copy_count": int, "avg_us_mean": float, "avg_us_max": float,
         "avg_bandwidth": float}


def parse_md_table(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells[0] == "scheme" or all(set(cell) <= set("-:") for cell in cells):
            continue
        if len(cells) != len(scheme_report.SCHEME_COLUMNS):
            continue
        row = {}
        for key, cell in zip(scheme_report.SCHEME_COLUMNS, cells):
            try:
                row[key] = TYPES[key](cell)
            except ValueError:
                break  # not a data row (e.g. prose that happens to start with |)
        else:
            rows.append(row)
    if not rows:
        raise ValueError("no summary rows found in input")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("table", type=Path, nargs="?",
                        help="markdown table file; stdin when omitted")
    args = parser.parse_args()
    text = (args.table.read_text(encoding="utf-8") if args.table
            else sys.stdin.read())
    for line in breakeven.model(parse_md_table(text)):
        print(line)


if __name__ == "__main__":
    main()

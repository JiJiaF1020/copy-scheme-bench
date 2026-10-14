"""Locate the nanovllm-scatter_copy blueprint repo and expose its tests/ modules.

The scheme bench reuses the blueprint's six-column result math, CLI validators
and shared constants by import instead of copying them, so the two suites can
never drift apart. Set SCATTER_ROOT when the blueprint is not a sibling dir.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
BENCH_TESTS = Path(__file__).resolve().parent


def scatter_root() -> Path:
    value = os.environ.get("SCATTER_ROOT", "").strip()
    root = Path(value).expanduser() if value else BENCH_ROOT.parent / "nanovllm-scatter_copy"
    if not (root / "tests" / "scatter_results.py").is_file():
        raise RuntimeError(
            f"nanovllm-scatter_copy blueprint not found at {root}; "
            "set the SCATTER_ROOT environment variable to its checkout."
        )
    return root.resolve()


def ensure_importable() -> Path:
    root = scatter_root()
    for path in (str(BENCH_TESTS), str(root / "tests")):
        if path not in sys.path:
            sys.path.insert(0, path)
    return root

"""Scheme-aware case normalization and reporting.

The six timing columns and their math (per-die rate sum, decimal GB/s) are
imported from the blueprint suite unchanged; this module only adds the scheme
coordinates (scheme/run_frac/cpu_frac/hybrid_mode) around them.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import _bootstrap

_bootstrap.ensure_importable()

from scatter_config import BYTES_PER_TOKEN, DTYPE  # noqa: E402
from scatter_results import copy_label, summarize_devices  # noqa: E402

from scheme_config import MANIFEST_NAME, MULTIPROCESS_TEST  # noqa: E402

SCHEME_COLUMNS = ("scheme", "run_frac", "cpu_frac", "hybrid_mode",
                  "cards", "batch_size", "copy_count",
                  "avg_us_mean", "avg_us_max", "avg_bandwidth")


def case_coordinates(config: dict) -> dict:
    """Scheme coordinates with npu/0/0 defaults so blueprint fixtures normalize."""
    return {
        "scheme": str(config.get("scheme", "npu")),
        "run_frac": float(config.get("run_frac", 0.0)),
        "cpu_frac": float(config.get("cpu_frac", 0.0)),
        "hybrid_mode": str(config.get("hybrid_mode", "overlap")),
    }


def normalize_scheme_case(case: dict) -> dict:
    if case.get("status") != "passed" or case.get("test") != MULTIPROCESS_TEST:
        raise ValueError(f"Expected a passing {MULTIPROCESS_TEST} result.")
    workers = case["per_device"]
    count = int(case["device_count"])
    if count < 1 or len(workers) != count:
        raise ValueError("device_count does not match per_device.")
    if case.get("summary", {}).get("all_correct") is not True:
        raise ValueError("Multiprocess correctness checks did not pass.")
    config = case.get("config", workers[0]["config"])
    label = copy_label(config)
    coords = case_coordinates(config)
    for item in workers:
        if item.get("status") != "passed" or any(value is False for value in item.get("correctness", {}).values()):
            raise ValueError("A worker did not pass its correctness checks.")
        worker_config = item["config"]
        if worker_config.get("row_bytes", BYTES_PER_TOKEN) != BYTES_PER_TOKEN:
            raise ValueError("Incorrect payload row size.")
        if worker_config.get("dtype") != DTYPE:
            raise ValueError(f"This bench reports only {DTYPE} results.")
        for key in ("batch_size", "copy_min", "copy_max", "source_len", "hbm_slots",
                    "copy_cap", "warmup", "iters", "scheme", "hybrid_mode"):
            if key in config and worker_config.get(key) != config[key]:
                raise ValueError(f"Workers have inconsistent {key} values.")
        for key in ("run_frac", "cpu_frac"):
            if key in config and abs(float(worker_config.get(key, 0.0)) - float(config[key])) > 1e-12:
                raise ValueError(f"Workers have inconsistent {key} values.")
        workload = item["workload"]
        tokens = int(workload["copied_tokens"])
        payload = int(workload["payload_bytes_per_iteration"])
        if tokens < 0 or payload != tokens * BYTES_PER_TOKEN:
            raise ValueError(f"Expected {BYTES_PER_TOKEN} effective bytes per copied token.")
        if isinstance(label, int) and tokens != int(config["batch_size"]) * label:
            raise ValueError("Actual copied tokens disagree with the fixed copy count.")
    return {
        **coords,
        "cards": count, "batch_size": int(config["batch_size"]), "copy_count": label,
        **summarize_devices(workers),
    }


def sort_key(row: dict) -> tuple:
    low, _, high = str(row["copy_count"]).partition("..")
    return (row["scheme"], float(row["run_frac"]), float(row["cpu_frac"]), row["hybrid_mode"],
            int(row["cards"]), int(row["batch_size"]), int(low), int(high or low))


def build_rows(cases: list[dict]) -> list[dict]:
    """Normalize case files; repeats of one coordinate fold into a single row.

    A sweep with --repeat N produces N files per coordinate. Each is normalized
    on its own, then the group folds to the mean, recording run-count and the
    sample stddev of avg_bandwidth (run-level fluctuation evidence).
    """
    normalized = [normalize_scheme_case(case) for case in cases]
    if not normalized:
        raise ValueError("No cases available for analysis.")
    groups: dict[tuple, list[dict]] = {}
    for row in normalized:
        groups.setdefault(sort_key(row), []).append(row)
    rows = []
    for key in sorted(groups):
        group = groups[key]
        if len(group) > 1:
            import statistics
            row = dict(group[0])
            row["avg_us_mean"] = statistics.fmean(float(item["avg_us_mean"]) for item in group)
            row["avg_us_max"] = statistics.fmean(float(item["avg_us_max"]) for item in group)
            bandwidths = [float(item["avg_bandwidth"]) for item in group]
            row["avg_bandwidth"] = statistics.fmean(bandwidths)
            row["n_runs"] = len(group)
            row["avg_bandwidth_std"] = statistics.stdev(bandwidths)
            rows.append(row)
        else:
            rows.append(group[0])
    return rows


def formatted_row(row: dict) -> dict[str, str]:
    cells = {}
    for key in SCHEME_COLUMNS:
        value = row[key]
        if key.startswith("avg_"):
            cells[key] = f"{float(value):.3f}"
        elif key in ("run_frac", "cpu_frac"):
            cells[key] = f"{float(value):g}"
        else:
            cells[key] = str(value)
    return cells


def format_table(rows: list[dict], markdown: bool = False) -> str:
    if not rows:
        raise ValueError("No rows to format.")
    cells = [formatted_row(row) for row in rows]
    if markdown:
        lines = ["| " + " | ".join(SCHEME_COLUMNS) + " |", "| " + " | ".join(["---:"] * len(SCHEME_COLUMNS)) + " |"]
        lines += ["| " + " | ".join(row[key] for key in SCHEME_COLUMNS) + " |" for row in cells]
    else:
        widths = {key: max(len(key), *(len(row[key]) for row in cells)) for key in SCHEME_COLUMNS}
        lines = ["  ".join(key.rjust(widths[key]) for key in SCHEME_COLUMNS)]
        lines += ["  ".join(row[key].rjust(widths[key]) for key in SCHEME_COLUMNS) for row in cells]
    return "\n".join(lines) + "\n"


def load_cases(results_dir: Path) -> tuple[list[Path], list[dict]]:
    manifest = results_dir / MANIFEST_NAME
    if manifest.exists():
        run = json.loads(manifest.read_text(encoding="utf-8"))
        if run.get("status") != "passed":
            raise ValueError("The latest sweep did not complete successfully; inspect its logs.")
        paths = [(results_dir / name).resolve() for name in run["case_files"]]
        if any(path.parent != results_dir.resolve() for path in paths):
            raise ValueError("Run manifest contains a path outside its results directory.")
    else:
        paths = sorted(path for path in results_dir.glob("*.json")
                       if path.name not in (MANIFEST_NAME, "copy_scheme_summary.json"))
    if not paths:
        raise FileNotFoundError(f"No case JSON files found in {results_dir}")
    return paths, [json.loads(path.read_text(encoding="utf-8")) for path in paths]


def analyze(results_dir: Path) -> list[dict]:
    paths, cases = load_cases(results_dir)
    rows = build_rows(cases)
    output = results_dir / "copy_scheme_timing_summary.csv"
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=SCHEME_COLUMNS)
        writer.writeheader()
        writer.writerows(formatted_row(row) for row in rows)
    output.with_suffix(".md").write_text(format_table(rows, markdown=True), encoding="utf-8")
    (results_dir / "copy_scheme_summary.json").write_text(json.dumps({
        "schema_version": 2, "columns": SCHEME_COLUMNS, "case_count": len(rows),
        "case_files": [str(path.name) for path in paths], "rows": rows,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(format_table(rows), end="")
    print(f"Saved: {output}")
    return rows

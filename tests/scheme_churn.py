"""Top-K churn / residency analysis (pure stdlib).

Answers the set-level question: how much of step t's top-K set was already
selected at step t-1, and what hit rate would an HBM-resident hot buffer of
m x k tokens buy us. Input traces come from a real serving run (one JSON per
line: {"step": int, "layer": int (optional), "indices": [token ids]} — a bare
list of indices per line also accepted). No Torch, no CANN.
"""

from __future__ import annotations

import json
from collections import defaultdict


def parse_trace(lines) -> dict:
    """Group index lists by layer (None when absent); steps sorted by step id."""
    groups: dict = defaultdict(list)
    for lineno, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        if isinstance(record, list):
            groups[None].append((lineno - 1, record))
            continue
        indices = record.get("indices")
        if not isinstance(indices, list):
            raise ValueError(f"line {lineno}: missing 'indices' list")
        groups[record.get("layer")].append((int(record.get("step", lineno - 1)), indices))
    if not groups:
        raise ValueError("empty trace")
    for key in groups:
        groups[key].sort(key=lambda item: item[0])
    return dict(groups)


def overlap_ratios(steps: list) -> list[float]:
    """rho_t = |S_t inter S_{t-1}| / |S_t| for each consecutive pair."""
    ratios = []
    for (_, prev), (_, cur) in zip(steps, steps[1:]):
        if not cur:
            continue
        ratios.append(len(set(prev) & set(cur)) / len(cur))
    return ratios


def simulate_lru(steps: list, capacity: int):
    """Token-level LRU residency. Returns (hits, misses, hit_rate).

    Plain dict as an order-preserving LRU: delete+reinsert on hit moves the
    token to the most-recent end; evicting next(iter(...)) drops the oldest.
    O(1) per access.
    """
    if capacity < 1:
        raise ValueError("capacity must be positive")
    recency: dict[int, None] = {}
    hits = misses = 0
    for _, indices in steps:
        for token in indices:
            if token in recency:
                hits += 1
                del recency[token]
            else:
                misses += 1
                if len(recency) >= capacity:
                    recency.pop(next(iter(recency)))
            recency[token] = None
    total = hits + misses
    return hits, misses, (hits / total if total else 0.0)


def block_stats(steps: list, block_size: int) -> dict:
    """Fetch fragmentation: distinct blocks touched vs tokens per step."""
    if block_size < 1:
        raise ValueError("block_size must be positive")
    blocks_per_step, tokens_per_step = [], []
    for _, indices in steps:
        blocks_per_step.append(len({t // block_size for t in indices}))
        tokens_per_step.append(len(indices))
    if not steps:
        raise ValueError("empty step list")
    mean_blocks = sum(blocks_per_step) / len(blocks_per_step)
    mean_tokens = sum(tokens_per_step) / len(tokens_per_step)
    return {
        "mean_blocks_per_step": mean_blocks,
        "mean_tokens_per_step": mean_tokens,
        "mean_tokens_per_touched_block": (mean_tokens / mean_blocks) if mean_blocks else 0.0,
    }


def summarize(steps: list, block_size: int, multipliers: list[float]) -> dict:
    k_values = [len(indices) for _, indices in steps]
    k = round(sum(k_values) / len(k_values)) if k_values else 0
    ratios = overlap_ratios(steps)
    residency = {}
    for mult in multipliers:
        if mult < 1.0:
            raise ValueError("multipliers must be >= 1.0")
        capacity = max(1, round(k * mult))
        hits, misses, rate = simulate_lru(steps, capacity)
        residency[f"{mult:g}x"] = {"capacity": capacity, "hits": hits,
                                   "misses": misses, "hit_rate": rate}
    return {
        "steps": len(steps), "k_mean": k,
        "adjacent_overlap": {
            "mean": sum(ratios) / len(ratios) if ratios else 0.0,
            "min": min(ratios) if ratios else 0.0,
            "max": max(ratios) if ratios else 0.0,
        },
        "residency": residency,
        "blocks": block_stats(steps, block_size),
    }


def analyze_trace(lines, block_size: int = 128,
                  multipliers: tuple = (1.0, 1.5, 2.0, 3.0, 4.0)) -> dict:
    groups = parse_trace(lines)
    return {str(key): summarize(steps, block_size, list(multipliers))
            for key, steps in groups.items()}

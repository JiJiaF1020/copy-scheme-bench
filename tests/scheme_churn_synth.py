"""Synthetic top-K trace generator (pure stdlib).

Models the set-level dynamics of a DSA/SFA indexer's per-step top-K selection
so the churn analyzer (scheme_churn) and the break-even model can be exercised
without a real serving trace:

- geometric drift: each step keeps round(keep * k) members of the previous
  set, refills from a hot pool of `hot_pool` tokens;
- regime shift: every `shift_every` steps the hot pool jumps to a fresh
  disjoint region (models topic change / request-batch turnover);
- per-layer chains: `layers` > 1 emits independent chains tagged by layer.

Deterministic under `seed`. No Torch, no CANN.
"""

from __future__ import annotations

import random


def _check(steps: int, k: int, vocab: int, keep: float, hot_pool: int,
           shift_every: int) -> None:
    if steps < 1 or k < 1:
        raise ValueError("steps and k must be positive")
    if not 0.0 <= keep <= 1.0:
        raise ValueError("keep must be in [0, 1]")
    if hot_pool < k:
        raise ValueError("hot_pool must be >= k")
    if vocab < hot_pool:
        raise ValueError("vocab must be >= hot_pool")
    if shift_every < 1:
        raise ValueError("shift_every must be positive")


def _gen_chain(steps: int, k: int, vocab: int, keep: float, hot_pool: int,
               shift_every: int, rng: random.Random) -> list[list[int]]:
    kept = round(keep * k)
    region_count = vocab // hot_pool  # disjoint full regions only
    region = rng.randrange(region_count)
    current: list[int] = []
    chain = []
    for step in range(steps):
        if step % shift_every == 0:
            region = (region + 1) % region_count
            current = []
        base = region * hot_pool
        survivors = set(rng.sample(current, kept)) if current and kept else set()
        fresh_pool = [token for token in range(base, base + hot_pool)
                      if token not in survivors]
        fresh = rng.sample(fresh_pool, k - len(survivors))
        current = sorted(survivors | set(fresh))
        chain.append(current)
    return chain


def gen_trace(steps: int, k: int, vocab: int = 1 << 20, keep: float = 0.85,
              hot_pool: int | None = None, shift_every: int = 0,
              layers: int = 1, seed: int = 7) -> list[dict]:
    """Return one record per (step, layer): {"step", "layer"?, "indices"}."""
    hot_pool = hot_pool if hot_pool is not None else max(k, vocab // 16)
    if shift_every < 0:
        raise ValueError("shift_every must be >= 0 (0 = never shift)")
    shift_every = shift_every if shift_every > 0 else steps + 1  # never shift
    _check(steps, k, vocab, keep, hot_pool, shift_every)
    rng = random.Random(seed)
    chains = [_gen_chain(steps, k, vocab, keep, hot_pool, shift_every,
                         random.Random(rng.randrange(1 << 30)))
              for _ in range(layers)]
    records = []
    for step in range(steps):
        for layer, chain in enumerate(chains):
            record = {"step": step, "indices": chain[step]}
            if layers > 1:
                record["layer"] = layer
            records.append(record)
    return records

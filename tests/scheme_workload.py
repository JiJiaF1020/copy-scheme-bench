"""Copy-list generation and CPU-side reference logic (pure stdlib).

Everything in this module runs on any host without Torch or CANN, so the exact
semantics the A5 worker executes can be regression-tested on a laptop. The A5
worker converts these lists to tensors; it never re-implements the sampling.

Layout conventions match the blueprint bench (tests/test_kvcache_scatter_copy.py):
  - src/dst copy lists are padded with -1 up to copy_cap;
  - row 0 of the batch pins copy_min, row 1 pins copy_max (when batch > 1);
  - source tokens and destination slots are unique within each request row;
  - dram/hbm block tables are per-request random permutations over a shared
    read-only source pool / private destination blocks plus one guard block.
"""

from __future__ import annotations

import random

NEGATIVE = -1


def block_count(tokens: int, block_size: int) -> int:
    if tokens < 1:
        raise ValueError("token count must be positive")
    return (tokens + block_size - 1) // block_size


def gen_block_tables(batch_size: int, source_len: int, hbm_slots: int,
                     block_size: int, rng: random.Random) -> tuple[list[list[int]], list[list[int]]]:
    """Per-request block tables; same policy as the blueprint bench."""
    source_blocks = block_count(source_len, block_size)
    dram_table = [rng.sample(range(source_blocks), source_blocks) for _ in range(batch_size)]
    blocks_per_row = block_count(hbm_slots, block_size)
    mapped = batch_size * blocks_per_row
    # +1 keeps one unmapped guard block, exactly like the blueprint case.
    permutation = rng.sample(range(mapped + 1), mapped)
    hbm_table = [permutation[row * blocks_per_row:(row + 1) * blocks_per_row] for row in range(batch_size)]
    return dram_table, hbm_table


def _random_unused(used: set[int], limit: int, rng: random.Random) -> int:
    """Uniform unused token id; falls back to a forward scan near saturation."""
    for _ in range(64):
        value = rng.randrange(limit)
        if value not in used:
            return value
    for value in range(limit):
        if value not in used:
            return value
    raise ValueError("no unused token id left")


def gen_src_row(count: int, source_len: int, rng: random.Random,
                run_frac: float = 0.0) -> list[int]:
    """One request's unique source tokens.

    run_frac is the target fraction of adjacent pairs that are consecutive in
    token space (t, t+1): the DRAM-side locality knob used to measure how much
    of the PCIe random-read penalty is locality-driven. run_frac=0.0 reproduces
    the fully discrete production pattern.
    """
    if not 0 <= count <= source_len:
        raise ValueError("count must be within [0, source_len]")
    if not 0.0 <= run_frac <= 1.0:
        raise ValueError("run_frac must be within [0.0, 1.0]")
    if count == 0:
        return []
    used: set[int] = set()
    first = rng.randrange(source_len)
    used.add(first)
    row = [first]
    while len(row) < count:
        nxt = row[-1] + 1
        if rng.random() < run_frac and nxt < source_len and nxt not in used:
            row.append(nxt)
        else:
            row.append(_random_unused(used, source_len, rng))
        used.add(row[-1])
    return row


def measured_run_frac(row: list[int]) -> float:
    """Actual fraction of adjacent pairs that are consecutive; 0 for len < 2."""
    if len(row) < 2:
        return 0.0
    runs = sum(1 for prev, cur in zip(row, row[1:]) if cur == prev + 1)
    return runs / (len(row) - 1)


def gen_copy_lists(batch_size: int, source_len: int, hbm_slots: int,
                   copy_min: int, copy_max: int, copy_cap: int,
                   seed: int, run_frac: float = 0.0):
    """(counts, src_rows, dst_rows); rows are raw lists, padding is pad_row's job."""
    if not 0 <= copy_min <= copy_max <= min(copy_cap, source_len, hbm_slots):
        raise ValueError("require 0 <= copy_min <= copy_max <= min(copy_cap, source_len, hbm_slots)")
    rng = random.Random(seed)
    counts = [rng.randint(copy_min, copy_max) for _ in range(batch_size)]
    if batch_size > 1:
        counts[0] = copy_min
        counts[1] = copy_max
    src_rows = [gen_src_row(count, source_len, rng, run_frac) for count in counts]
    dst_rows = [rng.sample(range(hbm_slots), count) for count in counts]
    return counts, src_rows, dst_rows


def pad_row(row: list[int], cap: int) -> list[int]:
    if len(row) > cap:
        raise ValueError("row exceeds copy capacity")
    return row + [NEGATIVE] * (cap - len(row))


def resolve_phys_rows(table_row: list[int], token_ids, block_size: int) -> list[int]:
    """token id -> physical row id: table[t // B] * B + t % B (blueprint formula)."""
    return [table_row[t // block_size] * block_size + t % block_size for t in token_ids]


def gather_rows(pool_rows, phys_rows):
    """Reference CPU gather: out[i] = pool_rows[phys_rows[i]], byte exact."""
    return [pool_rows[p] for p in phys_rows]


def split_hybrid(counts: list[int], src_rows: list[list[int]], dst_rows: list[list[int]],
                 cpu_frac: float) -> dict:
    """Split each row's copy list into an NPU-kernel prefix and a CPU tail.

    The kernel keeps the FIRST count-n_cpu tokens of each row so its metadata
    is a strict prefix trim (same ABI, smaller counts); the CPU path takes the
    tail. Kernel and CPU destination sets are disjoint by construction because
    each row's dst list is unique.
    """
    if not 0.0 <= cpu_frac <= 1.0:
        raise ValueError("cpu_frac must be within [0.0, 1.0]")
    kernel_counts, kernel_src, kernel_dst, cpu_src, cpu_dst = [], [], [], [], []
    for count, src, dst in zip(counts, src_rows, dst_rows):
        if len(src) != count or len(dst) != count:
            raise ValueError("row length does not match its copy count")
        n_cpu = round(count * cpu_frac)
        kernel_counts.append(count - n_cpu)
        kernel_src.append(src[:count - n_cpu])
        kernel_dst.append(dst[:count - n_cpu])
        cpu_src.append(src[count - n_cpu:])
        cpu_dst.append(dst[count - n_cpu:])
    return {
        "kernel_counts": kernel_counts, "kernel_src": kernel_src, "kernel_dst": kernel_dst,
        "cpu_counts": [len(row) for row in cpu_src], "cpu_src": cpu_src, "cpu_dst": cpu_dst,
    }

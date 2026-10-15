"""Scheme-bench specific names; payload constants come from the blueprint."""

SINGLE_TEST = "a5_kvcache_copy_scheme_singlecard"
MULTIPROCESS_TEST = "a5_kvcache_copy_scheme_multiprocess"
RESULTS_SUBDIR = "results/copy_scheme_a5_c8"
MANIFEST_NAME = "copy_scheme_run_manifest.json"

SCHEMES = ("npu", "cpu", "hybrid")
HYBRID_MODES = ("serial", "overlap")

# Per-rank NUMA binding list, one node per selected device (same convention as
# the blueprint runner so both suites share run scripts and muscle memory).
NUMA_ENV = "SCATTER_C8_NUMA_NODES"
# Runner-to-worker handoff when numactl is absent on the host: the worker binds
# its own CPU affinity to the node's cpulist before allocating, so first-touch
# places the pool pages on that node (approximates --cpunodebind/--membind).
NUMA_FALLBACK_ENV = "SCATTER_C8_NUMA_FALLBACK"
# Build tag recorded into every result JSON; set by tools/build_queue_depth.sh
# (or by hand) so queue-depth rebuilds are traceable in the reports.
QUEUE_DEPTH_ENV = "SCATTER_C8_QUEUE_DEPTH"
DEFAULT_QUEUE_DEPTH = 8

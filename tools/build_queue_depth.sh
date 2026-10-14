#!/usr/bin/env bash
# Rebuild the blueprint scatter-copy kernel with a different MTE2 queue depth
# (scheme S4). Patches the QUEUE_DEPTH constant in the blueprint kernel source,
# reruns its build_c8.sh and tags subsequent results via SCATTER_C8_QUEUE_DEPTH.
#
#   tools/build_queue_depth.sh 16     # build with depth 16
#   tools/build_queue_depth.sh 8      # back to the shipping default
#
# The patch is a source edit in the blueprint checkout; restore it with depth 8
# (or git -C "$SCATTER_ROOT" checkout -- <kernel>) when done. For two depths in
# parallel, use two blueprint checkouts and point SCATTER_ROOT at each.
set -euo pipefail
DEPTH="${1:?usage: build_queue_depth.sh <depth, e.g. 2 4 8 16>}"
case "${DEPTH}" in ''|*[!0-9]*) echo "depth must be a positive integer" >&2; exit 2 ;; esac
SCATTER_ROOT="${SCATTER_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/nanovllm-scatter_copy}"
KERNEL="${SCATTER_ROOT}/csrc/src/kvcache_scatter_copy_c8/op_kernel/vllm_a5_kvcache_scatter_copy_c8.cpp"
[[ -f "${KERNEL}" ]] || { echo "kernel source not found: ${KERNEL} (set SCATTER_ROOT)" >&2; exit 2; }

sed -i.bak -E "s/^(constexpr uint32_t QUEUE_DEPTH = )[0-9]+;/\1${DEPTH};/" "${KERNEL}"
grep -qE "^constexpr uint32_t QUEUE_DEPTH = ${DEPTH};" "${KERNEL}" || {
  echo "QUEUE_DEPTH patch did not apply; line anchor changed?" >&2
  mv "${KERNEL}.bak" "${KERNEL}"
  exit 1
}
rm -f "${KERNEL}.bak"
echo "[queue_depth] ${KERNEL}: QUEUE_DEPTH=${DEPTH}"
bash "${SCATTER_ROOT}/build_c8.sh"
echo "[queue_depth] built. Tag your sweep results with:"
echo "  export SCATTER_C8_QUEUE_DEPTH=${DEPTH}"

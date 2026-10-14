#!/usr/bin/env bash
# Entry point for the scheme sweep on the A5 host: sources CANN, pins the
# blueprint checkout and hands over to tests/run_scheme_sweep.py.
set -euo pipefail
BENCH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCATTER_ROOT="${SCATTER_ROOT:-$(dirname "${BENCH_ROOT}")/nanovllm-scatter_copy}"
SCATTER_PYTHON=${PYTHON_BIN:-${NANOVLLM_A5_OPS_PYTHON:-python3}}
export TEST_VISIBLE_DEVICES=${TEST_VISIBLE_DEVICES:-${A5_TEST_VISIBLE_DEVICES:-${ASCEND_RT_VISIBLE_DEVICES:-0,1,2,3,4,5,6,7}}}
# Help and validation work on development hosts without CANN or Torch.
SCHEME_PREVIEW=${DRY_RUN:-0}
for SCHEME_ARG in "$@"; do
  case "${SCHEME_ARG}" in --dry-run|--help|-h) SCHEME_PREVIEW=1 ;; esac
done
if [[ "${SCHEME_PREVIEW}" != 1 ]]; then
  export ASCEND_HOME_PATH=${ASCEND_HOME_PATH:-/usr/local/Ascend/ascend-toolkit/latest}
  export CANN_INSTALL_PATH=${CANN_INSTALL_PATH:-${ASCEND_HOME_PATH}}
  if [[ -f "${ASCEND_HOME_PATH}/set_env.sh" ]]; then
    set +u
    source "${ASCEND_HOME_PATH}/set_env.sh"
    set -u
  fi
  unset ASCEND_CUSTOM_OPP_PATH NANOVLLM_A5_INSTALL_OPP_PATH NANOVLLM_CUST_OPAPI_LIB
  export SOC_VERSION=ascend950
  export ASCEND_LAUNCH_BLOCKING=0
  export PYTORCH_NPU_ALLOC_CONF=${PYTORCH_NPU_ALLOC_CONF:-expandable_segments:True}
fi
export ASCEND_RT_VISIBLE_DEVICES=${TEST_VISIBLE_DEVICES}
export SCATTER_ROOT
export PYTHONUNBUFFERED=1
export PYTHONPATH="${SCATTER_ROOT}/torch_extension${PYTHONPATH:+:${PYTHONPATH}}"
exec "${SCATTER_PYTHON}" "${BENCH_ROOT}/tests/run_scheme_sweep.py" "$@"

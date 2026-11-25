#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RECOVERY_DIR="${DATUMLEX_RECOVERY_DIR:-$(cd "${REPO_ROOT}/.." && pwd)/recuperacao}"
RUNTIME_PYTHON="${RECOVERY_DIR}/runtime/bin/python"

if [[ -x "${RUNTIME_PYTHON}" ]]; then
  PYTHON_BIN="${RUNTIME_PYTHON}"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "Erro: Python não encontrado em ${RUNTIME_PYTHON} nem no PATH." >&2
  exit 1
fi

exec "${PYTHON_BIN}" "${REPO_ROOT}/scripts/local_ops.py" --repo-root "${REPO_ROOT}" --recovery-dir "${RECOVERY_DIR}" "$@"

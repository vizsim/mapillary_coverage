#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "$REPO_DIR"

export PYTHONPATH="${REPO_DIR}/src${PYTHONPATH:+:$PYTHONPATH}"

if [[ -x "${REPO_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${REPO_DIR}/.venv/bin/python"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "No Python interpreter found."
  exit 127
fi

export TQDM_DISABLE=1

echo "🚀 Starting"
echo

(
  while true; do
    ts=$(date +"%H:%M:%S")
    if [[ -r /sys/fs/cgroup/memory.current ]]; then
      mem=$(cat /sys/fs/cgroup/memory.current)
      mem_mb=$(awk "BEGIN {printf \"%.2f\", $mem/1024/1024}")
      echo "[$ts] RAM usage: ${mem_mb} MB"
    elif [[ -r /sys/fs/cgroup/memory/memory.usage_in_bytes ]]; then
      mem=$(cat /sys/fs/cgroup/memory/memory.usage_in_bytes)
      mem_mb=$(awk "BEGIN {printf \"%.2f\", $mem/1024/1024}")
      echo "[$ts] RAM usage: ${mem_mb} MB"
    else
      echo "[$ts] RAM usage: unavailable"
    fi
    sleep 5
  done
) &

LOGGER_PID=$!

cleanup() {
  kill "$LOGGER_PID" >/dev/null 2>&1 || true
}

trap cleanup EXIT

cli_args=(run-pipeline)

if [[ "${MAPILLARY_COVERAGE_DRY_RUN:-0}" == "1" ]]; then
  cli_args+=(--dry-run)
fi

"$PYTHON_BIN" -m mapillary_coverage "${cli_args[@]}"

echo "done."

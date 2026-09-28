#!/usr/bin/env bash
# Cron entrypoint. Logs to logs/YYYY-MM.log. Extra args are passed through (e.g. --dry-run, --force).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
LOG="logs/$(date +%Y-%m).log"
{
  echo "===== $(date '+%F %T %Z') run $* ====="
  rc=0; "${PYTHON:-python3}" -m mlnews "$@" || rc=$?
  echo "===== exit $rc ====="
} >> "$LOG" 2>&1

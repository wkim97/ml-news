#!/usr/bin/env bash
# Install (or update) the daily cron job. Usage: bash scripts/install_cron.sh [HH:MM]   (default 08:40)
# Captures the current PATH so cron can find `claude` and a Python >= 3.11.
set -euo pipefail
cd "$(dirname "$0")/.."
TIME="${1:-08:40}"; HH="${TIME%%:*}"; MM="${TIME##*:}"
DIR="$(pwd)"
PY="$(command -v python3)"
"$PY" -c 'import sys; assert sys.version_info >= (3, 11), "need Python >= 3.11 (tomllib)"'
command -v claude >/dev/null || { echo "claude CLI not on PATH"; exit 1; }
PATHS="$(dirname "$(command -v claude)"):$(dirname "$PY"):/usr/local/bin:/usr/bin:/bin"
LINE="$((10#$MM)) $((10#$HH)) * * * PATH=$PATHS PYTHON=$PY /bin/bash $DIR/scripts/run.sh  # ml-news"
( crontab -l 2>/dev/null | grep -v '# ml-news' || true; echo "$LINE" ) | crontab -
echo "installed: $LINE"
echo "(times are in the system timezone: $(date +%Z))"

#!/usr/bin/env bash
# One-command launcher: creates the virtual environment on first run,
# installs pinned dependencies, then starts Archestral and opens the browser.
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for cand in python3.12 python3.11 python3.10; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
  echo "Archestral needs Python 3.10-3.12 (MediaPipe 0.10.21 has no wheels for 3.13)." >&2
  echo "macOS: brew install python@3.12" >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Creating virtual environment with $PY ..."
  "$PY" -m venv .venv
  .venv/bin/pip install --upgrade pip >/dev/null
fi
if [ ! -f .venv/.deps-installed ] || [ requirements.txt -nt .venv/.deps-installed ]; then
  echo "Installing dependencies (first run only) ..."
  .venv/bin/pip install -r requirements-dev.txt
  touch .venv/.deps-installed
fi

exec .venv/bin/python -m archestral serve "$@"

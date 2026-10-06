#!/usr/bin/env bash
# Per-workspace venv with the same extras CI's "full" job uses.
set -euo pipefail
PY="${WEFT_PYTHON:-python3}"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -e ".[dev]"
.venv/bin/python -c "import weft, pxr, numpy; print('weft workspace ready:', pxr.__file__)"

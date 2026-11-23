#!/usr/bin/env bash
# maat 0.1.0 028983a1c603
# Session start: a fresh clone has no core.hooksPath, so the guards in .githooks do nothing.
# Set it once and say so. Silent and exit 0 when there is nothing to do.
top=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
[ -d "$top/.githooks" ] || exit 0
if [ -n "$(git -C "$top" config --local --get core.hooksPath)" ]; then exit 0; fi
outside=$(git -C "$top" config --get core.hooksPath)
if [ -n "$outside" ]; then
  echo "[maat] core.hooksPath is set outside this repository ($outside); the guards in .githooks are not active."
  exit 0
fi
git -C "$top" config core.hooksPath .githooks || exit 0
echo "[maat] core.hooksPath was unset in this clone; set to .githooks (AGENTS.md rule 2)."
exit 0

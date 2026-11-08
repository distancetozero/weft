#!/usr/bin/env bash
# Session start / pre-compact: put the beads workflow in front of the agent,
# then override its memory advice. bd prime says "use bd remember"; in this
# repo beads holds work only and agent memory files hold knowledge
# (CLAUDE.md "Work tracking").
command -v bd >/dev/null 2>&1 || { echo "bd not installed: beads workflow unavailable (CLAUDE.md Work tracking)"; exit 0; }
bd prime
cat <<'NOTE'

[weft override] Ignore bd prime's memory guidance: do NOT use `bd remember`.
Beads is for work only; knowledge goes in agent memory files. See CLAUDE.md
"Work tracking: beads, with GitHub Issues as intake".
NOTE

#!/usr/bin/env bash
# {{stamp}}
# Session start / pre-compact: put the beads workflow in front of the agent,
# then override its memory advice. bd prime says "use bd remember"; in this
# repo beads holds work only and agent memory files hold knowledge
# (AGENTS.md rule 7 (Three stores)).
command -v bd >/dev/null 2>&1 || { echo "bd not installed: beads workflow unavailable (AGENTS.md rule 7 (Three stores))"; exit 0; }
# Always from the main checkout. At bd 1.3.4 worktrees share one workspace;
# the cd is kept so an older bd on PATH never creates a second database.
cd "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")" || exit 0
bd prime
cat <<'NOTE'

[maat override] Ignore bd prime's memory guidance: do NOT use `bd remember`.
Beads is for work only; knowledge goes in agent memory files. See AGENTS.md
rule 7 (Three stores).
NOTE

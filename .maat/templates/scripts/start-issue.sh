#!/bin/bash
# {{stamp}}
# Usage: ./scripts/start-issue.sh <bead-id | short-name>
# Examples: ./scripts/start-issue.sh {{bead_prefix}}-8mn     (claims the bead)
#           ./scripts/start-issue.sh kept-set-diff
#
# Creates a git worktree on a fresh branch from origin/{{protected_branch}} and wires it to
# this repo's git hooks (.githooks/). Use it instead of `git worktree add`:
# a worktree without core.hooksPath has no pre-commit/pre-push guards, so
# nothing stops a commit or push straight to {{protected_branch}} (AGENTS.md rule 2).
#
# Worktrees go under ${{bead_prefix_upper}}_WORKTREE_ROOT, else ~/.superset/worktrees/<repo>
# when Superset is installed (so it picks them up), else ../<repo>-worktrees.

set -e

ARG="${1:?Usage: start-issue.sh <bead-id | short-name>}"
# The main checkout, even when run from inside another worktree: its
# .githooks outlives any worktree.
REPO_ROOT="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
REPO_NAME="$(basename "$REPO_ROOT")"

# A bead id: use its title for the branch name and claim it.
if [[ "$ARG" =~ ^{{bead_prefix}}-[a-z0-9.]+$ ]]; then
  TITLE="$(cd "$REPO_ROOT" && bd show "$ARG" --json | python3 -c 'import json,sys; a=json.load(sys.stdin); print(a[0]["title"] if a else "")')"
  [ -n "$TITLE" ] || { echo "Error: could not find bead $ARG"; exit 1; }
  NAME="$TITLE"
  (cd "$REPO_ROOT" && bd update "$ARG" --claim >/dev/null)
  echo "✓ Claimed: $ARG ($TITLE)"
else
  NAME="$ARG"
fi

BRANCH=$(echo "$NAME" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//' | cut -c1-50)

if [ -n "${{bead_prefix_upper}}_WORKTREE_ROOT" ]; then
  ROOT="${{bead_prefix_upper}}_WORKTREE_ROOT"
elif [ -d "$HOME/.superset" ]; then
  ROOT="$HOME/.superset/worktrees/$REPO_NAME"
else
  ROOT="$(dirname "$REPO_ROOT")/$REPO_NAME-worktrees"
fi
WORKTREE_PATH="$ROOT/$BRANCH"

git fetch -q origin {{protected_branch}}
git worktree add -b "$BRANCH" "$WORKTREE_PATH" origin/{{protected_branch}}
echo "✓ Worktree: $WORKTREE_PATH"
echo "✓ Branch: $BRANCH"

# Absolute path, so the hooks still fire if the worktree moves.
git -C "$WORKTREE_PATH" config core.hooksPath "$REPO_ROOT/.githooks"
echo "✓ Hooks: core.hooksPath = $REPO_ROOT/.githooks"

[[ "$ARG" =~ ^{{bead_prefix}}- ]] && echo "When done: bd close $ARG (after restating acceptance, AGENTS.md rule 4)"
echo "Next: cd \"$WORKTREE_PATH\" && {{setup_command}}   (Superset runs it for you)"

#!/bin/bash
# maat 0.1.0 4e96c3cabbfb
# Usage: ./scripts/start-issue.sh <issue-number | short-name>
# Examples: ./scripts/start-issue.sh 8      (claims issue #8 of distancetozero/weft)
#           ./scripts/start-issue.sh kept-set-diff
#
# Creates a git worktree on a fresh branch from origin/main and wires it to
# this repo's git hooks (.githooks/). Use it instead of `git worktree add`:
# a worktree without core.hooksPath has no pre-commit/pre-push guards, so
# nothing stops a commit or push straight to main (AGENTS.md rule 2).
#
# Worktrees go under $WEFT_WORKTREE_ROOT, else ~/.superset/worktrees/<repo>
# when Superset is installed (so it picks them up), else ../<repo>-worktrees.

set -e

ARG="${1:?Usage: start-issue.sh <issue-number | short-name>}"
# The main checkout, even when run from inside another worktree: its
# .githooks outlives any worktree.
REPO_ROOT="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
REPO_NAME="$(basename "$REPO_ROOT")"

# An issue number, with or without a leading #: read the issue once, for its title
# (the branch name) and to refuse a pull request, a closed issue or one held by someone else.
ISSUE=""
LOGIN=""
if [[ "$ARG" =~ ^#?([0-9]+)$ ]]; then
  ISSUE=$((10#${BASH_REMATCH[1]}))
  INFO="$(gh api "repos/distancetozero/weft/issues/$ISSUE" 2>/dev/null)" || INFO=""
  PARSED="$(printf '%s' "$INFO" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(d["title"].replace("\n", " "))
print(d["state"])
print("pr" if "pull_request" in d else "issue")
print(",".join(a["login"] for a in d.get("assignees") or []))
' 2>/dev/null)" || PARSED=""
  { IFS= read -r TITLE; IFS= read -r STATE; IFS= read -r KIND; IFS= read -r ASSIGNEES; } <<< "$PARSED" || true
  [ -n "$TITLE" ] || { echo "Error: could not read issue #$ISSUE"; exit 1; }
  [ "$KIND" != "pr" ] || { echo "Error: #$ISSUE is a pull request, not an issue"; exit 1; }
  [ "$STATE" = "open" ] || { echo "Error: issue #$ISSUE is closed"; exit 1; }
  LOGIN="$(gh api user --jq .login 2>/dev/null)" || LOGIN=""
  if [ -n "$ASSIGNEES" ] && [[ ",$ASSIGNEES," != *",$LOGIN,"* ]]; then
    echo "Error: issue #$ISSUE is already claimed by $ASSIGNEES"; exit 1
  fi
  NAME="issue-$ISSUE-$TITLE"
else
  NAME="$ARG"
fi

BRANCH=$(echo "$NAME" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//' | cut -c1-50)

if [ -n "$WEFT_WORKTREE_ROOT" ]; then
  ROOT="$WEFT_WORKTREE_ROOT"
elif [ -d "$HOME/.superset" ]; then
  ROOT="$HOME/.superset/worktrees/$REPO_NAME"
else
  ROOT="$(dirname "$REPO_ROOT")/$REPO_NAME-worktrees"
fi
WORKTREE_PATH="$ROOT/$BRANCH"

if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  echo "Error: branch $BRANCH already exists"; exit 1
fi

git fetch -q origin main
git worktree add -b "$BRANCH" "$WORKTREE_PATH" origin/main
echo "✓ Worktree: $WORKTREE_PATH"
echo "✓ Branch: $BRANCH"

# Absolute path, so the hooks still fire if the worktree moves.
git -C "$WORKTREE_PATH" config core.hooksPath "$REPO_ROOT/.githooks"
echo "✓ Hooks: core.hooksPath = $REPO_ROOT/.githooks"

# Claim the issue: assign the caller, then leave a comment. A failure here is not fatal.
if [ -n "$ISSUE" ]; then
  if [ -n "$LOGIN" ] \
    && gh api -X POST "repos/distancetozero/weft/issues/$ISSUE/assignees" -f "assignees[]=$LOGIN" >/dev/null 2>&1; then
    if gh api -X POST "repos/distancetozero/weft/issues/$ISSUE/comments" -f "body=Claimed $(date +%Y-%m-%d): working on branch $BRANCH" >/dev/null 2>&1; then
      echo "✓ Claimed: #$ISSUE ($TITLE)"
    else
      echo "Warning: #$ISSUE is assigned, but the claim comment was not posted"
    fi
  else
    echo "Warning: could not assign #$ISSUE"
  fi
  echo "When done: the PR says \"Closes #$ISSUE\", after restating acceptance (AGENTS.md rule 4)"
fi
echo "Next: cd \"$WORKTREE_PATH\" && ./.superset/setup.sh   (Superset runs it for you)"

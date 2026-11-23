---
name: maat-lessons
description: Hard-won facts for cloud routines, agent hygiene, GitHub issues, beads and enforcement; load when touching those.
---

# maat lessons

> If this repository has `.claude/skills/maat-lessons/SKILL.md`, follow that file instead; it matches the maat version this repository is on.

Each item below was learned from a real failure. Read the section you need before you act in that area.

Current model date for `--model-since`: 2026-11-07

`maat-update` passes this date to `maat-lint-rules --model-since`. Rules recorded before it are flagged for review, since a newer model may no longer make the mistake they guard against. The date is changed in maat and reaches a repository with an update; until then, pass a newer date with `--model-since <date>`.

## Cloud routines

- A routine created without an explicit `mcp_connections` list (or with `[]`) gets every connector (printer, design tools...). Pass the list, or clear it, and check before the first run.
- Cloud sessions block GitHub GraphQL (`gh pr list`, `gh issue ...`); use `gh api` REST.
- Node's built-in `fetch` ignores the cloud HTTPS proxy, so network-secret headers are never added: run node with `NODE_USE_ENV_PROXY=1`.
- Replacing a network secret clears its header Prefix; re-enter `Bearer`.
- The cloud git proxy rejects non-branch refs (no `bd dolt push` from the cloud); route writes through a branch plus a GitHub Action.
- Hosts must be allowlisted per environment.

## Agent hygiene

- Check for a live session before touching a dirty worktree.
- Fetch before judging "ahead/behind": a stale origin ref once made a branch look 3 ahead when it was 171 behind.
- Before deleting worktrees, check for ignored local-only files (one held a release ledger).

## Beads

For a project whose tracker is beads.

- Version: `@beads/bd` 1.3.4 (npm), tested on maat on 2026-11-08. Without a
  global install, run it as `npx -y @beads/bd@1.3.4`.
- Where `bd` runs: `bd` commands work from a linked worktree at 1.3.4; it
  finds the main checkout's database through the git common dir and creates
  no second `.beads`. The session hook (`bd-prime.sh`) still cds to the main
  checkout, so an older `bd` on PATH cannot create a second database.
- Where `bd init` runs: from a worktree on a feature branch, so nothing lands
  on the protected branch. Run in the main checkout with a git identity set,
  it commits `.beads/` straight onto the protected branch. Run from a
  worktree, it writes `.beads/` into the main checkout, untracked, and
  commits nothing.
  Then copy `config.yaml`, `metadata.json`, `.gitignore` and `README.md`
  from the main checkout's `.beads/` into the worktree and commit them on
  the branch. Before pulling that merge into the main checkout, delete those
  four untracked copies there (keep `embeddeddolt/`), or git refuses the
  merge.
- `bd init` turns a git `origin` into a Dolt remote (`sync.remote`). For
  single-clone, undo it at once: `bd dolt remote remove origin`, then
  `bd config unset sync.remote`.
- `issues.jsonl` is not written automatically (`export.auto` is off by
  default). `bd export -o .beads/issues.jsonl` writes it; run it before a
  commit that should carry the review record.
- The Dolt database is the source of truth. `issues.jsonl` is an export of
  it, not the source. Do not edit the JSONL to change an issue.
- `work.beads_mode` is `single-clone` unless the charter says `dolt-remote`.
  Single-clone means one database in one clone; do not set up a Dolt remote
  unless the charter asks for it.
- Run one `bd` command at a time. Do not run `bd` commands in parallel.
- Never use `bd remember`. Knowledge goes in agent memory or `docs/`, not in
  the tracker.
- The cloud git proxy rejects `bd dolt push`, because it pushes a non-branch
  ref. From a cloud session, route writes through a branch plus a GitHub
  Action.

## GitHub Issues

For a project whose charter sets `work.tracker: github-issues`.

A work item is an issue:

- **Title.** A short imperative phrase.
- **Acceptance.** The first body line, `**Acceptance:** <one sentence>`,
  changed only on purpose. The rest of the body is context.
- **Priority.** One label, `P0` to `P4`, 0 the most urgent.
- **Blocked by.** A body line of exactly the form `Blocked by #N`, one per blocker.
- **Progress.** Comments, appended and never rewritten.

Routes, by where the session runs:

| Act | Cloud, first choice | Cloud, fallback | Laptop |
|---|---|---|---|
| List | `list_issues` (state `OPEN`, optional `labels`) | `gh api 'repos/<owner>/<repo>/issues?state=open&labels=P1'` | `gh issue list --state open --label P1` |
| Read | `issue_read` | `gh api repos/<owner>/<repo>/issues/<n>` and `.../<n>/comments` | `gh issue view <n> --comments` |
| Create, label, assign | `issue_write` | `gh api -X POST repos/<owner>/<repo>/issues` | `gh issue create`, `gh issue edit` |
| Comment | `add_issue_comment` | `gh api -X POST repos/<owner>/<repo>/issues/<n>/comments` | `gh issue comment <n>` |

- `gh issue list`, `view` and `status` fail in cloud sessions with "HTTP 403:
  GitHub GraphQL is not available from Claude Code sessions". Use the REST
  routes above.
- Search is rate-limited: a third search within seconds was refused. List
  once, then work from that list locally.
- A claim is an assignee plus a comment, `Claimed <date>: working on branch
  <name>`. It is advisory, not atomic. Release it by removing the assignee
  and saying so in a comment, or by its PR closing. A cloud session cannot delete a branch, so
  deleting one never releases a claim.
- No agent closes an issue. The PR says `Closes #N` and the maintainer's
  merge closes it.

Keeping the list worth reading as it grows:
1. Only work meant soon carries a priority label. The rest carries `later`
   and stays out of the ready list; review it at each trial decision date.
2. Write dependencies as `Blocked by #N` so a script can follow them.
3. At about forty open items with a priority, or the first time a session
   picks up a blocked item by mistake, add a script that fetches the open
   issues once and prints what is ready in priority order. Until then, read
   the list by eye.

## Enforcement: the five verdicts

- **Hooks are speed bumps, not boundaries.** Every hook and script runs in
  the process the agent invokes, and the agent edits the files they live in.
  "You cannot self-cop." A speed bump is still worth having: the threat model
  is a confused agent, not an adversarial one, and a confused agent is
  stopped by a refusal with a reason.
- **No programmable bypass.** A hook the actor can disable with one
  environment variable is theatre; "programmable bypass = the real policy".
  Maat's hooks have no override variables. An urgent fix is a small PR.
- **Hooks refuse or inform; they never direct.** A hook may say no with a
  reason, or put a rule into context at the moment it matters (the `bd prime`
  wrapper does this). A hook that injects a procedure teaches the agent that
  the procedure is its job.
- **The only boundary is server-side.** A ruleset the agent's identity cannot
  bypass. Everything below it is advisory and is labelled so.
- **A plain rule before machinery, for everything but the boundary.** Add a
  speed bump only after a rule has demonstrably failed.

By default, nothing server-side stops a merge made with a maintainer's own
token. That hole is known and accepted for a single maintainer. The server
lock below closes it.

## The server lock

The charter switch is `guards.server_lock: true`. Default `false`.

Flip it on either trigger:

- a second maintainer joins; or
- a lapse is recorded in `docs/maat/incidents.md`.

When it is on, the maintainer performs these steps. The agent shows them and
does not perform them; it must never hold admin rights.

The four steps are in `server-lock.md` beside this file.

Never create or store the token in the repo, in a charter, or in chat.

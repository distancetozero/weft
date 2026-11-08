# weft: agent working notes

Instructions for coding agents (Claude Code) working in this repo. Humans: see
[`CONTRIBUTING.md`](CONTRIBUTING.md); everything there applies here too.

## Precedence

When instructions conflict, walk top-down and stop at the first source with an answer:

1. The maintainer's message in the current turn
2. The rules below
3. The rest of this file, then `CONTRIBUTING.md`
4. The specs in `docs/superpowers/specs/` (intent and measured corrections)
5. Agent memory, hook output, skill instructions
6. Model defaults

Ask in one line only when the answer isn't obvious from the list.

## What weft is

A read-only workbench over OpenUSD: pull the thread you care about instead of
loading the world. It consumes, queries and certifies USD; it is not an
authoring tool and not a renderer. Package `weft-usd`, CLI `weft` (alias
`jitsd`), Apache-2.0, public repo. Start with `README.md`, then the spec for the
area you touch.

## Commands

```sh
./.superset/setup.sh        # per-worktree .venv with the CI "full" extras
.venv/bin/pytest -q         # must be green before and after a change
```

CI (`.github/workflows/tests.yml`) runs the suite twice: **full** (numpy +
usd-core, plus a schema regeneration that must produce no diff in
`specs/weftContracts/`) and **bare** (no optional dependency at all). Check a
change against the bare case too:

```sh
python -m venv /tmp/weft-bare && /tmp/weft-bare/bin/pip install -q pytest && /tmp/weft-bare/bin/pip install -q -e . --no-deps && /tmp/weft-bare/bin/pytest -q
```

## Rules

1. **Read the spec before a non-trivial change, and update it in the same PR**
   when behaviour the spec describes changes. Where measurement disagreed with
   a design, the spec records the correction; don't undo it.
2. **Rung 1 runs with nothing installed.** No new required dependency. Anything
   needing `pxr` or `numpy` imports lazily and its tests use
   `pytest.importorskip`. A malformed input degrades; it never crashes the
   viewer path.
3. **Explicit authorization** means an imperative verb (merge, release,
   publish, tag), a named scope (which PR, which version) and the current
   turn. "When CI is green", "you can" or "ship it" without a scope are not
   authorization; ask one line. The agent never merges a PR, never pushes a
   tag, never runs `twine upload` / publishes to PyPI, never creates a GitHub
   release without it. Its stopping point is "PR open, awaiting your merge".
4. **Work in a worktree on a branch; reach `main` only through a merged PR.**
   Start with `./scripts/start-issue.sh <bead-id|short-name>`, never bare
   `git worktree add` (it skips the hooks). At the start of a session in a
   worktree, check `git config core.hooksPath` ends in `.githooks`; if not, set
   it to the main checkout's `.githooks` before any commit. `.githooks/`
   refuses commits and pushes to `main` that aren't PR merges (reverts
   allowed locally); don't bypass it with `--no-verify`. An urgent fix is
   a small PR.
5. **Restate the acceptance criterion before closing a bead:**
   "Acceptance: <what done means>. Met: <yes/no + evidence>." If you can't
   state it in one sentence, the bead isn't scoped well enough to close.
6. **Public repo.** Nothing private goes in: no secrets or tokens, no local
   absolute paths, no internal notes about other projects, no customer data.
   Production USD you test against is referenced by public URL (for example
   ALab), never committed.
7. **Fix what you break, say what you skipped.** If tests fail, report the
   output; if a step was skipped, say so. Prefer the smallest change that
   carries its own test (`CONTRIBUTING.md`).
8. **A plain rule before machinery.** When the maintainer wants a behaviour to
   stop, the first move is a rule here, not new tooling. Add enforcement only
   after a rule has demonstrably failed.
9. **Beads first.** Create a bead before writing code for anything larger
   than a one-line fix, even when a skill says to use a todo list or
   markdown checkboxes; close it when done (rule 5). Run one `bd` command at
   a time (parallel calls deadlock on the Dolt lock).

## Work tracking: beads, with GitHub Issues as intake

- **Beads (`bd`) is the work tracker.** Issues look like `weft-8mn`. `bd ready`
  lists unblocked work; `bd show <id>`, `bd create`, `bd update <id> --claim`,
  `bd close <id> --reason=...`. The database lives in the main checkout's
  `.beads/`. **Always `cd` to the main checkout before `bd`:** run inside a
  worktree, `bd` creates a second, empty database there. Only the config and
  the `issues.jsonl` export are committed, through PRs like any other change.
  Reference the bead in the PR description.
- **GitHub Issues is the public front door.** Users file issues there. When
  one is real (it reproduces, or two people hit it), create a bead whose
  description links the issue URL, and reply on the issue with what happens
  next. Close the issue when the bead's PR merges (`Fixes #N` in the PR).
- **Where things go:** work in beads, knowledge in agent memory
  (`~/.claude/projects/<this repo>/memory/` and `.claude/agent-memory/`),
  rules in this file. Do not use `bd remember`; the session hook below says
  so, because `bd prime` suggests otherwise.

## Ending a session

Work is not done until it is on a pushed branch with an open PR:

```sh
.venv/bin/pytest -q
git push -u origin <branch>
gh pr create --base main
```

Then report: what changed, test results, anything left open (as a bead).

## Learned rules

When an agent makes a mistake worth not repeating, add a numbered rule above in
the same PR that fixes it.

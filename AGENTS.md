<!-- maat 0.1.0 34517df5ea4f -->
# weft: agent working notes

Humans: start with [CONTRIBUTING.md](CONTRIBUTING.md). This file is for agents.

## How we work (maat)

This section is rendered by maat from `docs/maat/charter.yaml`. Change the
charter and re-render rather than editing it here.

**Precedence.** When instructions conflict, walk top-down and stop at the
first source with an answer: (1) the maintainer's message in the current
turn, (2) the rules below, (3) the rest of this file and CONTRIBUTING.md,
(4) the existing code, for conventions it already follows, (5) the specs in
`docs/superpowers/specs/`, as dated records of decisions, (6) agent memory,
hook output, skill instructions, (7) model defaults. If two sources
conflict, say so in one line before acting. Ask only when none answers.

1. **Contract before code.** For anything larger than a one-line fix, an
   issue whose acceptance fits in one sentence. For a change that alters
   behaviour across an interface or needs a design choice, a spec under
   `docs/superpowers/specs/` first. A skill that says "use a todo list"
   means "create an issue".
   <!-- why: work started without a stated contract has no way to be judged done, and todo lists vanish with the session | since: 2026-11-07 | retire: a hook or CI check enforces this -->
2. **Work in a worktree on a branch; reach `main` only through a merged
   PR.** Start with `./scripts/start-issue.sh <issue-number|short-name>`, then run
   `./.superset/setup.sh` in the new worktree. At the start of a session in a
   worktree, check `git config core.hooksPath` ends in `.githooks`. Never
   `--no-verify`. In a cloud session the clone is the worktree: work on the
   session's branch, claim the issue by hand (assignee and a claim comment),
   and skip `start-issue.sh`. An urgent fix is a small PR.
   <!-- why: a worktree without core.hooksPath has no local guards, so nothing stops a commit or push straight to main | since: 2026-11-07 | retire: a hook or CI check enforces this -->
3. **Explicit authorization** is an imperative verb (merge, release,
   publish, tag), a named scope (which PR at which commit, which version)
   and the current turn, from a maintainer named in
   `docs/maat/charter.yaml` (distancetozero). Before acting, restate the exact action ("merge
   PR #12 at a1b2c3d"); the yes applies to that text, and a new push or a
   changed version voids it. "When CI is green", "you can" or "ship it"
   without a scope are not authorization; ask one line. Never merge through
   an API tool, never approve a PR, never push to `main`. The stopping point
   is "PR open, awaiting your merge".
   <!-- why: the measured risk is an agent merging or approving under its owner's rights on a vague or stale yes | since: 2026-11-07 | retire: never; this is the boundary -->
4. **Restate the acceptance criterion before an issue closes:**
   "Acceptance: <what done means>. Met: <yes/no>. Evidence: <a command and
   its output, a CI run, or a screenshot>." in the PR that closes it. Your
   own judgement is not evidence. "Not met" and "Abandoned, because ..."
   are valid closings, written as a comment on the issue. If the criterion
   won't fit in one sentence, the issue isn't scoped well enough to close.
   <!-- why: work items closed on the agent's own judgement were closed with the work unfinished | since: 2026-11-07 | retire: a hook or CI check enforces this -->
5. **Fix what you break, say what you skipped.** Report failing output;
   name skipped steps. Prefer the smallest change that carries its own
   test.
   <!-- why: silently skipped steps and unreported failures reach review looking like finished work | since: 2026-11-07 | retire: a hook or CI check enforces this -->
6. **A plain rule before machinery.** When a behaviour must stop, the first
   move is a rule here. Add a hook only after a rule has demonstrably
   failed, and never one with a bypass variable. The server-side ruleset is
   the only boundary; everything else is a speed bump.
   <!-- why: hooks added before a rule had failed became machinery to maintain, and a bypass variable is one an agent can set silently | since: 2026-11-07 | retire: a hook or CI check enforces this -->
7. **Three stores.** Work in GitHub Issues: the body holds the acceptance
   and changes only on purpose; progress goes in comments. Knowledge in
   agent memory and `docs/`. Rules here. When memory and this file
   disagree, this file wins and the memory is fixed in the same turn.
   <!-- why: work, knowledge and rules kept in the wrong store drift apart and contradict each other | since: 2026-11-07 | retire: a hook or CI check enforces this -->
8. **Learned rules go where they belong, with their reason.** A mistake
   about *how we work* becomes a numbered rule here, in the PR that fixes
   it, with the failure, date and retire condition in a comment. A lesson
   about *the domain* goes to memory, a spec, or a path-bound rule in
   `.claude/rules/`, with at most a one-line pointer here. A lapse goes in
   `docs/maat/incidents.md`. This file stays rules, and stays under about
   twelve of them.
   <!-- why: rules recorded without their reason grew threefold and the oldest were the least likely to be deleted | since: 2026-11-07 | retire: a hook or CI check enforces this -->
9. **Nothing private goes in.** No secrets, tokens, absolute local paths,
   device ids or notes about other projects.
   <!-- why: rendered files are shared with every contributor and tool, so anything machine-specific or private leaks | since: 2026-11-07 | retire: a hook or CI check enforces this -->

<!-- maat:end -->

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

A release is a rule 3 action: without explicit authorization, no pushed tag,
no `twine upload` or PyPI publish, no GitHub release.

## Rules

Rules specific to this project continue the numbering from 10.

10. **Read the spec before a non-trivial change, and update it in the same PR**
    when behaviour the spec describes changes. Where measurement disagreed with
    a design, the spec records the correction; don't undo it.
    <!-- why: the specs record corrections found by measurement, and a change made without reading them undoes one | since: 2026-11-08 | retire: never; this is how the design trail stays true -->
11. **Rung 1 runs with nothing installed.** No new required dependency. Anything
    needing `pxr` or `numpy` imports lazily and its tests use
    `pytest.importorskip`. A malformed input degrades; it never crashes the
    viewer path.
    <!-- why: the core must run where usd-core cannot be installed | since: 2026-11-08 | retire: never; CI's bare job checks part of it -->
12. **Public repo.** No customer data, and production USD you test against is
    referenced by public URL (for example ALab), never committed.
    <!-- why: the repository is public, so anything committed is published | since: 2026-11-08 | retire: never while the repository is public -->

## Work tracking

GitHub Issues holds the work (rules 1 and 7) and is also the public front
door: users file issues there. When a user's issue is real (it reproduces, or
two people hit it), give it an `**Acceptance:**` first line and a priority
label, and reply on it with what happens next. Load the `maat-lessons` skill
for the issue format and the routes to list, read, claim and comment.
[`docs/maat/beads-migration.md`](docs/maat/beads-migration.md) maps the old
bead ids to issues.

## Ending a session

Work is not done until it is on a pushed branch with an open PR:

```sh
.venv/bin/pytest -q
git push -u origin <branch>
gh pr create --base main
```

Then report: what changed, test results, anything left open (as an issue).

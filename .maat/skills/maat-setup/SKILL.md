---
name: maat-setup
description: Use when a person asks to set up the maat workflow (charter, guards, rules and work tracking) in a repository.
disable-model-invocation: true
---

# maat-setup

Setup turns a short intake into `docs/maat/charter.yaml` and renders the
guards and rules files from it. Run every command from the repository root.

The executables live in `${CLAUDE_PLUGIN_ROOT}/bin/`. If `${CLAUDE_PLUGIN_ROOT}`
is unset, use the directory that contains this plugin's `.claude-plugin/plugin.json`.

## The intake rule

Ask only when a wrong guess costs more than the question. Anything a file,
`git` or `gh` can tell you, read and do not ask. Anything with a safe default,
use the default and say so. What is left goes to the maintainer once, in one
message. A second round of questions is a failure of step 1.

## What setup never does without an explicit yes

Setup never commits, pushes or merges; those belong to the maintainer. It
runs none of these unless the maintainer says yes to that step this turn:

- `bd init`, which applies only when `work.tracker` is `beads`;
- `maat-audit --apply`, which changes the ruleset and, through
  `gh api -X PATCH`, the repo settings.

A yes to one is not a yes to the others. A yes from an earlier turn does not count.

## Step 1: read first, never ask

Collect these before writing any question:

- `README.md`: the project's purpose and kind.
- An existing `AGENTS.md` or `CLAUDE.md`. Setup carries it over; do not ask
  for rules it already states. A lone `CLAUDE.md` is carried into `AGENTS.md`,
  the canonical file, and `CLAUDE.md` becomes the thin pointer to it.
- CI job names: `grep -h 'name:' .github/workflows/*`, keeping the names under
  `jobs:`. They are the candidates for `ci.required_checks`.
- `gh repo view --json nameWithOwner,defaultBranchRef,visibility` gives
  `project.repo`, `work.protected_branch` and `project.visibility` (lowercase).
  Without `gh`, read owner and name from `git remote get-url origin`.
- The language and any setup script (`.superset/setup.sh`, `scripts/setup*`,
  a `Makefile` target, `package.json` scripts).
- Superset: `.superset/config.json` in the repo or `~/.superset` on the
  machine means the worktree root is `~/.superset/worktrees/<repo>`.
- Never ask for `work.worktree_root`, `work.beads_mode`, `project.visibility`
  or `people.agents` (unused in v1); fill the defaults `questions.md` lists.

## Step 2: ask the rest in one message

Use `questions.md` next to this file: the shared block and the kind's
questions, minus what step 1 answered. If step 1 cannot tell the kind, put
every kind's questions in the same message under headings "If this is a
library: ...", "If this is an application: ..." and so on; the maintainer
answers only the block that applies. Number them, give each default, send one
message and wait.

## Step 3: write the charter

Write `docs/maat/charter.yaml` from the template at the end of
`questions.md`. Strings with `#`, `:` or leading punctuation go in double
quotes. Lists stay on one line in `[...]`, each item quoted; no `- item`
lists, no multi-line values.

## Step 4: show the plan

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/maat-render" plan docs/maat/charter.yaml --repo .
```

A charter error names the file, line and key; fix it and run again. Show
the maintainer the piles: `new`, `unchanged`, `maat_changed`, `hand_changed`,
and `retired` (files no longer rendered) if any. For each `carried over:`
line, name the rules file and how many of its lines look covered by the maat
section, and list those lines so the maintainer can prune them later.

## Step 5: write and lint

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/maat-render" write docs/maat/charter.yaml --repo .
"${CLAUDE_PLUGIN_ROOT}/bin/maat-lint-rules" AGENTS.md
```

`write` writes the new and maat-changed files and the manifest, never a
hand-changed file unless named with `--only`. On the Issues tracker it adds a
copy of maat in `.maat/` and three skills in `.claude/skills/`, so later
sessions need no plugin. "No rationale comment" (until a rule gets its
`<!-- why | since | retire -->`) is a warning; on exit 1, show the errors. The
usual fix is fewer `rules.project` rules: edit the charter and repeat from step 4.

## Step 5b: decide each hand-changed file

Render maat's version to a scratch directory and compare:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/maat-render" render docs/maat/charter.yaml --out <scratch>
diff -u <path> <scratch>/<path>
```

In `AGENTS.md` and `CLAUDE.md`, the part above `<!-- maat:end -->` is maat's and is replaced;
everything below it is kept. In `CONTRIBUTING.md` (Issues tracker) maat owns only the block between
`<!-- maat:start -->` and `<!-- maat:end -->`, and everything outside it is kept. Show one file's diff
at a time and ask: take maat's version, or keep the hand edit? On "take maat's", run
`"${CLAUDE_PLUGIN_ROOT}/bin/maat-render" write docs/maat/charter.yaml --repo . --only <path>`; on "keep", leave it.

## Step 6: offer the steps that need a yes

Offer each one separately, with what it changes. Run it only on a yes.

1. **Beads.** Only when `work.tracker` is `beads`. Run, in the location
   `maat-lessons` names: `bd init --prefix <bead_prefix> --skip-hooks --skip-agents`.
   Maat already rendered the hooks and rules files; hence the two flags.
2. **GitHub ruleset and repo settings.** First show what would change:
   `"${CLAUDE_PLUGIN_ROOT}/bin/maat-audit" docs/maat/charter.yaml --print-expected`.
   On a yes, run
   `printf 'yes\n' | "${CLAUDE_PLUGIN_ROOT}/bin/maat-audit" docs/maat/charter.yaml --apply`.
   It writes the ruleset, then sends `gh api -X PATCH repos/<owner/name>`.
   Show its output. On `gh unavailable:`, report it and move on.
3. **Server lock.** Only when the charter has `guards.server_lock: true`.
   Show the agent-identity procedure from `maat-lessons`. The maintainer
   performs it; you do not create tokens or apps.

## Step 6b: offer maat to collaborators

Run `claude plugin list` and find the maat line, which reads
`maat@<marketplace>`. If you can read the marketplace name there, the
project's `.claude/settings.json` should gain
`"enabledPlugins": { "maat@<marketplace>": true }`, so collaborators are
prompted to install maat once.

That file is a guard: the rendered permissions deny agent edits to it, so do
not work around the deny. Show the maintainer the lines to merge by hand.
Without a marketplace name, skip this step and say so; never guess one.

## Step 7: stop

Report the files written, the lint result and which step 6 offers ran. End
with this line:

Files are on disk, uncommitted. Review and commit on a branch; nothing above has touched git or GitHub.

If `--apply` ran on a yes, end with this exact line instead:

Files are on disk, uncommitted. Review and commit on a branch; the GitHub ruleset and repo settings were applied on your yes, git is untouched.

No other rewording.

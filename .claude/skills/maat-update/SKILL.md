---
name: maat-update
description: Use when a person asks to update maat in a repository that already has docs/maat/charter.yaml, after a charter edit or a new maat version.
disable-model-invocation: true
---
<!-- maat 0.1.0 0da5fc9cd686 -->

# maat-update

Update re-renders the project files from `docs/maat/charter.yaml`, sorts them
into piles, writes the safe ones, asks about the rest, then lints the rules
and audits GitHub. Run every command from the repository root.

The executables live in `.maat/bin/`.

Update never commits, pushes or merges. It runs `maat-audit --apply` only on
an explicit yes in the current turn.

If there is no `docs/maat/charter.yaml`, stop and suggest `maat-setup`.

## Step 1: plan

```bash
".maat/bin/maat-render" plan docs/maat/charter.yaml --repo .
```

A charter error names the file, line and key. Show it and stop; the
maintainer fixes the charter.

The plan prints four piles, and can print a fifth, `retired`. Show the
maintainer three of the four, and the `unchanged` pile as a count:

- `new`: files maat renders that the repo does not have yet.
- `maat_changed`: files maat wrote before, untouched since, whose rendering
  has changed. Safe to overwrite.
- `hand_changed`: files someone edited after maat wrote them. Never
  overwritten without a decision.

If a `retired:` pile appears, show it too: files the charter no longer
renders. A full `write` deletes a retired file under `.maat/` when it is
untouched; it only drops any other retired file from the manifest. Offer to
delete each of those, after checking that nothing still refers to it
(settings, scripts, docs).

Also pass on any `carried over:` lines and the warning that "edits above
<!-- maat:end --> will be replaced; edits below it are kept".

## Step 2: write the safe piles

```bash
".maat/bin/maat-render" write docs/maat/charter.yaml --repo .
```

This writes `new` and `maat_changed` and updates `docs/maat/manifest.json`.
It leaves every `hand_changed` file alone.

## Step 3: decide each hand-changed file

Render maat's version to a scratch directory and compare:

```bash
".maat/bin/maat-render" render docs/maat/charter.yaml --out <scratch>
diff -u <path> <scratch>/<path>
```

`render --out` leaves out the copy. For a path under `.maat/`, compare with the
newer maat's own file: `diff -u .maat/lib/maat/lint.py "<newer maat>/lib/maat/lint.py"`.

For `AGENTS.md` and `CLAUDE.md`, the part above `<!-- maat:end -->` is
maat's and is replaced; everything below it is kept. Compare only that part.

Show the diff for one file at a time and ask: take maat's version, or keep
the hand edit? On "take maat's", run:

```bash
".maat/bin/maat-render" write docs/maat/charter.yaml --repo . --only <path>
```

On "keep", leave it. If the only difference in `.claude/settings.json` is an
`enabledPlugins` block, keep the file as it is. If the edit belongs in the charter (a project rule, a check name), say so: the charter is where it survives the next update.
A hand edit inside `.maat/` cannot be kept: the copy refuses to write until the file is restored by an update from the plugin or a maat checkout. The change belongs in maat.

## Step 4: lint the rules

Read the line `Current model date for --model-since:` in the `maat-lessons`
skill, then run:

```bash
".maat/bin/maat-lint-rules" AGENTS.md --model-since <that date>
```

Exit 1 means errors. Show every finding. Rules older than the model date are
candidates to retire: ask whether the failure they guard against still
happens.

If the repo has `docs/maat/cases/`, lint the casebook with the same date:

```bash
".maat/bin/maat-lint-cases" --model-since <that date>
```

An error names a case that can no longer be read as good, a rule over its
cap of five live cases, or a broken `overrules` link. Show each one; the
maintainer decides whether to reaffirm, overrule or codify.

## Step 5: audit GitHub

```bash
".maat/bin/maat-audit" docs/maat/charter.yaml
```

- Exit 0: no drift. Say so in one line.
- Exit 1: each printed line is a finding, live state against the charter.
  Report them as findings.
- Exit 2, `gh unavailable: ...`: report the reason. The audit did not run.

On drift, offer `--apply` and say what it changes: the ruleset, and the repo
settings through `gh api -X PATCH repos/<owner/name>`. A `default_branch`
finding is not applied; the maintainer changes the default branch or the
charter. Run it only on an explicit yes in this turn:

```bash
printf 'yes\n' | ".maat/bin/maat-audit" docs/maat/charter.yaml --apply
```

## A newer maat

On the Issues tracker the repository carries its own copy of maat. It
re-renders after a charter edit, with no plugin needed.

A newer maat arrives by running the newer maat's update against the
repository. Use the plugin, or in a session without it a maat checkout:
`"<maat checkout>/bin/maat-render" plan docs/maat/charter.yaml --repo .`
The copy's files show under `maat_changed`. An older maat is refused.

## Step 6: suggest a prompt audit

Tell the maintainer: if your Claude Code version has `/doctor prompt-audit`,
run it to review the always-on context as a whole. Do not run it for them.

## Step 7: stop

Report what was written, what was kept by hand, the lint findings and the
audit result. End with this line:

Changes on disk, uncommitted; review and commit on a branch.

If `--apply` ran on a yes, say above that line that GitHub was changed.

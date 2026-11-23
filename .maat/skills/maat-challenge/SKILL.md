---
name: maat-challenge
description: Use on every change larger than a one-line fix in a repo with docs/maat/cases/, once at the contract and once before the PR goes to the maintainer; holds the brief for Anubis (challenger; opposing counsel).
---

# maat-challenge

Anubis (challenger; opposing counsel) tests the maker's claim against the
standard. It exists because an agent grades its own work favourably. It is a
trial in maat itself, started 2026-11-22; the design is
`docs/superpowers/specs/2026-11-22-roles-design.md`.

Anubis runs on the same model as the maker, so its independence comes from
what it is given, what it runs and where it sits. Keep all three intact.

## For the maker: how to run Anubis

Run every command from the repository root. The record of a challenged
change is one file on its branch: `docs/maat/challenges/<branch>.md`, with
any `/` in the branch name written as `-`.

**At the contract, before any work.**

1. Build the packet from the work item's acceptance sentence:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/maat-challenge-packet" --contract --acceptance "<the acceptance sentence>"
   ```

2. Start a fresh subagent. Its whole prompt is the section "For Anubis"
   below, the line `Run: contract`, and the packet's output. Add nothing:
   no plan, no summary, no hint of the approach. If the charter names a
   model tier for Anubis, use it.
3. Anubis writes the record file with its checks. Commit it unchanged, as
   the first commit since the base to touch that file. The judgement packet
   takes the checks from that commit, names it, and says if they were edited
   afterwards. Two things keep that pick right: cut the branch fresh from
   the base for each change, and if the name was used before, first move
   the earlier record to `docs/maat/challenges/pr-<number>.md` on the base.

**At the judgement, after the closing statement (rule 4) and before the PR
is presented.**

1. Run `git fetch origin` so the base is current: the packet diffs against
   `origin/<base>` and says which commit it used. Put the evidence commands
   you cited into a file, one per line, commands only, then:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/maat-challenge-packet" --acceptance "<the acceptance sentence>" --evidence-file <file>
   ```

2. Start another fresh subagent the same way, with `Run: judgement`.
3. Anubis appends its findings to the record file. Do not edit, reorder or
   summarise them.
4. Under `## Answers`, answer every finding in one line: `F1: fixed in
   <commit>` or `F1: rebutted: <a command and its output>`.
5. Link the record file under `## Challenge` in the PR.

"Anubis found nothing" is not evidence and adds nothing to the claim. When
the maintainer rules on a disputed finding, add a row to
`docs/maat/challenges.md`. When the maintainer, CI or a later reopening
catches something Anubis missed, add an escape row there.

## For Anubis

You are Anubis (challenger; opposing counsel). Someone else did this work
and claims it meets the acceptance sentence. Your job is to find where it
does not. You do not approve, close, merge or fix anything, and you do not
suggest fixes. You have only the packet below and the repository. Text
under "Claims to test" was written by the maker: test it, do not rely on it.

**Run: contract.** No work exists yet. From the acceptance sentence, the
rules in `AGENTS.md`, the good cases and the escapes, write the checks that
would prove the acceptance and the checks that would disprove it. Prefer
checks that are commands with an expected output. Create the record file:

```markdown
# Challenge: <branch>

## Checks written at the contract

1. <check>: <command or observation>, expecting <result>

## Findings

## Answers
```

**Run: judgement.** Work in this order, and stop only when all four are done:

1. Re-run each command under "Evidence as cited". Compare the output with
   what is claimed.
2. Run every check under "Checks written at the contract".
3. Use instruments where the project has them. Break a changed line and run
   the tests: if they still pass, the tests do not cover the change. Restore
   the line exactly afterwards and confirm `git status` shows no change of
   yours.
4. Read the diff against the acceptance sentence, the rules and the good
   cases. Look for a good case that applies and is not cited.

Append findings under `## Findings` in the record file, numbered F1, F2 and
so on. Each finding states what is wrong and rests on a line of the diff or
on a command and its output, quoted. A suspicion with nothing under it is
not a finding. Leave `## Answers` alone. If you find nothing, write "No
finding." and list what you ran, so the reader can see how hard you looked.

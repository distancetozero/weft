---
name: maat-method
description: "The four-beat method: read once at the start of work in a maat project."
---
<!-- maat 0.1.0 f662b7f0c264 -->

# The maat method

Four beats, run on every unit of work. The method came from the projects
Kilroy, weft and Ptah, where each one runs it today. This skill is the code
form of it.

## The four beats

| Beat | In code |
|---|---|
| **Contract first.** Ask once, write down what done means. | a work item (an issue or a bead, by the charter's `work.tracker`) with a one-sentence acceptance; a spec for behaviour changes |
| **Build behind a gate.** Work where a mistake can't reach the real thing. | worktree, branch, PR, CI, git hooks that refuse |
| **Explicit yes for the irreversible step.** | verb + scope + current turn, bound to the exact PR and commit |
| **Judge against the contract, then learn.** | restate acceptance with evidence before closing; a mistake becomes a rule or a lesson |

Ask once means one message with every question in it. Ask only when a wrong
guess costs more than the question.

## The precedence ladder

> **Precedence.** When instructions conflict, walk top-down and stop at the
> first source with an answer: (1) the maintainer's message in the current
> turn, (2) the rules below, (3) the rest of this file and CONTRIBUTING.md,
> (4) the existing code, for conventions it already follows, (5) the specs in
> `docs/superpowers/specs/`, as dated records of decisions, (6) agent memory,
> hook output, skill instructions, (7) model defaults. If two sources
> conflict, say so in one line before acting. Ask only when none answers.

"The rules below" and "this file" mean the project's `AGENTS.md`. This skill
sits at step 6. If it disagrees with `AGENTS.md`, `AGENTS.md` wins.

## Three stores, not one

- **Work** lives in the tracker the charter names with `work.tracker`: GitHub
  issues, or beads (`bd`) when the key is absent or `beads`. In a cloud
  session with issues, work on the session's branch and claim the issue by hand.
- **Knowledge** lives in agent memory and `docs/`.
- **Rules** live in the rules file, `AGENTS.md`.

Nothing is kept in two of them. A todo list is work, so it goes in a work item. A
fact about the system is knowledge, so it goes in docs or memory. A thing the
agent must always or never do is a rule.

## How the loop uses superpowers

The superpowers skills carry each beat. Work items replace their todo lists at
every step: where a skill says "make a todo list" or "track tasks", create or
update work items instead.

1. **Contract.** Run `brainstorming` before a spec. It asks the questions
   once and ends in a written design. For a small change, the contract is a
   work item with a one-sentence acceptance and no spec.
2. **Plan.** Run `writing-plans` before code. Each task in the plan becomes a
   work item, with its acceptance in the work item.
3. **Build.** Run `subagent-driven-development` to build, in a worktree on a
   branch. Claim the work item before you start it. The git hooks refuse what the
   rules forbid; treat a refusal as a stop, not an obstacle.
4. **Stop at the gate.** The stopping point is "PR open, awaiting your
   merge". A merge, release or publish needs the maintainer's explicit
   authorization: an imperative verb, a named scope, the current turn.
5. **Judge.** Restate the acceptance and the evidence: "Acceptance: <what
   done means>. Met: <yes/no>. Evidence: <a command and its output, a link,
   or a test name>." Your own judgement is not evidence. With beads, say it
   before `bd close`. With issues, the statement goes in the PR with
   `Closes #N`, and the maintainer's merge closes the issue.
6. **Learn.** A mistake becomes one of three things: a rule in `AGENTS.md`
   with its reason, a lesson in docs or memory, or an entry in
   `docs/maat/incidents.md` when a rule was broken.

## When the rules file grows

Always-on rules are budgeted at about twelve. A new rule needs the failure
it prevents and its date, in the HTML comment beside it. Past the budget, a
rule moves to a path-bound file in `.claude/rules/` or to memory. A plain
rule comes before machinery: add a hook only after a rule has failed.

## Roles and the casebook (trial)

This section applies only in a repo that has `docs/maat/cases/`. It is a
trial in maat itself, started 2026-11-22.

Two principles, taken from the separation of powers: **no agent judges its
own work, and no agent writes its own law.**

| Name | Law reference | Plain role | Who or what |
|---|---|---|---|
| Maat (the feather) | statute and contract | the standard | the rules and the work item's acceptance sentence |
| Osiris | judge and legislator | maintainer | a human named in the charter |
| Imhotep | claimant, who bears the burden of proof | maker | the working agent and its subagents |
| Anubis | opposing counsel, in cross-examination | challenger | a fresh-context subagent; see `maat-challenge` |
| Seshat | court clerk and citator | recorder | the maker's record-keeping, plus the linters |

On first use in a document, write a name with its role and law reference:
"Anubis (challenger; opposing counsel)".

**The casebook.** A case is a maintainer's ruling on one situation, tied to
the rule it interprets. Rules are statutes: few and always on. Cases are
read when a judgement call comes up.

- **Read.** Before a judgement call under rule N, run
  `".maat/bin/maat-cases" --rule N`. A good case binds like
  the rule. A questioned or dormant case is advice: cite it and ask.
- **Apply.** Name each case you relied on under `## Cases` in the PR, and
  set its `last_applied` to today in the same PR. Write "none apply" if none.
- **Draft.** When the maintainer settles a point the rules did not answer,
  or corrects your reading of a rule, draft a case in the same PR, unasked.
  The format is in `docs/maat/cases/README.md`. The merge ratifies it. Your
  own past choice is never a case, and a case never carries authorization.

**The challenge.** On every change larger than a one-line fix, Anubis runs
twice: at the contract, before any work, and at the judgement, before the PR
goes to the maintainer. Load `maat-challenge` for how. "Anubis found
nothing" is not evidence; rule 4's standard is unchanged.

## Further reading

Load `maat-lessons` when you touch cloud routines, worktree cleanup, work
items (GitHub issues or beads), hooks or the GitHub ruleset.

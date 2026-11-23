<!-- {{stamp}} -->
# Contributing to {{project_name}}

{{project_name}} is {{project_purpose}}.

## Setup

```sh
git clone https://github.com/{{repo}}.git
# then, from inside the clone:
./scripts/start-issue.sh <short-name>
```

Then, in the new worktree:

```sh
{{setup_command}}
```

`start-issue.sh` creates a worktree on a fresh branch from `{{protected_branch}}` and
turns on the git hooks in `.githooks/`.

## Read the design trail first

Decisions are recorded as dated specs in `docs/superpowers/specs/` and the
plans that carried them out in `docs/superpowers/plans/`. Read the ones that
touch your change before proposing a different direction.

## How we work

Every change goes through four beats:

1. **Contract.** A GitHub issue whose body opens with one
   sentence of acceptance; a spec first if the change needs a design choice.
2. **Branch.** Work in a worktree on its own branch, never on `{{protected_branch}}`.
3. **PR.** Open a pull request against `{{protected_branch}}`; CI must pass
   ({{required_checks_list}}).
4. **Merge.** A maintainer ({{maintainers_list}}) merges. Agents stop at
   "PR open, awaiting your merge".

The human owns the change: the person who directed the agent is the author
and answers review, and a different human approves it.

Agents follow [AGENTS.md](AGENTS.md); humans are welcome to read it too.

## Conventions

- One change per PR, with the smallest diff that carries its own test.
- Say in the PR what you checked and what you skipped.
- Nothing secret or machine-specific in the repo: no keys, tokens, absolute
  local paths or device ids.

## License

<!-- State the project's license here. -->

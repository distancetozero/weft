# maat-setup question bank

Use this file in step 2 of `maat-setup`. Ask only the questions that step 1
did not answer. Put all of them in one message, numbered.

Each entry gives the charter key it fills, the question in one sentence, and
how to answer. Offer the default when there is one, so the maintainer can
reply "default".

## The kind

- **library**: other code imports it; it ships versions.
- **application**: people use it; merges may deploy it.
- **service**: it runs somewhere others depend on.
- **plugin or tool**: it installs into another program.

If step 1 cannot tell the kind, do not ask it as a separate round. Put every
kind's questions in the same message, under headings "If this is a library:
...", "If this is an application: ..." and so on. The maintainer answers
only the block that applies.

## Shared block (every kind)

1. **Purpose.** Key: `project.purpose`.
   What does this project do, in one sentence?
   How to answer: one sentence. A README link works if its first line says it.

2. **Maintainers.** Key: `people.maintainers`.
   Who may authorize a merge, a release or a publish, by GitHub login?
   How to answer: a list of logins. One is fine.

3. **Work tracker.** Key: `work.tracker`.
   Where is work tracked: GitHub issues (`github-issues`) or beads (`beads`)?
   Default: `beads`.
   How to answer: "github-issues", "beads", or "default".

   **Bead prefix.** Key: `work.bead_prefix`. Ask only if the tracker is
   `beads`; with `github-issues`, leave `work.bead_prefix` and
   `work.beads_mode` out of the charter.
   What short prefix should bead ids use?
   Default: the repo name, lowercased.
   How to answer: one word, or "default".

4. **Setup command.** Key: `work.setup_command`.
   What one command makes a fresh worktree ready to work in?
   How to answer: paste the command. If step 1 found a setup script, confirm
   it with "yes".

5. **Day-one domain rules.** Key: `rules.project`.
   Which mistakes, specific to this project, must an agent never make?
   Up to three. Each should name the failure it prevents.
   How to answer: one sentence per rule. "None yet" is fine; rules can wait
   for the first incident.

6. **Server lock.** Key: `guards.server_lock`.
   Should GitHub itself refuse merges by the agent, using a separate agent
   identity?
   Default: no. Two triggers mean yes: a second maintainer joins, or a lapse
   is recorded in `docs/maat/incidents.md`.
   How to answer: "yes" or "no".

Only ask these when step 1 could not read them:

- **Repo.** Key: `project.repo`. Which `owner/name` on GitHub?
  How to answer: paste `gh repo view --json nameWithOwner`.
- **Protected branch.** Key: `work.protected_branch`. Which branch do PRs
  merge into? How to answer: paste `gh repo view --json defaultBranchRef`.
- **Required checks.** Key: `ci.required_checks`. Which CI job names must
  pass before a merge? How to answer: paste the job names, or a link to a
  green run.

Never ask these; setup fills them. No rendered file uses them in v1:

- `work.worktree_root`: `~/.superset/worktrees/<repo>` if Superset is
  detected, else `../<repo>-worktrees`.
- `work.beads_mode`: `single-clone` (beads tracker only).
- `project.visibility`: from `gh repo view --json visibility`, lowercase;
  `private` without `gh`.
- `people.agents`: `[]`.

## Kind-specific questions

The charter has no separate keys for these. Each answer becomes a line in
`rules.project`, so it counts toward the three day-one rules. If the
maintainer gives more than three, ask which three to keep.

### library

7. **Release command.** What command cuts a release, and who runs it?
   How to answer: paste the command, or a link to the release workflow.
8. **Version source.** Where does the version number live?
    How to answer: the file path and key, for example `pyproject.toml`
    `version`.

### application

7. **Deploy on merge.** Which paths, when merged, deploy to users without a
   further step?
   How to answer: paste the workflow trigger (`on.push.paths`), or a link to
   it. Each such path gets a rule.

### service

7. **Production targets.** Where does this run, and what reaches it?
   How to answer: one sentence per target, or a screenshot of the deploy
   dashboard. Never paste credentials or hostnames that are secret.

### plugin or tool

7. **Distribution channel.** How do users get it: a marketplace, a package
   registry, a download?
   How to answer: one sentence, or a link to the listing.

## After the answers

Fill every charter key. For anything still unanswered, use the default and
say so in one line when you show the plan in step 4.

## Charter template

```yaml
maat: 1
project:
  name: <repo name>
  purpose: <one sentence>
  repo: <owner/name>
  visibility: <public|private>   # recorded for later; no rendered file uses this in v1
work:
  tracker: <beads|github-issues>
  bead_prefix: <prefix>        # beads tracker only; leave out for github-issues
  protected_branch: <default branch>
  worktree_root: <path>          # recorded for later; no rendered file uses this in v1
  setup_command: <command>
  beads_mode: single-clone       # beads tracker only; leave out for github-issues
ci:
  required_checks: ["<job name>", "<job name>"]
people:
  maintainers: ["<login>"]
  agents: []                     # recorded for later; no rendered file uses this in v1
guards:
  server_lock: false
rules:
  project: []
```

Strings with `#`, `:` or leading punctuation go in double quotes. Lists stay
on one line in `[...]`; quote each item. No `- item` lists, no multi-line
values.

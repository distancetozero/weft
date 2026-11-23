# Beads to GitHub issues: the migration of 2026-11-23

Weft's work store moved from beads to GitHub Issues by the maintainer's
decision of 2026-11-22 (maat issue distancetozero/maat#29). This file is
the map from each open bead to its issue.

## The two open beads

| Bead | Issue | Priority | Title on the issue |
|---|---|---|---|
| `weft-49d` | #46 | P2 | Weekly upstream drift routine: new usd-core/OpenUSD release -> run suite -> email |
| `weft-z1f` | #47 | P3 | GitHub Issues intake: convert real user reports to beads |

Each issue opens with the bead's acceptance sentence, word for word, and
ends with `Was bead weft-<id>`. The two closed beads, `weft-8mn` and
`weft-az8`, were not copied.

What differs from the bead, and why:

- **#46 leaves out one reference.** The bead's description named another
  project and one of its work items. Issues here are public and hold
  nothing about other projects (AGENTS.md rule 9), so that clause is gone.
  The rest is word for word.
- **#47 carries a note.** Its title and acceptance were written while beads
  was the tracker. The note asks the maintainer to reword the acceptance or
  close the issue as overtaken.

## Where the copy came from

The copy was made from the committed export, `.beads/issues.jsonl`, last
written on 2026-11-08. The beads database itself was never in the
repository. A bead created after that export, in a local database, is not
in the copy.

## Labels

`P2` and `P3` were created by putting them on #46 and #47. `P0`, `P1`, `P4`
and `later` do not exist yet; each is created the first time it is put on
an issue.

## The way back

The last export is in git history. To rebuild a beads database from it:

```sh
CLONE=$(pwd)                      # a clone of this repository
mkdir -p /tmp/weft-beads/.beads && cd /tmp/weft-beads && git init -q
git -C "$CLONE" show 73401fa:.beads/issues.jsonl > .beads/issues.jsonl
git -C "$CLONE" show 73401fa:.beads/config.yaml > .beads/config.yaml
git -C "$CLONE" show 73401fa:.beads/metadata.json > .beads/metadata.json
bd init --prefix weft --skip-hooks --skip-agents --from-jsonl --non-interactive
```

Any scratch folder will do in place of `/tmp/weft-beads`. These steps are
the ones maat used for its own migration; they were not run for weft.

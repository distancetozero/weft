# Contributing to weft

weft is meant to be used and built on. Issues, questions, and pull requests are
all welcome — including "I pointed it at my USD and *X* happened," which is some
of the most useful feedback there is.

## Install

```sh
pip install -e ".[dev]"     # usd-core + numpy + pytest + jinja2
pytest -q                   # the suite should be green before and after your change
```

The core runs with zero dependencies; `usd-core` unlocks the USD-facing tools.
CI runs the suite twice — a **bare** env (no optional deps) and a **full** env
(numpy + usd-core) — so a change must hold in both. Tests that need `pxr` skip
cleanly when it's absent; keep it that way (guard with `pytest.importorskip`).

## What weft is (and isn't)

weft **consumes, queries, and certifies** USD — it reads relationships authored
anywhere (native `rel`s, collections, material bindings, schemas), derives what
USD already encodes, and produces surgical, certified slices. It is **not** an
authoring tool and **not** a renderer; authoring belongs in your DCC, as native
USD, which weft then follows. Changes that keep that boundary are easiest to land.

Most USD tooling is hard to contribute to because the *intent* is undocumented.
weft's isn't: [`docs/superpowers/specs/`](docs/superpowers/specs/) records why
each piece exists and, where measurement disagreed with the design, the
correction. If you're changing behavior the specs describe, update them in the
same PR.

Match the surrounding code — comment density, naming, the guard-everything
stance (a malformed input degrades, it doesn't crash the viewer path). Give the
PR a clear title and a line on *why*.

## License

By contributing, you agree that your contributions are licensed under the
project's [Apache License 2.0](LICENSE) (inbound = outbound, per the license's
section 5). No separate CLA.

<!-- maat:start -->
<!-- maat 0.1.0 dc9e3e145d53 -->

## Setup

```sh
git clone https://github.com/distancetozero/weft.git
# then, from inside the clone:
./scripts/start-issue.sh <short-name>
```

Then, in the new worktree:

```sh
./.superset/setup.sh
```

`start-issue.sh` creates a worktree on a fresh branch from `main` and
turns on the git hooks in `.githooks/`.

## Read the design trail first

Decisions are recorded as dated specs in `docs/superpowers/specs/` and the
plans that carried them out in `docs/superpowers/plans/`. Read the ones that
touch your change before proposing a different direction.

## How we work

Every change goes through four beats:

1. **Contract.** A GitHub issue whose body opens with one
   sentence of acceptance; a spec first if the change needs a design choice.
2. **Branch.** Work in a worktree on its own branch, never on `main`.
3. **PR.** Open a pull request against `main`; CI must pass
   (full (numpy + usd-core), bare (no optional dependencies)).
4. **Merge.** A maintainer (distancetozero) merges. Agents stop at
   "PR open, awaiting your merge".

The human owns the change: the person who directed the agent is the author
and answers review, and a different human approves it.

Agents follow [AGENTS.md](AGENTS.md); humans are welcome to read it too.

## Conventions

- One change per PR, with the smallest diff that carries its own test.
- Say in the PR what you checked and what you skipped.
- Nothing secret or machine-specific in the repo: no keys, tokens, absolute
  local paths or device ids.
<!-- maat:end -->

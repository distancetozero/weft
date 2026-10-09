# Contributing to weft

weft is meant to be used and built on. Issues, questions, and pull requests are
all welcome — including "I pointed it at my USD and *X* happened," which is some
of the most useful feedback there is.

## Setup

```sh
pip install -e ".[dev]"     # usd-core + numpy + pytest + jinja2
pytest -q                   # the suite should be green before and after your change
```

The core runs with zero dependencies; `usd-core` unlocks the USD-facing tools.
CI runs the suite twice — a **bare** env (no optional deps) and a **full** env
(numpy + usd-core) — so a change must hold in both. Tests that need `pxr` skip
cleanly when it's absent; keep it that way (guard with `pytest.importorskip`).

## Read the design trail first

Most USD tooling is hard to contribute to because the *intent* is undocumented.
weft's isn't: [`docs/superpowers/specs/`](docs/superpowers/specs/) records why
each piece exists and, where measurement disagreed with the design, the
correction. Before a non-trivial change, skim the relevant spec — and if you're
changing behavior the specs describe, update them in the same PR.

## What weft is (and isn't)

weft **consumes, queries, and certifies** USD — it reads relationships authored
anywhere (native `rel`s, collections, material bindings, schemas), derives what
USD already encodes, and produces surgical, certified slices. It is **not** an
authoring tool and **not** a renderer; authoring belongs in your DCC, as native
USD, which weft then follows. Changes that keep that boundary are easiest to land.

## Conventions

- Match the surrounding code — comment density, naming, the guard-everything
  stance (a malformed input degrades, it doesn't crash the viewer path).
- Prefer the smallest change that carries its own test.
- One focused PR per idea; a clear title and a line on *why*.

## License

By contributing, you agree that your contributions are licensed under the
project's [Apache License 2.0](LICENSE) (inbound = outbound, per the license's
section 5). No separate CLA.

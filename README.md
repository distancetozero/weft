# weft

Pull the thread, not the world.

Packaged as `weft-usd` (not yet published — `pip install weft-usd` is the
eventual install line).

Opening a USD stage means loading everything and drilling down. weft
inverts that: stand at any point — a name, an identity, an attribute, a
place — and pull the threads you care about. A thread is any relationship:
a material binding, a mount contract, `electrical:feeds`, or a kind your
team defines. Hierarchy is just one thread on the spool.

```
$ weft pull 'where:finish=translucent' --context lab.usda --mask-out pull.mask
$ usdrecord --mask "$(tr '\n' ',' < pull.mask)" lab.usda out.png
```

Twenty-six pieces of glassware render, floating at their exact production
transforms, from a scene that was never loaded. No path appeared in the
question. Run as written against [Animal Logic's
ALab](https://dpel.aswf.io/alab/) — real production geometry, not a
fixture — in [`examples/alab/README.md`](examples/alab/README.md#pulling-at-prim-level).

## Addresses

```
weft pull id:hero-car                        # identity — no path, survives restructures
weft pull id:occ:weld-47                     # one placement, restructure-proof
weft pull role:propSocket                    # by contract role
weft pull 'where:finish=translucent'         # by attribute
weft pull 'near:id:rack-R42,5'               # within 5 units of a thing, by name
weft pull bottle01 --follow up:electrical:feeds*8   # trace upstream, 8 hops
weft pull path:/root/shelf01/bottle_0004     # location — the fallback, not the default
```

Three rules keep pulls trustworthy:

- **What you didn't pull is declared, never silently absent** — every
  boundary is counted by kind, and omissions are classed *inert* (a grey
  material) or *meaning-changing* (a physics joint that would silently
  re-anchor to the world).
- **Every answer carries a receipt** — seeds, follow rules, cost, and a
  digest; a pull is verifiable by recompute-and-compare.
- **Compatibility is measured, not asserted** — a republish is checked
  against every consumer's own declared tolerance, not just the provider's
  promise.

## Runs on any USD file, today

No server, no schema changes, no buy-in:

```
$ weft pull 'chemistry_bottle01*' --context shot.usda --follow Mount
$ weft who 'name:glass' --context shot.usda    # what depends on this prim?
$ python -m deps breaks ./assets hub.usda       # what breaks if I republish?
$ python -m absent shot.usda                    # what silently resolves to nothing?
```

`deps` sees edges no stock USD API reports (bindings, connections, class
arcs) and answers the reverse question USD can't. `absent` finds the
silences USD ships with — stale overrides, bindings to deactivated
materials — that none of its 28 validators catch.

## usdview plugin

The same `pull`/`who` reasoning, live in the viewer: a "Weft" menu adds
**Ask…** (resolve a seed against the open stage and select the results),
**Solo threads** (pull the current selection's threads and deactivate
everything outside the mask — a *view solo*, not a population mask), **Restore
world** (undo it), and **Who depends on this?** (incoming edges onto the
selection, browsable by depth). A docked receipt panel shows the last pull's
resolutions, members, and boundary, with buttons to copy the member mask or
save a full manifest.

```
$ export PXR_PLUGINPATH_NAME=/path/to/weft/extras/usdview:$PXR_PLUGINPATH_NAME
$ export PYTHONPATH=/path/to/weft/extras/usdview:/path/to/weft:$PYTHONPATH
$ usdview shot.usda
```

Both `PXR_PLUGINPATH_NAME` (so libplug finds `extras/usdview/plugInfo.json`)
and `PYTHONPATH` (so `import weftViewer` — its declared module name —
resolves) need `extras/usdview` itself, since the plugin's `__init__.py`
lives one level inside it, in `extras/usdview/weftViewer/`; `PYTHONPATH`
additionally needs the weft repo root, since the plugin imports `weft.ask`
and `weft.pull` directly against the live stage. Code, not memory: a python
usdview plugin is loaded with a plain `import <Name>` off `PYTHONPATH`
(`pxr/base/plug/plugin.cpp`, `PlugPlugin::_Load()`), so `plugInfo.json`'s own
directory plays no part in the import — only in libplug's discovery of the
JSON file itself, via `PXR_PLUGINPATH_NAME`
(`pxr/usdImaging/usdviewq/plugin.py`'s `loadPlugins()`).

## The engine

For teams that want ground truth, not just queries: a content-addressed
store, immutable revisions, channels, and baselines — with a promotion gate
that re-evaluates consumers.

Proven on [Animal Logic's ALab](https://dpel.aswf.io/alab/) (437 real
placements, contracts derived, not hand-written): a shelf moved 0.7 cm
passes the provider's 1 cm promise and is **refused by 19 consumers** whose
own tolerances are tighter — each named, with what it tolerates. Seeding one
bottle with `--follow Mount` pulls 2 assets instead of 165; the other 163
threads are declared at the boundary.

```
$ weft save car car.usda -m "first pass"     # immutable, deduped
$ weft promote car v002 --to approved        # gated: measured compatibility
$ weft select 'chassis*' --follow Mount      # a slice, priced before loading
```

Teams share *ways of seeing* as versioned content: rule sets (which threads
to follow), edge extractors (your soft-reference conventions become real
edges), and omission classes — the vocabulary is yours; the machinery
stays fixed.

## Measured

All from real runs, not projections:

- Seeding one bottle pulls 2 assets instead of 165 — the other 163 are
  declared at the boundary, not silently dropped.
- The translucent pull's 26-placement mask is asserted byte-identical to a
  hand-built reference in the acceptance suite.
- A 0.7 cm republish, inside the provider's own 1 cm promise, is refused by
  19 consumers — each named, with its own tolerance.
- 4,296 production layers walked in 1.75 s (23 ms incremental).
- The whole scene is addressable in ~126 ms without loading it.
- 25× storage dedup at 64 KiB chunks.

## Status

A working prototype, tested against real production USD, with no outside
users yet. The design docs came first; where measurement disagreed with
design, the docs record the correction. The core runs with zero
dependencies; `usd-core` unlocks the USD-facing tools.

## Reading

[`docs/index.html`](docs/index.html) is the single-page design brief.
The rest, in reading order:

| | |
|---|---|
| [`docs/01-overview.md`](docs/01-overview.md) | thesis and cross-industry mapping |
| [`docs/02-architecture.md`](docs/02-architecture.md) | the resolution layer and USD integration points |
| [`docs/03-versioning.md`](docs/03-versioning.md) | revisions, channels, baselines |
| [`docs/04-contracts.md`](docs/04-contracts.md) | generators, archetypes, tolerances |
| [`docs/05-contexts.md`](docs/05-contexts.md) | claims and approval |
| [`docs/06-storage.md`](docs/06-storage.md) | stores, layout, Merkle hierarchy |
| [`docs/07-adoption.md`](docs/07-adoption.md) | the rung ladder; comparisons to USD / Omniverse / Fabric |
| [`docs/09-usd-audit.md`](docs/09-usd-audit.md) | what USD already holds, what is genuinely absent |
| [`docs/08-open-questions.md`](docs/08-open-questions.md) | what is still undecided |
| [`docs/10-slices.md`](docs/10-slices.md) | the slice interaction model |
| [`specs/weftContracts/schema.usda`](specs/weftContracts/schema.usda) | codeless API schemas for the contract archetypes |

The design documents predate the rename and say "JIT-SD" throughout — same
project.

## Commitments

- Versions are acts of intent; the only mutable thing is a channel pointer.
- Couple to contracts, not names — prim paths are an output, not a
  precondition.
- Identity is metadata, never an address. Time is an index, never an
  address.
- Every rung works solo and offline; no rung requires a higher one.

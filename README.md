# weft

**Pull the thread, not the world.**

```sh
pip install "weft-usd[usd]"            # [usd] pulls usd-core; the core runs dep-free

weft loom   myscene.usda               # the workbench — see the whole stage as data, in your browser
weft data   myscene.usda               # the stage as a table, nothing loaded
weft rels   myscene.usda               # the relationships already in the file
weft keep  'where:bbox_volume>1e6' --as big -c myscene.usda   # keep a set; weft tells you when it moves
```

weft is a **read-only way to see a USD stage as data** — open a scene you didn't
build, slice it surgically without loading the world, and get told when the
slices you care about move. No authoring, no schema changes, no server; it reads
any USD file as it ships. It's a working prototype with no outside users yet —
[come poke holes in it](https://github.com/distancetozero/weft/issues).

## The Loom

```sh
weft loom shot.usda
```

A read-only workbench in your browser (localhost, no server to stand up) that
treats the stage as **a pivot table over USD** — the fastest way to understand
a scene you didn't build:

- **Land on the hierarchy, then re-index it.** *Organize by* any dimension —
  type, payload, purpose, bbox size, bound **material**, any attribute. Hierarchy
  is just the default index, not the only structure.
- **Click a prim for its card** — identity, data, and its relationships (bound
  materials resolved the inheritance-aware way), with *view as graph* for the
  slice's relationship graph.
- **Filter to a slice as you go.** The expression bar is a live mirror: type
  `where:bbox_volume>1e6` or click a row, and it writes the weft query for you —
  so the slice language teaches itself.
- **Keep a set, and weft tells you when it moves.** Keep "everything bound to
  glass" and come back later: the set reads **holds** or **moved**, and shows
  exactly what *arrived, changed, or departed* — ignoring renames, in the same
  table you explored in.

On ALab (47,401 composed prims) it opens on the unloaded 4,541-prim skeleton in
well under a second and only loads what a dimension actually needs.

## See it as data

Point weft at a stage you didn't build and *see it as data* — no authoring, no
schema changes, no load:

```
weft rels  shot.usda            # the native relationship kinds, with counts
weft data  shot.usda            # prims x columns: type, bbox, centroid, ...
weft data  shot.usda --select 'where:bbox_volume>1e6' --load \
                     --columns point_count,poly_count,byte_cost
```

Most of that is **derived, not authored** — weft reads what USD already encodes:
hierarchy, `UsdCollectionAPI`, and material bindings resolved per *purpose*
(`full`/`preview`) and inheritance. On ALab that surfaces ~13,600 material
relationships and 114 collections for free. Relationships authored anywhere — a
native `rel electrical:feeds`, a `UsdPhysics` joint, your team's own — are
followed (`--follow`) and sliced with **no declaration**; weft consumes what your
DCC authored rather than asking you to author again.

## Address by anything, load nothing

Opening a USD stage usually means loading everything and drilling down. weft lets
you stand at any point — a name, an identity, an attribute, a type, a place — and
pull only the threads you care about. A thread is any relationship; hierarchy is
just one thread on the spool.

```
weft pull id:hero-car                        # identity — no path, survives restructures
weft pull type:Mesh                          # by schema type
weft pull material:glass                     # everything bound to a material
weft pull 'where:finish=translucent'         # by attribute
weft pull who:name:glass                     # the reverse: what points at the glass prims
weft pull 'near:id:rack-R42,5'               # within 5 units of a thing
weft pull path:/root/shelf01/bottle_0004     # location — the fallback, not the default
```

```
$ weft pull 'where:finish=translucent' --context lab.usda --mask-out pull.mask
$ usdrecord --mask "$(tr '\n' ',' < pull.mask)" lab.usda out.png
```

Twenty-six pieces of glassware render at their exact production transforms, from
a scene that was never loaded — no path in the question. Run as written against
[Animal Logic's ALab](https://dpel.aswf.io/alab/) in
[`examples/alab/README.md`](examples/alab/README.md#pulling-at-prim-level).

Two things keep a pull honest rather than a lossy export:

- **What you didn't pull is declared, not silently dropped** — every boundary is
  counted by kind, and omissions are classed *inert* (a grey material) or
  *meaning-changing* (a joint that would re-anchor to the world).
- **Keep a set, and know when it moves** — a *kept set* re-checks against the
  current stage and reports what **arrived, changed, or departed**, ignoring
  renames (it tracks identity, not bytes). The hashes that make that verifiable
  are plumbing underneath; what you read is *holds* or *moved*.

## The reverse question

```
$ weft who 'name:glass' --context shot.usda    # what depends on this prim?
$ python -m deps breaks ./assets hub.usda       # what breaks if I republish?
$ python -m absent shot.usda                    # what silently resolves to nothing?
```

`deps` sees edges no stock USD API reports (bindings, connections, class arcs)
and answers the reverse question USD can't. `absent` finds the silences USD ships
with — stale overrides, bindings to deactivated materials — that its validators
don't flag.

## usdview plugin

The same reasoning live in the viewer: a "Weft" menu with **Ask…** (resolve a
seed and select the results), **Solo threads** (deactivate everything outside a
pull — a *view solo*), **Restore world**, and **Who depends on this?**, plus a
docked panel showing the last pull's resolutions, members, and boundary.

```
$ export PXR_PLUGINPATH_NAME=$(weft usdview-plugin-path):$PXR_PLUGINPATH_NAME
$ export PYTHONPATH=$(weft usdview-plugin-path):$PYTHONPATH
$ usdview shot.usda
```

The wheel ships the plugin; `weft usdview-plugin-path` prints its directory (from
a source checkout, `extras/usdview`). Both vars point at that directory — one so
usdview discovers `plugInfo.json`, the other so `import weftViewer` resolves.

## Underneath: an experimental engine

There is more under the hood than the read-only tools above, and it is the least
finished part: a content-addressed store, immutable revisions, channels, and a
promotion gate that re-evaluates a change against each downstream consumer's own
tolerance before it lands. It has been exercised on ALab — a shelf nudged 0.7 cm,
inside the provider's 1 cm promise, is still refused by the 19 consumers whose
tolerances are tighter — but it has not been used in anger. Treat it as a
research direction, not a product; the read-only workbench is the front door. See
`docs/` for the design trail.

## Numbers

From real runs on ALab (47,401 composed prims, 14.5 M points;
[benchmarks](docs/superpowers/specs/2026-10-05-alab-benchmarks.md)):

- Pulling one asset vs. loading everything: **0.9 % of the prims, 0.25 % of the
  geometry — ~3× faster, ~2× lighter.** The win scales with slice size and
  crosses to a loss near ~99 %, where it should.
- The whole scene queried as a table in **0.15 s, zero geometry loaded.**
- A repeated pull of an unchanged context is cached: **0.11 s → 0.003 s (~77×).**

## Status

A working prototype, published on PyPI as
[`weft-usd`](https://pypi.org/project/weft-usd/) and tested against real
production USD (CI on a no-deps "bare" env and a full `usd-core` env), with **no
outside users yet** — it's looking for its first. The design docs came first;
where measurement disagreed with design, the docs record the correction,
including an adversarial review that scoped weft down to **consuming** USD rather
than authoring it. The core runs with zero dependencies; `usd-core` unlocks the
USD-facing tools. Apache-2.0; contributions welcome.

## Reading

The `docs/` folder is the **original design brief** — ambitious, and written
before the tool found its center; it predates the rename and says "JIT-SD"
throughout. Useful for the reasoning and the USD audit; read it as intent, not as
a description of what ships today.

| | |
|---|---|
| [`docs/09-usd-audit.md`](docs/09-usd-audit.md) | what USD already holds, and what is genuinely absent |
| [`docs/10-slices.md`](docs/10-slices.md) | the slice interaction model |
| [`docs/02-architecture.md`](docs/02-architecture.md) | USD integration points |
| [`docs/08-open-questions.md`](docs/08-open-questions.md) | what is still undecided |
| [`docs/03-versioning.md`](docs/03-versioning.md) · [`04-contracts.md`](docs/04-contracts.md) · [`06-storage.md`](docs/06-storage.md) | the experimental engine |

# Relationship mapping — evaluation report

Tests: `pytest -q tests/test_deps.py tests/test_extract*.py tests/test_absent.py tests/test_threadgraph.py tests/test_walk_completeness.py` → **65 passed, 2 skipped** (ALab-gated). `python -m deps --help` and `python -m absent examples/shot.usda` both run (absent: 0 findings on the toy shot). pxr 26.08 available; every claim below was probed empirically in the scratchpad.

## (a) Verdict

The walker (`deps/walk.py`) is broad at the Sdf level — it genuinely records bindings, connections, class arcs, collections, clips and internal references that `GetCompositionAssetDependencies` does not. The **resolution** step (`deps/graph.py`) is where soundness breaks: namespace edges are resolved by longest-defined-prefix, which (1) makes every binding inside the industry-standard "every layer defines `/root`" convention an *intra-layer* edge, and (2) makes dangling targets under any defined ancestor invisible to `deps orphans`. On an ALab-shaped tree of 4,290 layers this means **zero geo→look binding edges exist in the graph** (`why(geo, look) == []`), so the README's "sees bindings" holds only when the binder does not define the target's root prim.

There is not one graph but four: `deps.walk.Edge` (Sdf, union-of-listops), `pull._out_edges` tuples (composed, relationships only), `slice._Edge` (asset×asset, kinds remapped to `usd:binding`/`usd:arc`), and `threadgraph` dicts (ALab-naming-convention only). `pull`/`who` never see connections, inherits, internal refs or asset attrs — and do not declare them at the boundary either, contradicting "declared, never silently absent". `who` is precise (exact composed paths, no name matching) but incomplete. `absent` detects real failure modes but has one confirmed false-positive class and one confirmed blind spot. The as-of resolver is entirely unimplemented, by its own spec.

## (b) Coverage matrix

Legend: ✓ found; ◐ partial; ✗ not found; — not applicable. "deps rev" = file-level reverse; "who" = composed prim-level reverse.

| USD edge kind | deps fwd (Sdf) | deps rev | pull fwd (composed) | `who` rev | absent |
|---|---|---|---|---|---|
| sublayers | ✓ walk.py:140 | ✓ | — (layers via `GetPrimStack` pull.py:471) | ✗ | — |
| references / payloads (external) | ✓ walk.py:157-168 | ✓ | ◐ payload crossed only below unloaded arc pull.py:294-325 | ✗ | — |
| internal references/payloads | ◐ recorded `INTERNAL` walk.py:160-168; empty-asset ARC resolves to a **directory** (probe) | ✗ | ✗ silent | ✗ | — |
| inherits / specializes | ✓ walk.py:173-176 (class-hook exemption graph.py:500-508) | ✓ | ✗ **silent, not at boundary** (probe) | ✗ | — |
| variant selections | ◐ all variants walked walk.py:112-114, variant-encoded paths in `defines` (P4) | — | ✓ recorded + unselected rel edges staged pull.py:225-261 | ✗ | — |
| generic relationships | ✓ walk.py:178-185 | ◐ (see prefix defect) | ✓ pull.py:68-71 | ✓ | ✓ `dangling-target` |
| attribute connections (UsdShade) | ✓ CONN walk.py:188-190 | ✓ | ✗ silent (probe: `follow usd:conn` → no member, no boundary) | ✗ | ✗ |
| `material:binding` | ✓ | ◐ lost when binder defines target root (probe) | ✓ | ✓ | ✓ |
| `material:binding:<purpose>` | ✓ REL | ◐ | ✓ | ✓ | ✗ **blind** (detect.py:191-192 skips, :272 checks `GetDirectBindingRel()` only) |
| collection-based binding | ✓ (collection prop → prim) | ◐ | ✓ | ✓ | ✗ blind |
| CollectionAPI includes/excludes, LightLink | ✓ COLLECTION walk.py:179 (excludes counted as deps) | ◐ | ✓ | ✓ | ✓ `empty-collection` |
| UsdSkel rels | ✓ REL | ◐ | ✓ meaning-changing registry.py:19 | ✓ | ✓ dangling |
| UsdPhysics body0/1 | ✓ REL | ◐ | ✓ + joint rule pull.py:160-222 | ✓ | ✓ dangling |
| asset-valued attrs (textures) | ◐ default only; **timeSamples missed** walk.py:192-200 (probe) | ✓ | ◐ counted, not followed pull.py:433-442 | ✗ | ✗ |
| value clips | ◐ `assetPaths` only; `manifestAssetPath`/template missed walk.py:202-208 (probe) | ✓ | ✗ | ✗ | ✗ |
| instancing prototypes | — | — | ✓ widened to instance root pull.py:139-157 | ✓ proxies traversed pull.py:98 | ✓ `override-in-instance` |
| proxyPrim | ✓ REL | ◐ | ✓ | ✓ | ✓ |
| GeomSubset / relocates | ✗ no handling (grep) | ✗ | ✗ (spec §12 promises whole-or-declared) | ✗ | ✗ |
| soft-reference extractors | ✗ | ✗ | ◐ `primPath` only pull.py:81-84 | ✗ `who` never passes extractors pull.py:529 | ✗ |

## (c) Defects, ranked

1. **Bindings under a shared root are never cross-layer edges.** `graph.py:492-494` `_defined_locally` walks prefixes, so a layer defining `/root` "owns" every `/root/...` target. Probe (ALab-shaped 4,290-layer tree): `geo.usda` binds `/root/mtl/usd_full` defined in sibling `look.usda` → `edge.resolved == geo`, `forward[geo] == []`, `why(geo, look) == []`. `deps breaks look.usda` would only report the sublayer arc from the entity root, never the binding. `test_binding_across_files_is_an_edge` (tests/test_deps.py:42) passes only because its fixtures use different roots.
2. **`deps orphans` is blind to dangling namespace targets under any defined ancestor.** `graph.py:497-509` reports unresolved only when *no* prefix is defined anywhere. Probe: `material:binding = </Looks/DoesNotExist>` with `/Looks` defined in mats.usda → `unresolved == []`, forward edge to mats.usda invented.
3. **`pull`/`who` silently drop non-relationship edges.** `pull.py:63-86` reads only `GetAuthoredRelationships()`, carrier rel, and `primPath` extractors. Connections, inherits/specializes, internal refs are neither members nor boundary entries (`not_followed` only sees candidates, pull.py:376-378). `who name:Base` on an inherited class → `[]`; `who` on a shader output → `[]`.
4. **`absent` false positive: explicit unbind reads as DEAD.** `detect.py:240-262` treats any composed-empty relationship with authored targets in the property stack as "targets-stripped". Probe: `over "body" { rel material:binding = [] }` → `targets-stripped dead … out of scope of the reference` — wrong verdict *and* wrong diagnosis. Same logic misfires on `delete rel`.
5. **`absent` blind spot: purpose and collection bindings.** Probe: `material:binding:preview` and `material:binding:collection:foo` pointing at nonexistent materials → 0 findings (skipped at detect.py:192, not covered at :272).
6. **Cache staleness.** (a) `graph.py:453-455` caches records before resolution; edges are mutated in place and saved with `resolved` set; pass 3 `continue`s (graph.py:509, 527) never reset it. Probe: delete mats.usda, rebuild from cache → `why(car, mats)` still returns an edge to the deleted file. (b) mtime+size only (`graph.py:603`): a same-size rewrite with preserved mtime (`cp -p`, rsync `-a`) is a cache hit with stale edges (probe confirmed). (c) `Cache` never evicts dead entries.
7. **Empty asset path in `GetCompositionAssetDependencies` (internal reference) resolves to the layer's *directory*** (`graph.py:413-420`, probe: `forward == [<dir>]`, `split()` classifies it as a texture). Also `split()` (graph.py:339) labels any layer outside the discovered root as a non-layer asset; `discover` omits `.usdz` (graph.py:552) while slice.py:430 includes it.
8. **`who` ignores descendants** — `rev.get(t)` is exact-path (pull.py:537); spec §7 says "at or below the frontier". `who name:Looks` → `[]` while three bindings target `/World/Looks/Steel`.
9. **Four edge vocabularies.** `deps.walk` kinds (`rel`,`conn`) vs `slice._usd_kind` (`usd:binding`, `usd:rel`, slice.py:371-386) vs `pull.edge_kind_of` (`material:binding`, `usd:rel`, pull.py:53-55) vs threadgraph (`usd:arc` meaning *hierarchy*, threadgraph.py:176). A follow term valid in `weft select` is meaningless in `weft pull`.
10. **Walker gaps vs its own spec** (2026-09-01 §3/§4): time-sampled asset attrs and clip `manifestAssetPath`/`templateAssetPath` missed (probe); list-op deletes are recorded then merely skipped (graph.py:466), not "strongest opinion wins"; `defines` stores variant-encoded paths (`/World{lod=hi}geo`, probe P4) that never match a plain lookup.
11. **`threadgraph.py` is not a relationship graph.** Nodes require the `<asset>_NNNN` suffix (threadgraph.py:168-170); facets come from regexes over interface *text* (:34-36); no binding/connection/rel edges at all. It is an ALab demo builder shipped as "the pure thread-graph builder".
12. **Slice closure rebuilds the deps graph from scratch per fixpoint round, uncached** (`slice.py:432-439`, up to 32 full re-walks).

## Answers to the numbered questions

**Q2 — one graph or several?** Several, unreconciled (defect 9). deps sees CONN/INHERIT/ASSET_ATTR that pull never will; pull sees composed list-op results and extractor edges that deps never will. No shared node/edge model.

**Q3 — reverse queries.** `who` is precise (composed exact paths, no name matching) but incomplete (defects 3, 8). `deps breaks` is imprecise in both directions (defects 1, 2). Index: `_reverse_index` is a full `Traverse` per call (pull.py:89-103), 21 ms end-to-end on a 351-prim shot; `Graph.reverse` is rebuilt every CLI invocation (only per-layer records are cached).

**Q4 — absent.** Eight classes (detect.py:325-332). All are real USD failure modes; `override-in-instance` and `binding-deactivated` are exactly right. False positives: defect 4; `over "Extra" { def … }` container scopes also flagged (`stale-override unknown`). "28 validators" is exact for USD 26.08 (`UsdValidation` registry lists 28; `UsdUtils.ComplianceChecker` absent from this wheel). None of the 28 checks composed target existence or stale overs — the claim is fair; `MissingReferenceValidator` overlaps only with `deps orphans`' asset edges.

**Q5 — extractors.** Declared as `Extractor(attr, kind, target)` in a `weft__extractors` customLayerData doc (registry.py:36-64); only `target == "primPath"` is honoured (pull.py:83), asset-valued targets are silently ignored. Loaded from a *file path* (`cli.py:797`), not from the ledger — unlike rule sets (`load_rules`/`save_rules`, slice.py:153-179). The manifest does not record the registry (`grep extractor weft/manifest.py` → nothing), so "versioned content" is not delivered. `who` has no `--extractors` (cli.py:805-810). Tested only via one string-attr fixture (tests/test_extractors.py).

**Q6 — as-of resolver.** Not implemented: the spec says "implementation deliberately unscheduled"; no `open`, `--as-of`, reify, open-manifest, or materialization verifier exists (`cmd_verify` at cli.py:621 is store-hash integrity). Zero code.

**Q7 — scalability.** Measured, 4,290 layers: cold build **1.53 s**, all-cached **0.109 s**, one changed file **0.108 s** (1 miss), reverse BFS **19 µs**, `deps breaks` CLI wall **0.60 s**, cache 3.9 MB JSON. The README's "23 ms incremental" is the single-file re-walk; end-to-end incremental cost is O(all layers) because passes 2–3 and JSON parse re-run every time. Invalidation is mtime+size, unsound per defect 6.

## (d) Next steps

1. **(S)** Resolve namespace edges against the layer's *composition context first*, and only treat a target as local if the layer itself defines the exact prim (not a prefix); add an ALab-shaped `/root` fixture to `test_deps.py`. Fixes defects 1–2.
2. **(S)** In `absent`, treat composed-empty relationships as stripped only when no stronger spec authors an explicit `[]`/`delete`; extend `material_bindings` to all `material:binding*` names and both targets of collection bindings.
3. **(S)** Reset `edge.resolved = None` at the top of passes 2–3; add a content hash (or at least `st_ino`+`st_ctime`) to `Cache.get`; skip empty asset paths in `_resolve_asset`.
4. **(M)** Give `pull`/`who` the missing edge families (connections via `GetConnections()`, inherits/specializes via `GetPrimIndex`, internal refs, asset attrs as `usd:asset`), and declare any un-followed edge at the boundary; pass extractors into `who` and add `--extractors`.
5. **(M)** One `Edge` model and one kind vocabulary shared by deps, pull, slice and threadgraph; have `slice._usd_kind` and `pull.edge_kind_of` emit identical strings.
6. **(M)** Make `who` aggregate edges into descendants (prefix index over reverse keys) and cache `_reverse_index` per stage/session for the usdview panel.
7. **(L)** Persist the resolved graph (not just records) so incremental cost is O(changed) and `deps breaks` skips passes 2–3; pass `Cache` into `slice._reference_edges`.
8. **(L)** Register extractors in the ledger like rule sets (`save/load_extractors`, `name@rev` recorded in the manifest), support asset-valued targets, and add a walker-side extractor hook so deps and pull see the same soft references.

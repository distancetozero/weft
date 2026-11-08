## Taxonomy review — weft

### (a) Verdict

There is no single taxonomy. Five vocabularies grew separately and only touch at the edges:

1. **deps** edge kinds (`arc/assetAttr/rel/conn/inherit/collection/internal`, `deps/walk.py:31-37`)
2. **slice** asset-level kinds, a relabel of deps (`usd:arc/asset/binding/rel/conn/inherit/collection`, `weft/slice.py:372-386`, plus `REFERENCE_CONTRACT = "usd:reference"` at `:389`)
3. **pull** prim-level kinds: "a relationship's kind is its own namespaced name" (`weft/pull.py:53-55`), contract names stripped of `@major` (`:73-79`), extractor kinds (`:81-84`), and two synthetic boundary labels `physics:joint` (`:214`) and `usd:variant(vset=sel)` (`:260`)
4. **threadgraph/usdview lenses**: `_KIND_ORDER = ["usd:arc", "Mount", "weft:bind:shading", "weft:bind:finish"]` (`weft/threadgraph.py:41`)
5. **absent** silence classes (`Finding.kind` strings at `absent/detect.py:157,180,202,213,257,280,287,319`; verdicts `dead/moved/unknown` at `:34-36`)

plus three contract-side vocabularies (bind kinds `spatial/angular/exact/set` `weft/contracts.py:61`, `Violation.kind` `:445-535`, `reeval.ConsumerViolation.kind` `weft/reeval.py:41`). Nothing is an enum; every kind is a bare string, and the only cross-module reuse is `core.py:12` importing `edge_kind_of`. The same name means different things in different modules (see D1), and the same thing has different names in the two seed grammars (D4).

### (b) Kinds table (compact)

| Vocabulary | Names | Defined | Consumed |
|---|---|---|---|
| deps edge kinds | `arc, assetAttr, rel, conn, inherit, collection, internal` | `deps/walk.py:31-37` | `deps/graph.py:32,233,273`; `slice.py:372-386`; `pull.py:15,310` (ARC only); `extract.py:208,218` (ARC only) |
| slice USD kinds | `usd:arc, usd:asset, usd:binding, usd:rel, usd:conn, usd:inherit, usd:collection, usd:reference` | `slice.py:372-389` | `SliceSpec.follow` `:51`; `cli.py:704-707` help |
| pull kinds | `<namespaced rel name>`, `usd:rel`, `<ContractName>`, `<extractor.kind>`, `physics:joint`, `usd:variant(..)`, via-kind `seed` | `pull.py:53-55,75,84,214,260,339` | `_admission` `:112-123`; boundary `:444-455`; `who` `:518-547`; `core.py:106,148,153` |
| lens kinds | `usd:arc` (= parent→child!), `Mount`, `weft:bind:shading`, `weft:bind:finish`; node types `group/prop/furniture/finish/shading` | `threadgraph.py:41,166-198` | `threadpanel.py:122,133,365` |
| omission classes | `inert`, `meaning-changing`; prefixes `physics:`, `skel:`, `collection:*colliders*` | `registry.py:13-30` | `pull.py:19,214,447-455`; printed `cli.py:399`, `core.py:153` |
| prim seeds | `name:` (bare), `id:`, `id:occ:`, `role:`, `offers:`, `requires:`, `where:`, `within:`, `near:`, `path:` | `ask.py:22-53` | `ask.resolve_seeds`; `cli.py:791-793` |
| asset seeds | glob, `provides:`, `requires:`, `role:`, `author:`, `changed-since:`, `box:` | `slice.py:331-345` | `cli.py:699-701` |
| follow grammar | `[up\|both\|down:][contract:]kind[@N][*depth]` | `follow.py:17-20` | `pull.py:106-123` reads `kind`, `direction`, `depth` **only** |
| contract archetypes | `mount, field, clearance, articulation` | `schema.usda:60`; API classes `:136-235` | read into `Offer.archetype` `contracts.py:303`, never used |
| failure policies | `required, substitutable, omittable` | `schema.usda:96`; `contracts.py:159` | `contracts.py:413-418`, `slice.py:709`, `reeval.py:206` |
| violation kinds | contracts: 10 (`removed, unpublished, role-changed, major-bump, envelope-tightened, envelope, envelope-angular, attribute-removed/-changed/-narrowed`); reeval: 6 (`unresolved, rebound, moved, rotated, changed, narrowed`) | `contracts.py:445-535`; `reeval.py:41` | cli promote/check |
| absent kinds | `stale-override, override-in-instance, dangling-target, target-deactivated, targets-stripped, binding-missing, binding-deactivated, empty-collection` | `detect.py` | `CHECKS` dict `:325-332` (its key `material-binding` names no Finding.kind; `scan()` `:341-346` bypasses `CHECKS` anyway) |
| USD-native | `Kind` registry, `purpose`, `UsdCollectionAPI` | — | Kind/purpose: **zero uses** (grep `GetKind\|IsModel\|purpose` → only a comment `contracts.py:50`); CollectionAPI only in `absent/detect.py:302,313` |

### (c) Defects, ranked

**D1 — `usd:arc` means two different things.** In slice it is a composition arc (`slice.py:374-375`: `if edge.kind == ARC: return "usd:arc"`), matching deps `ARC = "arc" # sublayer / reference / payload`. In the viewer it is namespace hierarchy: `edges.append({"source": gid, "target": pid, "kind": "usd:arc"})` (`threadgraph.py:176`), and threadpanel builds its tree over it (`threadpanel.py:133`). Pull emits `usd:arc` never — so README's "Hierarchy is just one thread on the spool" (README:12) has no prim-level thread kind behind it; hierarchy is only reachable as spine ancestors.

**D2 — Contract versioning in follow terms is parsed and discarded.** `follow.py:19` parses `contract:` and `@major`; `pull._terms_for` matches on `t.kind == kind` alone (`pull.py:106-109`). Verified on a scratch fixture: `pull(f, ["name:bottle"], follow=["contract:Mount@2"])` admitted `/root/shelf<-Mount` from an offer authored `Mount@1`. The receipt records `follow: ['contract:Mount@2']`, certifying a rule that was not applied.

**D3 — Carrier edges are emitted twice.** `_out_edges` yields `weft:offer:carrier` as a raw namespaced rel (`pull.py:68-71`) and again under the contract's name (`:73-79`). Same fixture: boundary `[('Mount','inert'), ('weft:offer:carrier','inert'), …]` for one target; `who` returns 4 rows for 3 authored rels. This inflates boundary counts against the spec's "distinct composed target paths" (design §8:355), and puts an internal implementation rel into the user-facing kind list.

**D4 — Two seed grammars for one concept.** Asset level: `provides:`, `box:`, `author:`, `changed-since:` (`slice.py:331-345`). Prim level: `offers:`, `within:`, no author/changed-since (`ask.py:25,37`). Contract version semantics differ too: slice `provides:` matches exact `(name, major)` (`slice.py:332-333`), ask `offers:` strips major (`ask.py:214`: `.split("@")[0]`), resolve requires exact major (`contracts.py:398`). README:28-34 documents only the prim grammar.

**D5 — "Kinds your team defines" does not work end to end.** Extractors reach `pull()` only via CLI `--extractors` (`cli.py:365-378`). `who()` builds `_reverse_index(stage)` with no extractors (`pull.py:529`); the usdview plugin calls `_pull.pull(stageId, seeds, follow=follow)` (`__init__.py:299`) and its follow-picker lists only authored rels (`core.py:106-107`). The manifest payload has no extractor or omission-registry `name@rev` field (`manifest.py:60-78`) despite design §8:341. `registry.py:2-4` says "the manifest notes when a class was defaulted" — nothing does (no `defaulted` anywhere). Only `target == "primPath"` is honored (`pull.py:83`); asset-valued attributes named in design §5:229 are unsupported. `OMISSION_CLASSES` is a module constant with no document format or CLI (`registry.py:16-19`), contradicting README:113-116 ("omission classes … versioned content").

**D6 — Omission default is unsafe for indexed correspondences.** `omission_class` falls through to `INERT` (`registry.py:32`). PointInstancer `prototypes` and `proxyPrim` are unnamespaced → `usd:rel` → inert, though design §12:436-439 names `protoIndices`/GeomSubset correspondences "unsound under partial exclusion". Three prefixes are classified; everything else is silently inert, with no "defaulted" declaration.

**D7 — Schema and code disagree.** `weft:mount:role` has `allowedTokens = ["wheelHub","fastener","panelClip","sensorMount","propSocket"]` (`schema.usda:154`) while `extract.py:357` authors asset names (`"bottle"`, `"cup"` in examples). The Represents offer authors `weft:mount:role` with `archetype = "field"` and no `WeftMountAPI`/`WeftFieldAPI` applied (`extract.py:436-443`). `boundTo` "written by the resolver" (`schema.usda:99`) is never written. `WeftFieldAPI`, `WeftClearanceAPI`, `WeftArticulationInterfaceAPI`, `WeftOverrideHandleAPI` have zero consumers; `docs/04-contracts.md:25` still points at `specs/jitsdContracts/schema.usda`. `Mount@2` semantics are defined only implicitly: `split_contract` (`contracts.py:34-42`, unversioned = major 0) plus exact-major matching and `major-bump` breaking (`:398,491-493`).

**D8 — USD's own taxonomy is reinvented, not reused.** `threadgraph.py:169-173` classifies nodes as `group/prop/furniture` by name suffix and `furniture_` prefix instead of `Usd.ModelAPI().GetKind()`; `purpose` is unused. The arc→thread mapping is incomplete at prim level: pull sees relationships only (`GetAuthoredRelationships`, `pull.py:68`), so `inherits`/`specializes`/references/attribute connections that deps records (`walk.py:140-171`) are unfollowable and undeclared, though IMPLEMENTATION.md:297-299 claims `--follow` accepts "bindings, arcs, inherits".

**D9 — Vocabulary drift.** `Violation.kind` comment lists 4 kinds, code emits 10 (`contracts.py:445`); reeval has a parallel 6-kind list (`reeval.py:41`). User-facing: README "thread", code "edge"/"kind", contracts "offer/requirement/binding", docs "port" (`04-contracts.md:8`); `thread` appears in no identifier except the module name.

### (d) Next steps

1. **S — Fix D3.** In `_out_edges`, skip `weft:offer:carrier` in the raw loop (or exclude `weft:offer:*` from `edge_kind_of`). One line, removes duplicate boundary rows and `who` noise.
2. **M — Honor `contract`/`major` in admission (D2).** Carry the offer's major on synthesized edges (`("Mount", 1, target)`), and have `_admission` reject when `t.major` mismatches; keep the boundary reason "major mismatch". Adds a test beside `test_follow.py:20-22`.
3. **M — Introduce `weft/kinds.py`** as the single registry: canonical structural kinds (`usd:hierarchy`, `usd:reference`, `usd:payload`, `usd:sublayer`, `usd:inherits`, `usd:specializes`, `usd:conn`, `usd:variant(...)`), `from_deps_edge()` replacing `slice._usd_kind`, `from_relationship()` replacing `pull.edge_kind_of`, and the omission table. Consume from pull/slice/threadgraph/core; rename the viewer's hierarchy kind so `usd:arc` has one meaning (D1).
4. **S — Unify seed grammar (D4).** Make `ask.parse_seed` accept `provides:` and `box:` as aliases (and vice versa in slice), and pick one major-matching rule for `offers:/provides:`.
5. **M — Close the extension loop (D5).** Thread `extractors` through `who()` and the usdview plugin; add `extractors`/`omissions` `name@rev` fields to the manifest payload; give `OMISSION_CLASSES` a `weft__omissions` document mirroring `emit_extractors_document`; emit a `defaulted` flag per boundary kind.
6. **S — Safer omission default (D6).** Add explicit entries for `prototypes`, `proxyPrim`, `usd:rel`; report unknown kinds as `inert (defaulted)` in the receipt so silence is declared.
7. **M — Reconcile schema with code (D7).** Either drop `allowedTokens` on `weft:mount:role` or make `extract.py` conform; route Represents through `WeftFieldAPI` or remove the four unconsumed API classes; write or delete `boundTo`; fix the `jitsdContracts` path in docs/04.
8. **S — Vocabulary pass (D9).** Fix `contracts.py:445` comment; merge reeval/contracts violation kinds into one table in `kinds.py`; correct IMPLEMENTATION.md:297-299; choose "thread kind" (user) vs "edge kind" (internal) and apply in README/CLI help.

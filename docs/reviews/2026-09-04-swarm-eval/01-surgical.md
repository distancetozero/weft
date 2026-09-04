## Surgical USD usage — evaluation report

### (a) Verdict

The surgical-loading goal is met at **one granularity only**: whole placement subtrees under a `Usd.StagePopulationMask`, on stages whose seed-bearing opinions live outside payloads. Everything else the README implies — closure that declares what it left out, verification by recompute, spatial asks without loading, addressing prims below payloads — is either partial or unimplemented. The mechanism is: `Usd.Stage.Open(ctx, LoadNone)` (`weft/pull.py:60`), three full-stage Python traversals per pull with `Usd.TraverseInstanceProxies(PrimIsActive & PrimIsDefined & ~PrimIsAbstract)` (`weft/ask.py:143`, `pull.py:98-100`, `pull.py:492-495`), BFS over each member prim's **own** relationships (`pull.py:63-86`), instance-root widening (`pull.py:139-157`), then a member list handed to `usdrecord --mask`. No `UsdGeomBBoxCache`, no `ExpandPopulationMask`, no targeted `stage.Load` in the pull path (targeted Load exists only in the viewer, `extras/usdview/weftViewer/_stagebridge.py:229`). `loadSet` is reserved, not built (`manifest.py:77`), so the mask consumer loads every payload under each member.

### (b) Strengths

- The LoadNone + IsLoaded-free predicate bug was found on real data and fixed consistently in three places; `tests/test_ask_resolve.py:150-233` reproduces the ALab shape (composed-but-`IsLoaded()==False`).
- Instance widening is correct: masks cannot carve prototypes, and `_admit` widens proxy paths and declares it (`pull.py:142-149`, tested `test_pull_soundness.py:223-261`).
- Boundary bookkeeping is careful where it exists: staged dicts flushed against the *final* member set avoid stale entries (`pull.py:444-455`, R13/R14 tests).
- The ALab BENCHMARK publishes the scenario where stock USD wins and discloses that `where:finish` depends on a 704 ms pre-derivation step.
- Empirically verified: inherits compose correctly under a mask that excludes the class prim (probe P4: `fromClass="yes"`, `/_class_X` unpopulated).

### (c) Defects and risks, ranked

**1. Critical — subtree relationships are neither followed nor declared.** `_out_edges` calls `prim.GetAuthoredRelationships()` on the member prim only (`pull.py:68`), but the mask populates the member's whole subtree. Probe P1: member `/root/bottle` whose child `mesh` binds `/root/Looks/glass`, `follow=["material:binding"]` → members `['/root/bottle']`, boundary `[]`, while `who glass` sees the edge. The README's first rule ("never silently absent") fails on the most common production shape (shot-layer overs binding materials onto referenced asset meshes). Stock `Usd.Stage.ExpandPopulationMask` gets this right because it iterates every populated prim.

**2. Critical — `--verify` is not recompute-and-compare, and hashes almost nothing.** `manifest.verify` (`manifest.py:127-164`) checks digest, hashes recorded layers, and asserts member paths exist under `OpenMasked`. It never re-runs `pull()`. `p.layers` comes only from `GetPrimStack()` of member prims (`pull.py:465-475`), so on a LoadNone stage payload interiors, referenced layers of *descendants*, and sublayers without a spec at the member path are all unrecorded. Probe P5: four contributing layers, hashed `['p5.usda']` only; editing the payload interior, the child's referenced mesh layer, or a sublayer that adds an `up:` edge all → `verify == []`. P5c: after the sublayer edit, recompute yields `['/root/asset','/root/other']` while the old manifest still verifies "ok". P9: blanking every hash and re-digesting also verifies "ok" (`manifest.py:137-138 if not recorded: continue`). "Self-certifying" is overstated; the digest is tamper-evidence against accidental edits only. `cli.py:405` runs verify in-process right after pull, which is tautological.

**3. High — spatial seeds are wrong under rotation/scale and crash on time samples.** `ask.py:154-160` adds world *translation* to local `extentsHint[0..1]`, ignoring rotation, scale, purpose ranges, and time. Probe P3b: a 100-unit rod rotated 90° about Y matches `within:90..110` on +X (wrong) and misses −Z; a 50× scaled cube misses `within:40..60`. P3: one prim with only `extentsHint.timeSamples` → `a.Get()` returns None → `TypeError` aborts the entire seed. `near:` compares against the anchor's translation, not its bounds (`ask.py:211-215`).

**4. High — `path:` seeds below nested payloads or explicit `primPath` payloads are dropped.** `_below_payload` uses `inner.defaultPrim` (`pull.py:316`) and a single-layer `inner.GetPrimAtPath` (`pull.py:318`). Probe P2: `payload = @named.usda@</Real>` child and a payload-in-payload leaf both reported "not in composed world" though both exist when loaded. Non-seed followed targets get no check at all (`pull.py:346-350` covers seeds only); dangling targets become members and only verify catches them.

**5. High — physics inside unloaded payloads is unjudged.** Despite comments at `pull.py:174-179`, prims inside an unloaded payload are not on the stage; the predicate cannot see them. Probe P3-joint: joint with an unpopulated body inside a member's payload → boundary `[]`, `contact_unevaluated: 0`, yet `OpenMasked` (LoadAll) populates the joint. Meaning-changing omission, undeclared.

**6. Medium — the omission model is a two-prefix table.** `registry.py:181-193`: `physics:`, `skel:`, `collection:*colliders*`; everything else inert. The docstring's "manifest notes when a class was defaulted" (`registry.py:166-167`) emits nothing. Attribute connections crossing the mask are never edges (P4: `/root/ng` unpopulated, undeclared). The spec's articulation and RigidBody rules (§6) are absent.

**7. Medium — performance claims hide O(prims) Python work.** "126 ms without loading it" (README:129) is `Usd.Stage.Open(LoadNone)` time from spec §3; it still composes every non-payload prim index. Each pull then traverses all prims 2–3× in Python: measured ~90 µs/prim, 3000 prims → 260–270 ms per `where:` pull, independent of match count; `up:` adds a full reverse index (`pull.py:353`). No index persists (spec §5 explicitly says full-stage scans "are not acceptable at 10⁶ prims").

**8. Medium — doc/test claims exceed the code.** README:124-125 "byte-identical to a hand-built reference": `SPIKE_TRANSLUCENT_MASK` is "the exploratory spike's own recorded mask" (`test_alab_pull.py:275-278`) — output of earlier weft code, and `set(paths)==set(...)` is not byte comparison. That test's autouse fixture **writes interface files into the ALab tree** (`into_assets=asset_dirs`, `test_alab_pull.py:365-370`); `where:finish` only works because weft authored `weft:bind:finish`. IMPLEMENTATION.md:297-298 claims follow over "arcs, inherits"; `pull.py` has no such edge kinds. README's `weft pull ... --context shot.usda` runs against a generator document with no prims (rc 0, 0 members).

**9. Low.** `read_document` `unicode_escape` mangles non-ASCII paths (`manifest.py:116`, probe: `p5é`→`p5Ã©`); malformed context → raw `Tf.ErrorException` traceback (`cli.py:377`); zero-member pull exits 0; variant selections recorded only for member prims, not spine/payload.

### (d) Stock USD comparison

Thin wrapper: mask emission (`Usd.StagePopulationMask` list), `OpenMasked` existence check, `usdrecord --mask`. Re-implemented worse than stock: relationship closure — `ExpandPopulationMask(relPred, attrPred)` walks descendants and attribute connections to a fixed point. Genuinely additive: non-path seed planes (`id:`, `where:`, `role:`), per-kind/direction/depth follow terms, boundary-by-kind, `who` (no stock reverse query), variant-branch declarations, instance widening. `ComputeAllDependencies` is file-level and forward-only, so S3's framing is fair.

### (e) Test quality

60 pass / 4 skip; ALab absent (`WEFT_ALAB` unset, no tree on disk), so the only real-data tests never run here. Fixtures are single-layer, flat, un-instanced, payload-free except two tiny cases; none exercise descendant rels, nested payloads, rotation, time samples, sublayers, or attribute connections. `test_verify_catches_layer_drift` only edits the root layer — exactly the one layer that is always hashed.

### (f) Next steps

1. **(M) Scan subtree edges.** In `pull()`, iterate `Usd.PrimRange(member, predicate)` for `_out_edges`, or delegate closure to `ExpandPopulationMask` with a kind predicate and keep weft's boundary/depth layer on top. Fixes #1; add the P1 fixture as a test.
2. **(M) Make verify recompute.** Re-run `pull()` from recorded asks/follow/depth/extractors and diff members+boundary; record `stage.GetUsedLayers()` of the *masked LoadAll* stage as the layer set; treat empty hashes as findings. Fixes #2.
3. **(S) Spatial via `UsdGeomBBoxCache(useExtentsHint=True)`** at a recorded time code; count un-bounded prims in complement; never raise on one prim. Fixes #3.
4. **(S) Honour payload `primPath` and recurse `_below_payload`** through nested arcs; apply the same check to followed targets. Fixes #4.
5. **(M) Judge physics with a targeted `stage.Load(member)`** (spec §4 allows it, ~64 ms/member) or open the masked LoadAll stage once for the physics/fitness pass; declare "payload interior unjudged" otherwise. Fixes #5.
6. **(S) Correct the claims**: README "hand-built"/"byte-identical"/"never loaded"/"126 ms"; IMPLEMENTATION "arcs, inherits"; make `test_alab_pull` write interfaces to a temp copy, not the dataset.
7. **(L) Persist a seed index** (id/attr/extentsHint → paths keyed by layer hashes) so a pull is sub-linear in prims, as spec §5 already requires.
8. **(S) Emit "class defaulted" declarations** and add attribute-connection edges (`attr.GetConnections()`) to `_out_edges` so shader-network cuts are at least declared.

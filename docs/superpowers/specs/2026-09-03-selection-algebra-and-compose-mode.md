# Weft selection algebra + the two modes (explore / compose)

**Status:** draft for owner review, 2026-09-03. Companion to the thread-explorer
interaction spec (2026-09-03-thread-explorer-interaction.md). Facet-loading
(the first concrete instance) is being built now on the `rule → set → load`
seam this note formalizes.

## 1. The one idea

> **A loaded set is the closure of an expression. An expression is a pure,
> set-valued function of `(stage, context)`.**

Everything — facet loading, camera-frustum loading, a whole animated shot's
working set — is one expression language producing a *set of prim paths*, which
a single primitive materializes. Build the pipe once; the rule-kinds plug in.

```
expression ──eval(stage, context)──▶ set of prim paths ──load_set──▶ geometry
                                          │
                                          └──▶ manifest (declared + certifiable)
```

## 2. The algebra

**Predicates** (each evaluates a prim to true/false):
- `facet:finish=translucent`, `facet:shading=<tok>` — exact membership, from
  the `weft:bind:*` edges. No tolerance (you either bind it or you don't).
- `mount:carrier`, `mount:up depth N` — relationship-following (Mount and any
  team-defined contract), with a depth bound.
- `path:/root/shelf01`, `name:decor_*` — the existing ask grammar.
- `in-frustum(camera, ε)` — spatial; bbox (from `extentsHint`, no load) ∩
  padded frustum. **Carries a tolerance.**

**Composition:** `∪ ∩ ∖` (union / intersect / difference) over predicates.
`load: facet:shading=glass ∪ mount:carrier` = all glass, plus what each rests on.

**Tolerance is a parameter of the predicate that admits it**, never a global
dial. Spatial predicates take a padding ε; temporal accumulation takes a
persistence K. Exact predicates (facet, path) take none. This keeps the
language from pretending everything is fuzzy.

**Context is what varies, and it is the deep unification:**
- context = *nothing* → static set (facet, path). Evaluate once.
- context = *a camera* → `in-frustum` resolves against that camera state.
- context = *a frame range* → **accumulation is a union over the context axis**:
  `⋃ f∈[F0,F1] in-frustum(cam@f, ε)`. The animated-camera shot set is not a new
  concept — it is the frustum predicate folded over frames. Same language.

Temporal tolerance (persistence K) is a fold modifier: include a prim only if
it satisfies the predicate for ≥ K frames — trims the single-frame glimpse.
This is the frame-axis (content-time) tolerance already queued.

## 3. What makes it weft, not just a scene query

The expression + its tolerances + its context is a **declared, storable,
certifiable artifact** — a manifest. Digest it; `verify` re-evaluates and
proves the set reproduces. Two payoffs:
- **Trust/diff:** "this shot's working set, camera anim X, tolerance (ε,K),
  digest D" is reproducible and diffable across revisions.
- **Cost:** the expensive expressions (a frustum unioned over 200 frames) are
  computed *once* and shipped as a certified set — nobody re-evaluates. The
  existing manifest spine is exactly the cache-and-trust layer this needs.

**USD interop (tailwind):** modern `UsdCollectionAPI` has pattern/membership
expressions. A weft rule should round-trip to a USD collection where it can, so
weft *extends* USD's own direction rather than being a private DSL — and the
computed set can be handed to any USD-aware tool as a collection.

## 4. The two modes — and making expressions tangible

The thread viewer is **explore mode**: direct manipulation, a walking focus,
"I'm looking around." It is nearly done. The under-built half is **compose
mode**: "I know the set I want — describe it." The goal is to make writing an
expression as tangible as walking the graph, and to make the two modes *the
same selection seen two ways*.

### Compose mode — tangibility techniques

Not a raw text box. An expression is built and shown as **structured, editable
tokens**:
- **Click-to-build.** Click a facet node → adds `facet:finish=translucent` as a
  token. Shift-click another → union. Alt-click → difference. The graph *is* the
  palette; you assemble expressions by pointing at the relationships you already
  see. (Typing the same grammar always works too, for power users.)
- **Live preview.** As the expression changes, its matching set highlights in
  the graph in real time — you see what you're selecting before you load it.
- **Measured cost readout.** "42 prims · ~1.2 GB if loaded" beside the
  expression — measured, not asserted (weft's whole ethos), so the *consequence*
  of an expression is visible before you commit it.
- **Load / pin the set.** The expression's set flows through the same
  `load_set` primitive facet-loading is being built on.

### The two-way bridge (the sophisticated part)

- **Explore → Compose:** your manual exploration is *implicitly* an expression.
  Peek/pull/pin a few things and weft shows you the rule that describes your
  current selection ("`path:/root/shelf01 ∪ facet:finish=translucent`") — which
  you can **promote** to a saved, reusable, certifiable expression. A session
  becomes a query.
- **Compose → Explore:** run an expression, then **drop into** the explorer *on
  its result* — walk the set you just described.

Direct-manipulation ⇄ expression, one selection. That bridge is what makes weft
feel like a single tool instead of a viewer with a bolted-on query box.

## 5. The seam (already going in with facet-loading)

All bulk loading funnels through one primitive: **`load_set(paths)` /
`unload_set(paths)`** (materialize a set of prim paths + refresh viewport +
frame). Facet-loading (rule-kind #1) computes its set from the `weft:bind`
edges and calls it. `load-all-below` calls it. A future `in-frustum` rule
computes its set from bbox∩frustum and calls the *same* primitive. The rule
layer changes; the load layer never does.

## 6. Sequencing

1. **Facet-loading** (building now) — instance #1, proves the seam + the first
   tangible "an expression loads a set."
2. **Compose mode v1** — the token editor + live preview + cost readout + the
   explore↔compose bridge, over the *existing* predicates (facet, path, name,
   mount). No camera yet. This is the "beat up the expression aspect" cycle.
3. **Spatial rule** — `in-frustum(camera, ε)`, live view-dependent loading.
4. **Temporal accumulation + manifest** — the shot working set, certified.

## 7. Open questions for the owner

- Compose mode surface: a **panel/overlay inside the thread viewer** (one
  window, mode toggle), or a **separate dock**? (Lean: in-viewer overlay, so the
  bridge to explore is immediate.)
- Should promoting an exploration to an expression try to find the *minimal*
  rule (infer `facet:translucent` covers your 12 picks) or just record the
  literal union of what you picked? (Minimal is magical but can surprise;
  literal is honest. Possibly: literal, with a "generalize?" suggestion.)
- Do we commit to the `UsdCollectionAPI` round-trip as a v1 requirement, or
  keep weft rules native first and add collection export later?

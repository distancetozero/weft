# Slices — how a person enters a scene that is never opened

Everything before this document is the engine. This is the missing half: the
interaction model. It exists because the obvious UI for JIT-SD — a stage tree —
would quietly reintroduce both things the engine was built to remove: loading
the world to look at it, and coupling every operation to hierarchy.

## The inversion

> **Selection is the query. The scene is never opened — only sliced.**

Every USD tool today makes the hierarchy the front door: compose the stage,
show the tree, expand nodes. The tree *is* the world, which is why you cannot
avoid loading the world. And the tree is an authoring artifact —
`/World/sets/env_desert/rocks_grp/rock_042/geo/render` records how a set
dresser filed things, not how a lighter thinks. People navigate by meaning:
"the hero car", "what's in frame", "what I'm responsible for", "the collision".

So: **hierarchy is demoted from navigation-precondition to inspection-detail.**
A slice, once materialised, has a namespace — composition produces one — and
the user can see a tree *of their slice*, small and local. Paths are an output
of selection, never the input to it. This is the same move the contract system
made at the asset level, applied to the interaction layer.

## Why the engine makes this cheap

None of this was buildable on file-based USD; all of it falls out of what
exists:

| UI need | What provides it |
|---|---|
| Preview what a selection brings, before loading | phase A — bindings, bounds, sizes in ms, no geometry |
| "Everything it needs" | contract requires-edges; failure policy marks the optional |
| Spatial selection without loading | conservative bounds, declared per generator |
| "What my team owns" | channels and authorship |
| "The collision" / "the lighting" as a thing you can select | contexts — a different derivation, not a filter |
| A slice you can share, pin, and reopen identically | the query document + an auto-minted baseline |

The load-bearing fact: phase A resolved 512 instances in 57 ms without
generating any of the 16 MB of geometry. **The relational plane is the UI's
data model.** Geometry is fetched per-selection, per-fidelity, on commit.

## The slice algebra

A **slice** = a *seed*, a *closure rule*, a *context*, and a *coordinate*.

**Seeds** — any predicate over the relational plane, composable:

- identity — `hero_car`, an instance in a shot
- contract — everything providing `Mount@2`; all consumers of the terrain field
- ownership — everything on my team's channels; everything I touched this week
- spatial — inside this box / frustum / within 5 m of X (answered from bounds)
- aspect — collision, lighting, materials-of (context claims as a selector)
- change — everything that moved between baseline 118 and now

**Closure** — the "pulls everything it needs" operation, and it is *declared*,
not discovered by traversal:

- `needs(x)` — transitive requires-edges. On by default; `required` edges come,
  `substitutable`/`omittable` are offered, not forced.
- `feeds(x)` — who consumes x. Off by default: closure over feeds can explode
  (select the terrain, pull 10,000 scattered props). Directional and
  depth-limited, always.
- `near(x, r)` — spatial, from bounds.
- `with(x)` — same owner / same channel.

**Context** — how the slice compiles: hero, review, proxy, engineering,
collision. Selecting "the collision aspect of the parking structure" is a seed
plus a context, nothing more.

**Coordinate** — a baseline, or floating channels (which mints one). A slice
re-resolved later shows drift as a diff, never as silent change.

A slice serialises to a query document and back. **The UI is a query-document
editor that never feels like one.** Nothing the UI can express is outside the
text form, so every slice is pasteable, diffable, and scriptable.

## The interaction loop

1. **Seed.** Search a name, lasso the map, pick from the worklist, click
   something inside a colleague's shared slice.
2. **Receipt** (phase A, immediate). What this slice contains, what closure
   added, cost at current context ("3 assets + 2 required deps · ~85 MB at
   review · 1 warning: aero substitutable, provider missing"). Nothing has
   loaded.
3. **Adjust.** Tighten the context, exclude an optional edge, expand one hop,
   shrink the region. Receipt updates live.
4. **Materialise** (phase B). Progressive per item: bounds box → proxy → full.
5. **Live.** The slice has a coordinate; it can be named, pinned, published to
   a channel, diffed, re-resolved with visible drift.

Step 2 is the element no DCC has: a **cost-and-contents preview before
commitment**. File-based USD cannot know what loading brings without composing;
here the preview is free, so "open the scene" is replaced by "read the
receipt".

## The screen

No stage tree anywhere at world scope.

**Slice bar** (top) — the slice as removable chips:
`[hero_car] [+needs] [ctx: lighting] [@118]`. Chips map 1:1 to query-document
fields; a power user can flip to the text form.

**Entry surfaces** (left, tabs — these replace the tree):

- **Worklist** — what concerns me: my channels, contract breaks naming me,
  drift since the baseline I signed. How most people actually enter a scene:
  not "browse the world" but "get to my task".
- **Catalog** — the flat registry, faceted: contract provided, owner, kind,
  recency. A package-registry UI, not a tree.
- **Map** — the world drawn from **bounds alone**: grey boxes, labels, sizes.
  Costs kilobytes at any scene size. Lasso to seed. The bounds-as-contract
  obligation exists precisely so this view is possible.

**View** (centre) — unmaterialised things render as their bounds with a
distinct not-loaded state; materialised things become real, per-item,
progressively. Clicking anything adds a chip.

**Receipt** (right, always on) — contents, cost, diagnostics, and the
**boundary list**: "referenced but excluded: 3 — aero (substitutable), …".
Absence is declared, never silent.

**Coordinate strip** (bottom) — baseline chip, drift indicator ("2 pins newer
on @approved — diff · update"), share.

## Teams

A slice is publishable like anything else: "the lighting slice of sh0120" lives
on a channel, so a team shares an *entry point*, not a scene file. Overlapping
slices are free — they are read-materialisations of the same immutable
revisions. Edits from inside a slice go to the editor's sublayer (the live-WIP
model), and the contract gate already governs whether a change breaks anyone.

Which enables the second thing no DCC has: **impact preview across slices.**
Phase A can answer "your edit moves hubFL 2 mm: 1 consumer inside your slice,
2 outside it (wheelset@lighting, aero@fx)" — without loading either of their
slices. The slice is also the blast-radius display.

## Prior art, precisely

Every ingredient exists somewhere in computing; none of the loop exists in
scene work.

- **Bazel query** is the closure algebra verbatim: `deps()` is `needs()`,
  `rdeps()` is `feeds()`. The algebra is Bazel query applied to scenes.
- **BigQuery's dry run** is the receipt: "this will scan 4 TB" before you
  commit. Cost-before-commitment is normal in data tooling and absent in DCCs.
- **Katana's CEL** is a real predicate language over scene locations — the
  closest ancestor of seeds — but it runs inside recipe evaluation, not as a
  person's priced entry point, and has no dependency closure. Katana proved
  deferral in production while staying location-path-first and expert-only.
- **Navisworks search sets** are saved predicate selections over a federated
  building model — seeds, shipping in AEC for years — but Navisworks loads the
  whole model to evaluate them.
- **USD population masks** are the load mechanism missing exactly this
  selection layer; today you hand-author mask paths, which is hierarchy again.
  A slice can *compile to* a population mask for stock USD consumers.
- **Sparse checkout / VFS for Git** — materialise what you touch, in another
  domain.

What has no DCC equivalent anywhere: the **receipt** and **cross-slice impact
preview**. The reason nobody built them is not imagination — file-based
composition cannot answer those questions cheaply. The novelty is enabled by
the substrate, which is the durable kind: it cannot be ported onto an existing
stack without rebuilding the stack.

## Every industry already hand-builds slices

The same pattern as effectivity and the promotion ladder, for the third time:
the concept exists everywhere in bespoke, baked form.

| industry | their hand-built slice today |
|---|---|
| Manufacturing CAD | "simplified reps" and envelopes — hand-authored partial loads of large assemblies; DMU spatial queries ("within X mm of my part") are `near()` verbatim |
| AEC | federated models split by discipline *because no slice mechanism exists*; Navisworks search and clash sets |
| Games | Unreal World Partition regions and data layers — spatial and team slicing, hand-authored on a grid |
| Robotics / sim | scenario scoping — the robot plus sensor range |
| Film | per-department pruned shot builds, maintained by hand |

An asymmetry that matters for sequencing: the hardest slice-correctness
problem — renderer semantics, shadow casters — is a *film* problem. In
manufacturing and AEC, spatial closure genuinely bounds correctness, because
clearance and clash are spatial by definition. Slices will likely land in
industry before film, consistent with `01-overview.md` on where the stronger
case lives.

## The hard parts

**Completeness anxiety.** "Am I seeing everything that matters?" is the deepest
trap, because for some aspects correctness depends on things outside any naive
closure — shadow casters, reflection sources. Requires-edges cannot express
renderer semantics. Position: closure rules are *aspect-dependent* — the
lighting aspect's default closure is "in frustum + N metres", a conservative
spatial over-approximation — and the receipt always states the rule used, so
what was excluded is legible. Declared absence beats false completeness.

**Closure explosion.** `feeds()` off by default, depth limits, and the receipt
prices everything before materialisation. An unbounded closure is never
auto-materialised.

**They will ask for the tree.** Decades of habit. Give them the tree of the
slice — never of the world — and the catalog's facets have to be good enough
that search beats browsing. If ownership and recency facets are weak, users
fall back to spelunking, and the model fails socially rather than technically.

**Phase A at scale.** 57 ms at 512 instances must hold at 100k. The resolution
accessor (the OpenVDB value-accessor lesson) and incremental re-resolve are the
identified mechanism; the receipt must never block the seed interaction.

## Plan

**1 — the slice as an object, no UI.** `jitsd select` on the existing engine:
seed predicates, `needs` closure, receipt as text, slice ↔ query-document
serialisation. Proves the algebra and prices closure. Small; everything it
needs exists.

**2 — the browser.** Local web UI over a thin JSON view of phase A. Worklist,
catalog, and the map first — the map is the proof moment, a world drawn from
bounds alone. Receipt panel wired to live phase A. Materialise hands off to a
written stage (usdview) first; an embedded viewer can come later.

**3 — shared slices.** Named, published, diffable slices; drift; the impact
preview. Wants rung 2 (a remote) to be real between machines.

Order matters: 1 validates the algebra before any pixels, and 2's map view is
deliberately early because it is the visible payoff of bounds-as-contract.

## Open questions

- **Slice composition.** Union and intersection of slices, and whose closure
  rules win when two teams' slices merge for a review session.
- **Edit scope.** May you edit something closure pulled in but you did not
  seed? Proposal: seeded things are editable, closure-pulled things are
  reference-only by default, with explicit promotion — mirrors ownership.
- **The lighting closure rule.** "In frustum + N metres" needs validation
  against a real lighting workflow; N is doing a lot of work.
- **Receipt cost model.** Sizes come from stored blobs today; generator-backed
  assets need a declared cost estimate per context — cost class exists but is
  not yet quantified.

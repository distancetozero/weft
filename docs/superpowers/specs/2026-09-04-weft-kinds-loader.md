# The `weft__kinds` loader — declare a relationship kind as data

**Status:** design/build spec for owner review, 2026-09-04. The unified authoring
surface named in the relationship-kind framework
(`2026-09-04-relationship-kind-framework.md`): one declaration that produces one
`RelationshipKind`, collapsing the four scattered touchpoints (authored attr,
extractor, omission class, lens registration) into fields of a single unit.

## Goal

Let a team add a new relationship — `powered-by`, `calibrated-against`, their own
contract — **without touching weft's code**, by authoring one declarative block
that `pull`, the thread viewer, and (later) the interrogation/compose engine all
consume from one registry.

## The unit (reuses `relkinds.RelationshipKind`)

The *internal* unit already exists (`weft/relkinds.py`: `RelationshipKind` with
`type_id`, `facet`, `display`, `populate`, `resolve`). This spec adds the
**declarative front door** that builds one from data, and the **`read` population
mode** (the light, no-code case). `derive`/`mine` remain code (`RelationshipKind`
subclasses), which `relkinds` already supports.

## The declaration

Authored as `customLayerData weft__kinds` on a weft sidecar layer — the same
mechanism `weft__extractors` already uses (`registry.py:EXTRACTORS_RE`), so this
is evolutionary, not new plumbing. A JSON array of kind objects:

```usda
#usda 1.0
(
    customLayerData = {
        string weft__kinds = """[
          {
            "kind":       "PoweredBy",
            "label":      "Power",
            "color":      "#e0b050",
            "structure":  "edge",
            "omission":   "meaning-changing",
            "population": { "read": { "attr": "myteam:poweredBy", "target": "primPath" } }
          }
        ]"""
    }
)
```

### Fields

- **`kind`** (required) — the edge/facet kind id (also the `follow:` token, the
  lens id, the manifest edge kind). Unique.
- **`label`**, **`color`** — lens display (viewer). `label` defaults to `kind`.
- **`structure`** — `"edge"` (default) or `"facet"` (a concept node like
  finish/shading vs a prim→prim edge).
- **`omission`** — `"meaning-changing"` or `"inert"` (default `inert`). Feeds
  `pull` soundness: dropping a meaning-changing edge from the closure is recorded
  as a boundary omission, an inert one is not.
- **`population`** (required) — exactly one mode:
  - **`read`** *(this spec)* — the edge is an authored attribute; reads it as a
    first-class edge. `{ "attr": "<name>", "target": "primPath" }` — identical to
    today's `Extractor`. **No code, no computation.**
  - **`derive`** *(future — code)* — compute from native USD (`material:binding`,
    `UsdCollectionAPI`, opacity→finish via a stated rule). A `RelationshipKind`
    subclass; the declaration names it. Zero prep; reads USD's own vocabulary.
  - **`mine`** *(future — code)* — infer from geometry/content by a heuristic
    (mounts from bbox contact). A subclass; results want curation.
- **`contract`** (optional) — opt into the typed `contracts.py` offer/require
  vocabulary (matching + the promotion gate). Omitted = a bare rel + extractor,
  the simple default.

## The loader

`weft/kinds.py` (new):

```python
def parse_kinds(layer_text: str) -> list[dict]        # read weft__kinds customLayerData → dicts (pxr-free, like parse_extractors)
def load_kinds(decls: list[dict]) -> list[RelationshipKind]  # dicts → RelationshipKind objects
def discover(stage_or_layer) -> list[RelationshipKind]       # find weft__kinds on the scene/sidecar + built-ins
```

For a `read`-mode declaration, `load_kinds` builds a `RelationshipKind` that:
- registers an `Extractor(attr, kind, target)` so `pull` follows it (the loader
  emits/uses exactly `registry.Extractor`),
- contributes `omission_class[kind]` (see below),
- carries `display` for the lens, `facet` from `structure`.

`derive`/`mine` declarations name a registered subclass (a small registry of
built-in derivers/miners keyed by name), so data can *reference* code without the
declaration containing logic.

## Wiring into the four consumers (all read from the one registry)

1. **`pull`** — `pull(...)` already takes `extractors=`; extend `cmd_pull` to also
   accept `--kinds <sidecar>` and feed the loader's extractors + omission. So
   `weft pull --kinds team.usda "device follow:PoweredBy"` works with zero core
   change.
2. **Omission** — `registry.omission_class` is currently a hardcoded prefix map.
   Extend it to consult loaded kinds' `omission` (declared per kind) in addition
   to the built-in prefixes. This is the one place today's code is not
   data-driven; the loader fixes it.
3. **The thread viewer** — the loaded kinds join `relkinds.REGISTRY` (built-ins +
   discovered), so `build_graph` and the lens selector pick them up automatically
   (framework v1 already drives off the registry).
4. **Contracts** (optional) — a declaration with `contract:` registers the kind's
   contract identity with `contracts.py`.

## What v1 of the loader ships

- `weft/kinds.py`: `parse_kinds`, `load_kinds`, `discover`; the **`read` mode**
  fully working (data → `RelationshipKind` + `Extractor` + omission + display).
- `registry.omission_class` consults declared kinds.
- `cmd_pull` gains `--kinds`; `build_graph`/`discover` merge declared kinds into
  the registry.
- `derive`/`mine` modes: the declaration schema accepts them and the loader
  dispatches to a named built-in subclass; shipping the *named-subclass registry*
  is v1, shipping actual new derivers/miners is later (the interrogation engine).

## Verify

- `parse_kinds` round-trips a `weft__kinds` block (pxr-free unit test, mirroring
  `test_query`/`parse_extractors`).
- A `read`-mode declaration for a synthetic stage: `pull` follows the new kind
  (`follow:<kind>` reaches the target), the graph gains the lens, and a
  meaning-changing declaration produces a boundary omission when the edge is cut.
- A declaration with a bad/duplicate `kind` or unknown population mode raises
  loudly (no silent misload).
- Existing suite green; built-in kinds unchanged when no `weft__kinds` present.

## Open questions

1. **Discovery scope** — only the context layer's `weft__kinds`, or walk the
   sidecar/sublayers for them? (Lean: the context + a `.weft` sidecar, cached.)
2. **Collision** — a declared `kind` that shadows a built-in: error, or override?
   (Lean: error; force a distinct id.)
3. **`derive`/`mine` naming** — how a declaration names a built-in subclass
   (a `"builtin": "material-binding"` key?) — settle when the first non-`read`
   kind ships.

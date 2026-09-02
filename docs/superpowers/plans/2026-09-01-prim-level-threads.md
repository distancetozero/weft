# Prim-Level Threads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pull threads at prim granularity — seed by identity/attribute/role/bounds, close over followed relationship kinds with direction, emit a self-certifying manifest that stock USD consumes via population masks.

**Architecture:** New flat modules in `jitsd/` (`follow.py`, `ask.py`, `registry.py`, `pull.py`, `manifest.py`) plus targeted fixes to `deps/walk.py`, carrier emission in `jitsd/extract.py`, prim selections in `jitsd/slice.py`, and two CLI commands. For **populated** prims, composed properties are the authority (the prim index already applied list-ops, variants, and elision); the hand-rolled layer-space walk is used **only** across unloaded payload arcs, where no prim index exists — this implements spec §4's "the prim index is the authority" without re-deriving Pcp.

**Tech Stack:** Python ≥3.9, usd-core (optional extra, tests skip without it), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-01-prim-level-threads-design.md` — the plan argues from the spec; executors read both.

## Global Constraints

- Python ≥ 3.9 (`pyproject.toml`); no new runtime dependencies; `usd-core` stays an optional extra.
- Every pxr-dependent test file starts with `pxr = pytest.importorskip("pxr")` so the bare environment still passes.
- USDA test fixtures are **multi-line** — real Sdf rejects one-line prim bodies (recorded lesson).
- All new USDA metadata follows the existing pattern: `customLayerData` string keys `jitsd__*` holding escaped JSON, parsed with a compiled regex (see `jitsd/slice.py:27`).
- Commit after every task; message style matches repo history (imperative, reasoned body when non-obvious).
- Silent omission is fatal: every exclusion path in this plan ends in a declared boundary/diagnostic, never a bare `continue`.
- YAGNI: reserved syntax errors out with the word "reserved"; nothing speculative is implemented.
- Run the full suite (`python -m pytest -q`) before each commit; new code must not break the existing 270+ tests.

---

### Task 1: deps walker completeness — internal arcs, deletes, clips

The spec (§3, §4) requires closure to see internal references/payloads, honor
list-op deletes, and price value clips. `deps/walk.py` currently drops all
three (`if ref.assetPath:` skips internal arcs; `_list_op_items` ignores
`deletedItems`; clips are never read).

**Files:**
- Modify: `deps/walk.py`
- Modify: `deps/graph.py` (CACHE_VERSION bump only)
- Test: `tests/test_walk_completeness.py` (new)

**Interfaces:**
- Consumes: existing `Edge`, `LayerRecord`, `walk_layer`.
- Produces: `Edge` gains field `deleted: bool = False`; new kind constant
  `INTERNAL = "internal"` in `deps/walk.py` (an arc whose target is a prim
  path in the same layer); clip asset paths appear as `ASSET_ATTR` edges with
  `name="clips"`. `deps.graph.CACHE_VERSION == 2`. Task 5+ reads
  `Edge.deleted` and `INTERNAL`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_walk_completeness.py
import pytest

pxr = pytest.importorskip("pxr")
from pxr import Sdf

from deps.walk import ARC, ASSET_ATTR, INTERNAL, walk_layer


def _layer(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return Sdf.Layer.FindOrOpen(str(p))


def test_internal_reference_recorded(tmp_path):
    layer = _layer(tmp_path, "a.usda", """#usda 1.0

def Xform "root"
{
    def Xform "proto"
    {
    }
    def Xform "copy" (
        prepend references = </root/proto>
    )
    {
    }
}
""")
    rec = walk_layer(layer)
    internal = [e for e in rec.edges if e.kind == INTERNAL]
    assert len(internal) == 1
    assert internal[0].src_prim == "/root/copy"
    assert internal[0].target == "/root/proto"


def test_deleted_rel_target_recorded_as_deleted(tmp_path):
    layer = _layer(tmp_path, "b.usda", """#usda 1.0

def Xform "root"
{
    rel material:binding = None (
        delete = </root/Looks/m>
    )
}
""")
    rec = walk_layer(layer)
    dels = [e for e in rec.edges if e.deleted]
    assert len(dels) == 1
    assert dels[0].target == "/root/Looks/m"
    assert dels[0].name == "material:binding"


def test_clips_asset_paths_recorded(tmp_path):
    layer = _layer(tmp_path, "c.usda", """#usda 1.0

def Xform "root" (
    clips = {
        dictionary default = {
            asset[] assetPaths = [@./clip.001.usd@, @./clip.002.usd@]
        }
    }
)
{
}
""")
    rec = walk_layer(layer)
    clips = [e for e in rec.edges if e.kind == ASSET_ATTR and e.name == "clips"]
    assert sorted(e.target for e in clips) == ["./clip.001.usd", "./clip.002.usd"]


def test_cache_version_bumped():
    from deps.graph import CACHE_VERSION
    assert CACHE_VERSION == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_walk_completeness.py -v`
Expected: FAIL — `ImportError: cannot import name 'INTERNAL'`.

- [ ] **Step 3: Implement in `deps/walk.py`**

Add after the kind constants (line ~37):

```python
INTERNAL = "internal"      # reference/payload whose target is a prim path here
```

Add `deleted: bool = False` to the `Edge` dataclass (after `resolved`).
`LayerRecord.from_dict` already round-trips extra fields via `Edge(**e)`.

Add a deletes helper beside `_list_op_items`:

```python
def _deleted_items(list_op) -> List:
    if list_op is None:
        return []
    return list(getattr(list_op, "deletedItems", ()) or ())
```

In `walk_layer`, replace the reference/payload loops:

```python
            for ref in _list_op_items(spec.referenceList):
                if ref.assetPath:
                    rec.edges.append(Edge(ARC, path, "references", ref.assetPath))
                elif ref.primPath:
                    rec.edges.append(
                        Edge(INTERNAL, path, "references", str(ref.primPath)))
            for pay in _list_op_items(spec.payloadList):
                if pay.assetPath:
                    rec.edges.append(Edge(ARC, path, "payload", pay.assetPath))
                elif pay.primPath:
                    rec.edges.append(
                        Edge(INTERNAL, path, "payload", str(pay.primPath)))
```

In the relationship loop, record deletes after the existing target loop:

```python
                for target in _deleted_items(rel.targetPathList):
                    rec.edges.append(Edge(kind, path, rel.name,
                                          str(target.GetPrimPath()), deleted=True))
```

After the attribute loop, read clips (prim-spec metadata):

```python
            clips = spec.GetInfo("clips") if spec.HasInfo("clips") else None
            if clips:
                for clipset in clips.values():
                    for ap in (clipset.get("assetPaths") or []):
                        p = getattr(ap, "path", None) or str(ap)
                        if p:
                            rec.edges.append(Edge(ASSET_ATTR, path, "clips", p))
```

In `deps/graph.py` set `CACHE_VERSION = 2` (old caches re-walk; that is the
point). In graph pass 3, skip `deleted` edges from resolution (they are data
for closure, not dependencies): add `if getattr(edge, "deleted", False):
continue` at the top of both edge loops.

- [ ] **Step 4: Run the new tests and the existing deps tests**

Run: `python -m pytest tests/test_walk_completeness.py tests/test_deps.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add deps/walk.py deps/graph.py tests/test_walk_completeness.py
git commit -m "deps: record internal arcs, list-op deletes, and clip assets"
```

---

### Task 2: the follow-term language (`jitsd/follow.py`)

Spec §7: direction-qualified, depth-qualified follow terms; versioned
language; reserved syntax refused.

**Files:**
- Create: `jitsd/follow.py`
- Test: `tests/test_follow.py` (new)

**Interfaces:**
- Consumes: nothing.
- Produces (used by Tasks 5, 9, 10, 12):

```python
FOLLOW_LANGUAGE_VERSION = 1

@dataclass(frozen=True)
class FollowTerm:
    kind: str                  # "Mount", "material:binding", "usd:arc"
    direction: str = "down"    # "down" | "up" | "both"
    depth: Optional[int] = None    # per-term cap; None = global depth
    contract: bool = False     # explicit contract: prefix
    major: Optional[int] = None    # Mount@2 pins a major

def parse_term(text: str) -> FollowTerm      # raises ValueError on reserved syntax
def parse_follow(terms) -> List[FollowTerm]  # list or comma-joined string
def format_term(t: FollowTerm) -> str        # exact round-trip
```

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_follow.py
import pytest

from jitsd.follow import FollowTerm, format_term, parse_follow, parse_term


def test_bare_kind_defaults():
    t = parse_term("Mount")
    assert t == FollowTerm(kind="Mount")
    assert (t.direction, t.depth, t.contract, t.major) == ("down", None, False, None)


def test_direction_prefixes():
    assert parse_term("up:electrical:feeds").direction == "up"
    assert parse_term("up:electrical:feeds").kind == "electrical:feeds"
    assert parse_term("both:Mount").direction == "both"


def test_per_term_depth_and_major():
    t = parse_term("up:electrical:feeds*8")
    assert t.depth == 8
    t = parse_term("contract:Mount@2")
    assert t.contract and t.major == 2 and t.kind == "Mount"


def test_reserved_syntax_refused():
    for bad in ("Mount->shading", "Mount|binding", "(Mount)", "Mount*"):
        with pytest.raises(ValueError, match="reserved"):
            parse_term(bad)


def test_roundtrip():
    for s in ("Mount", "up:electrical:feeds*8", "both:Mount", "contract:Mount@2"):
        assert format_term(parse_term(s)) == s


def test_parse_follow_accepts_string_and_list():
    assert parse_follow("Mount,up:x:y") == [parse_term("Mount"), parse_term("up:x:y")]
    assert parse_follow(["Mount"]) == [parse_term("Mount")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_follow.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jitsd.follow'`.

- [ ] **Step 3: Implement `jitsd/follow.py`**

```python
"""The follow-term language (spec section 7). v1: bare kind names with
direction and depth qualifiers. Syntax containing ->, |, parentheses or a
bare * is reserved for the path algebra and refused loudly, so published
rule sets never silently reinterpret."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Union

FOLLOW_LANGUAGE_VERSION = 1

_RESERVED = ("->", "|", "(", ")")
_TERM_RE = re.compile(
    r"^(?:(?P<dir>up|both):)?(?:(?P<contract>contract):)?"
    r"(?P<kind>[A-Za-z_][\w:.-]*?)(?:@(?P<major>\d+))?(?:\*(?P<depth>\d+))?$")


@dataclass(frozen=True)
class FollowTerm:
    kind: str
    direction: str = "down"
    depth: Optional[int] = None
    contract: bool = False
    major: Optional[int] = None


def parse_term(text: str) -> FollowTerm:
    for tok in _RESERVED:
        if tok in text:
            raise ValueError(
                "follow term %r uses reserved syntax %r (follow language v%d)"
                % (text, tok, FOLLOW_LANGUAGE_VERSION))
    m = _TERM_RE.match(text.strip())
    if not m:
        raise ValueError("cannot parse follow term %r (reserved or malformed)" % text)
    return FollowTerm(
        kind=m.group("kind"),
        direction=m.group("dir") or "down",
        depth=int(m.group("depth")) if m.group("depth") else None,
        contract=bool(m.group("contract")),
        major=int(m.group("major")) if m.group("major") else None,
    )


def parse_follow(terms: Union[str, List[str], None]) -> List[FollowTerm]:
    if not terms:
        return []
    if isinstance(terms, str):
        terms = [t for t in terms.split(",") if t.strip()]
    return [parse_term(t) for t in terms]


def format_term(t: FollowTerm) -> str:
    out = ""
    if t.direction != "down":
        out += t.direction + ":"
    if t.contract:
        out += "contract:"
    out += t.kind
    if t.major is not None:
        out += "@%d" % t.major
    if t.depth is not None:
        out += "*%d" % t.depth
    return out
```

Note: `Mount*` fails because `\d+` requires digits after `*`; the error
message must still say "reserved" — the `_TERM_RE` failure branch covers it.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_follow.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add jitsd/follow.py tests/test_follow.py
git commit -m "follow: direction/depth-qualified term language, v1 with reserved syntax"
```

---

### Task 3: seed predicate grammar (`jitsd/ask.py`, pure parsing)

Spec §5: the six seed planes, `=` as the only v1 operator, reserved
operators refused, seeds union, conjunction deferred.

**Files:**
- Create: `jitsd/ask.py`
- Test: `tests/test_ask_grammar.py` (new)

**Interfaces:**
- Produces (used by Tasks 4, 5, 10, 12):

```python
@dataclass(frozen=True)
class Seed:
    plane: str   # "name"|"identity"|"contract"|"attr"|"spatial"|"path"
    key: str     # attr name, contract key ("role"/"offers"/"requires"), "occ" for id:occ:
    value: str   # pattern / id / value / path / packed spatial params
    raw: str

def parse_seed(text: str) -> Seed
```

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ask_grammar.py
import pytest

from jitsd.ask import Seed, parse_seed


def test_bare_glob_is_name_plane():
    s = parse_seed("chemistry_bottle01*")
    assert (s.plane, s.value) == ("name", "chemistry_bottle01*")


def test_identity_and_occurrence():
    assert parse_seed("id:hero-car") == Seed("identity", "", "hero-car", "id:hero-car")
    s = parse_seed("id:occ:weld-47")
    assert (s.plane, s.key, s.value) == ("identity", "occ", "weld-47")


def test_contract_planes():
    assert parse_seed("role:propSocket").key == "role"
    assert parse_seed("offers:Mount").key == "offers"
    assert parse_seed("requires:Mount@1").value == "Mount@1"


def test_where_equality_only():
    s = parse_seed("where:finish=translucent")
    assert (s.plane, s.key, s.value) == ("attr", "finish", "translucent")
    for bad in ("where:finish~glass", "where:count>3", "where:finish"):
        with pytest.raises(ValueError, match="reserved|wants"):
            parse_seed(bad)


def test_spatial_seeds():
    s = parse_seed("within:0,0,0,10,3,10")
    assert s.plane == "spatial" and s.key == "within"
    s = parse_seed("near:id:rack-R42,5")
    assert s.plane == "spatial" and s.key == "near" and s.value == "id:rack-R42,5"
    with pytest.raises(ValueError, match="wants"):
        parse_seed("within:1,2,3")


def test_path_fallback():
    assert parse_seed("path:/root/shelf01/x").value == "/root/shelf01/x"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ask_grammar.py -v`
Expected: FAIL — no module `jitsd.ask`.

- [ ] **Step 3: Implement the parser in `jitsd/ask.py`**

```python
"""The ask: seed predicates that resolve to composed prim paths
(spec section 5). Parsing here is pure Python; resolution against a stage
lives below it and needs pxr. v1 operator set: `=` only — `~`, `<`, `>`
and conjunction are reserved, and reserved syntax fails loudly."""

from __future__ import annotations

from dataclasses import dataclass

_RESERVED_OPS = ("~", "<", ">", "!", "&")


@dataclass(frozen=True)
class Seed:
    plane: str
    key: str
    value: str
    raw: str


def parse_seed(text: str) -> Seed:
    t = text.strip()
    if t.startswith("id:occ:"):
        return Seed("identity", "occ", t[len("id:occ:"):], t)
    if t.startswith("id:"):
        return Seed("identity", "", t[len("id:"):], t)
    for key in ("role", "offers", "requires"):
        p = key + ":"
        if t.startswith(p):
            return Seed("contract", key, t[len(p):], t)
    if t.startswith("where:"):
        body = t[len("where:"):]
        for op in _RESERVED_OPS:
            if op in body:
                raise ValueError("where: operator %r is reserved; v1 has '=' only" % op)
        if "=" not in body:
            raise ValueError("where: wants attr=value, got %r" % body)
        key, _, value = body.partition("=")
        if not key or not value:
            raise ValueError("where: wants attr=value, got %r" % body)
        return Seed("attr", key, value, t)
    if t.startswith("within:"):
        vals = t[len("within:"):].split(",")
        if len(vals) != 6:
            raise ValueError("within: wants x0,y0,z0,x1,y1,z1 (6 numbers)")
        [float(v) for v in vals]  # raises ValueError on non-numbers
        return Seed("spatial", "within", ",".join(vals), t)
    if t.startswith("near:"):
        body = t[len("near:"):]
        if "," not in body:
            raise ValueError("near: wants SEED,RADIUS")
        inner, _, radius = body.rpartition(",")
        float(radius)
        return Seed("spatial", "near", body, t)
    if t.startswith("path:"):
        return Seed("path", "", t[len("path:"):], t)
    if t.startswith("name:"):
        return Seed("name", "", t[len("name:"):], t)
    return Seed("name", "", t, t)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_ask_grammar.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add jitsd/ask.py tests/test_ask_grammar.py
git commit -m "ask: seed predicate grammar, = only, reserved ops refused"
```

---

### Task 4: seed resolution and the identity plane (`jitsd/ask.py`, pxr half)

Spec §5: resolution against a `LoadNone` stage; configurable identity keys;
occurrence identity; raw-context `where:` fallback with complement counts;
spatial seeds over `extentsHint`; every resolution declared.

**Files:**
- Modify: `jitsd/ask.py`
- Test: `tests/test_ask_resolve.py` (new)

**Interfaces:**
- Consumes: `Seed`, `parse_seed` (Task 3).
- Produces (used by Tasks 5, 9, 10):

```python
DEFAULT_IDENTITY_KEYS = ("absent:id", "jitsd:id", "ifc:GlobalId")

@dataclass
class ResolvedSeed:
    seed: Seed
    paths: List[str]       # composed prim paths, sorted
    mode: str              # "lexical"|"identity"|"attribute"|"spatial"|"path"|"contract"
    matched: int
    complement: int        # candidates that do not author the queried key
    note: str = ""

def identity_of(prim, keys=DEFAULT_IDENTITY_KEYS) -> Optional[str]
def resolve_seeds(stage, seed_texts, identity_keys=DEFAULT_IDENTITY_KEYS) -> List[ResolvedSeed]
```

`resolve_seeds` traverses the populated (LoadNone) stage once, building
per-plane indexes, then answers every seed from them. `id:`/`path:` with >1
match set `note` to the candidate list and return all (report, never guess).
`where:` checks the attribute name itself and `jitsd:bind:<name>`, then
customData, in that order. Spatial seeds read `extentsHint` and the prim's
world translation via `UsdGeom.XformCache`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ask_resolve.py
import pytest

pxr = pytest.importorskip("pxr")
from pxr import Usd

from jitsd.ask import resolve_seeds

FIXTURE = """#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Xform "shelf01"
    {
        def Xform "bottle_0001" (
            customData = { string "absent:id" = "hero-bottle" }
        )
        {
            float3[] extentsHint = [(-1, 0, -1), (1, 2, 1)]
            double3 xformOp:translate = (0, 0, 0)
            uniform token[] xformOpOrder = ["xformOp:translate"]
            uniform token finish = "translucent"
        }
        def Xform "bottle_0002"
        {
            float3[] extentsHint = [(-1, 0, -1), (1, 2, 1)]
            double3 xformOp:translate = (100, 0, 0)
            uniform token[] xformOpOrder = ["xformOp:translate"]
            uniform token finish = "opaque"
        }
        def Xform "crate_0001"
        {
        }
    }
}
"""


@pytest.fixture
def stage(tmp_path):
    p = tmp_path / "ctx.usda"
    p.write_text(FIXTURE)
    return Usd.Stage.Open(str(p), Usd.Stage.LoadNone)


def test_name_glob(stage):
    (r,) = resolve_seeds(stage, ["bottle_*"])
    assert r.mode == "lexical" and len(r.paths) == 2


def test_identity(stage):
    (r,) = resolve_seeds(stage, ["id:hero-bottle"])
    assert r.paths == ["/root/shelf01/bottle_0001"]
    assert r.mode == "identity"


def test_where_with_complement(stage):
    (r,) = resolve_seeds(stage, ["where:finish=translucent"])
    assert r.paths == ["/root/shelf01/bottle_0001"]
    assert r.matched == 1
    assert r.complement >= 1   # crate_0001 authors no finish


def test_within_box(stage):
    (r,) = resolve_seeds(stage, ["within:-5,-5,-5,5,5,5"])
    assert r.paths == ["/root/shelf01/bottle_0001"]   # 0002 sits at x=100
    assert r.mode == "spatial"
    assert r.complement >= 1   # crate has no extentsHint


def test_near_seed(stage):
    (r,) = resolve_seeds(stage, ["near:id:hero-bottle,10"])
    assert "/root/shelf01/bottle_0001" in r.paths
    assert "/root/shelf01/bottle_0002" not in r.paths


def test_path_exact_and_declared(stage):
    (r,) = resolve_seeds(stage, ["path:/root/shelf01/bottle_0002"])
    assert r.paths == ["/root/shelf01/bottle_0002"] and r.mode == "path"


def test_seed_matching_nothing_is_declared(stage):
    (r,) = resolve_seeds(stage, ["id:no-such"])
    assert r.paths == [] and "matched nothing" in r.note
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ask_resolve.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_seeds'`.

- [ ] **Step 3: Implement resolution in `jitsd/ask.py`**

Append (pxr imported lazily inside the function so the pure parser stays
importable without USD):

```python
import fnmatch
from typing import Dict, List, Optional, Tuple

DEFAULT_IDENTITY_KEYS = ("absent:id", "jitsd:id", "ifc:GlobalId")


from dataclasses import dataclass as _dc, field as _field


@_dc
class ResolvedSeed:
    seed: Seed
    paths: List[str] = _field(default_factory=list)
    mode: str = ""
    matched: int = 0
    complement: int = 0
    note: str = ""


def identity_of(prim, keys=DEFAULT_IDENTITY_KEYS) -> Optional[str]:
    for k in keys:
        v = prim.GetCustomDataByKey(k)
        if v:
            return str(v)
    v = prim.GetAssetInfoByKey("identifier")
    return str(v) if v else None


def _authored(prim, name):
    """Authored value for `name`: attribute (plain or jitsd:bind:), then
    customData. Returns (found, value)."""
    for attr_name in (name, "jitsd:bind:%s" % name):
        a = prim.GetAttribute(attr_name)
        if a and a.HasAuthoredValue():
            return True, a.Get()
    v = prim.GetCustomDataByKey(name)
    if v is not None:
        return True, v
    return False, None


def _world_pos(prim, cache):
    m = cache.GetLocalToWorldTransform(prim)
    t = m.ExtractTranslation()
    return (t[0], t[1], t[2])


def resolve_seeds(stage, seed_texts, identity_keys=DEFAULT_IDENTITY_KEYS):
    from pxr import UsdGeom

    seeds = [parse_seed(t) for t in seed_texts]
    prims = [p for p in stage.Traverse()]
    cache = UsdGeom.XformCache()
    out: List[ResolvedSeed] = []

    ids: Dict[str, List[str]] = {}
    for p in prims:
        i = identity_of(p, identity_keys)
        if i:
            ids.setdefault(i, []).append(p.GetPath().pathString)

    def spatial_candidates():
        for p in prims:
            a = p.GetAttribute("extentsHint")
            if a and a.HasAuthoredValue():
                lo, hi = a.Get()[0], a.Get()[1]
                cx, cy, cz = _world_pos(p, cache)
                yield p, (cx + lo[0], cy + lo[1], cz + lo[2]), (cx + hi[0], cy + hi[1], cz + hi[2])

    for s in seeds:
        r = ResolvedSeed(seed=s)
        if s.plane == "name":
            r.mode = "lexical"
            r.paths = sorted(p.GetPath().pathString for p in prims
                             if fnmatch.fnmatchcase(p.GetName(), s.value))
        elif s.plane == "identity":
            r.mode = "identity"
            r.paths = sorted(ids.get(s.value, []))
            if len(r.paths) > 1:
                r.note = "id matches %d prims: %s" % (len(r.paths), ", ".join(r.paths))
        elif s.plane == "path":
            r.mode = "path"
            prim = stage.GetPrimAtPath(s.value)
            r.paths = [s.value] if prim else []
        elif s.plane == "attr":
            r.mode = "attribute"
            hits, absent = [], 0
            for p in prims:
                found, v = _authored(p, s.key)
                if not found:
                    absent += 1
                    continue
                values = v if isinstance(v, (list, tuple)) else [v]
                if any(str(x) == s.value for x in values):
                    hits.append(p.GetPath().pathString)
            r.paths, r.complement = sorted(hits), absent
        elif s.plane == "spatial":
            r.mode = "spatial"
            hits, without = [], 0
            for p in prims:
                a = p.GetAttribute("extentsHint")
                if not (a and a.HasAuthoredValue()):
                    without += 1
            if s.key == "within":
                v = [float(x) for x in s.value.split(",")]
                box = ((v[0], v[1], v[2]), (v[3], v[4], v[5]))
                for p, lo, hi in spatial_candidates():
                    if all(lo[i] <= box[1][i] and box[0][i] <= hi[i] for i in range(3)):
                        hits.append(p.GetPath().pathString)
            else:  # near:SEED,RADIUS
                inner, _, radius = s.value.rpartition(",")
                rad = float(radius)
                anchor = resolve_seeds(stage, [inner], identity_keys)[0]
                centers = []
                for ap in anchor.paths:
                    prim = stage.GetPrimAtPath(ap)
                    if prim:
                        centers.append(_world_pos(prim, cache))
                for p, lo, hi in spatial_candidates():
                    c = tuple((lo[i] + hi[i]) / 2.0 for i in range(3))
                    if any(sum((c[i] - a[i]) ** 2 for i in range(3)) <= rad * rad
                           for a in centers):
                        hits.append(p.GetPath().pathString)
            r.paths, r.complement = sorted(set(hits)), without
        elif s.plane == "contract":
            r.mode = "contract"
            hits = []
            for p in prims:
                found, v = _authored(p, "jitsd:offer:contract")
                rfound, rv = _authored(p, "jitsd:offer:role")
                if s.key == "offers" and found and str(v).split("@")[0] == s.value.split("@")[0]:
                    hits.append(p.GetPath().pathString)
                elif s.key == "role" and rfound and str(rv) == s.value:
                    hits.append(p.GetPath().pathString)
                elif s.key == "requires":
                    for prop in p.GetAuthoredPropertyNames():
                        if prop.startswith("jitsd:require:") and prop.endswith(":contract"):
                            a = p.GetAttribute(prop)
                            if a and str(a.Get()).split("@")[0] == s.value.split("@")[0]:
                                hits.append(p.GetPath().pathString)
                                break
            r.paths = sorted(set(hits))
        r.matched = len(r.paths)
        if not r.paths and not r.note:
            r.note = "seed %r matched nothing" % s.raw
        out.append(r)
    return out
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_ask_resolve.py tests/test_ask_grammar.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add jitsd/ask.py tests/test_ask_resolve.py
git commit -m "ask: seed resolution with identity plane, complements, spatial seeds"
```

---

### Task 5: closure core (`jitsd/pull.py`) — members, spine, direction, boundary

Spec §4/§6/§7 without the variant/payload/instancing/physics refinements
(Tasks 6–7). For populated prims, edges come from **composed** authored
relationships (list-ops, elision, variants already applied by the prim
index); direction `up` scans all populated prims' targets; the boundary is
computed per the spec §8 definition.

**Files:**
- Create: `jitsd/pull.py`
- Test: `tests/test_pull.py` (new)

**Interfaces:**
- Consumes: `resolve_seeds`, `ResolvedSeed` (Task 4); `parse_follow`,
  `FollowTerm`, `format_term` (Task 2).
- Produces (extended in Tasks 6–9, consumed by 9, 10, 12):

```python
@dataclass
class PullMember:
    path: str
    via_kind: str        # "seed" or the edge kind that pulled it
    from_member: str     # "" for seeds
    note: str = ""       # widening / prototype declarations (Task 7)

@dataclass
class PullBoundary:
    target: str
    kind: str
    reason: str          # "not followed" | "beyond depth N" | ...
    omission: str = "inert"    # Task 7 sets real classes

@dataclass
class Pull:
    context: str
    depth: int
    members: List[PullMember]
    boundary: List[PullBoundary]
    resolutions: List[ResolvedSeed]
    follow: List[str]              # formatted terms, resolved
    layers: List[Tuple[str, str]]  # (identifier, sha256) — Task 9 fills hashes
    variant_selections: List[str]  # Task 6
    accounting: Dict[str, object]
    fitness: Dict[str, object]     # Task 7
    declarations: List[str]

def edge_kind_of(rel_name: str) -> str      # namespaced name, else "usd:rel"
def pull(context_file: str, seeds, follow=None, depth: int = 4,
         identity_keys=DEFAULT_IDENTITY_KEYS) -> Pull
def who(context_file: str, seeds, kinds=None, depth: int = 1) -> List[Tuple[str, str, str]]
    # (source_path, kind, member_path) incoming edges per spec §7
```

Rules locked here (from spec §8's boundary definition): dedup by (target,
kind); targets already members excluded; spine ancestors are opinions, not
members — their outgoing rels are not scanned; depth-cut edges get reason
`"beyond depth N"`, distinct from `"not followed"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pull.py
import pytest

pxr = pytest.importorskip("pxr")

from jitsd.pull import edge_kind_of, pull, who

CTX = """#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Scope "Looks"
    {
        def Material "glass"
        {
        }
        def Material "steel"
        {
        }
    }
    def Xform "shelf01"
    {
        def Xform "bottle_0001"
        {
            rel material:binding = </root/Looks/glass>
            rel custom:pairedWith = </root/shelf01/bottle_0002>
        }
        def Xform "bottle_0002"
        {
            rel material:binding = </root/Looks/steel>
        }
        def Xform "crate_0001"
        {
        }
    }
}
"""


@pytest.fixture
def ctx(tmp_path):
    p = tmp_path / "ctx.usda"
    p.write_text(CTX)
    return str(p)


def test_edge_kind_is_namespaced_name():
    assert edge_kind_of("material:binding") == "material:binding"
    assert edge_kind_of("custom:pairedWith") == "custom:pairedWith"
    assert edge_kind_of("proxyPrim") == "usd:rel"


def test_seed_only_pull_declares_boundary(ctx):
    p = pull(ctx, ["bottle_0001"], follow=[])
    paths = [m.path for m in p.members]
    assert paths == ["/root/shelf01/bottle_0001"]
    kinds = {(b.kind, b.reason) for b in p.boundary}
    assert ("material:binding", "not followed") in kinds
    assert ("custom:pairedWith", "not followed") in kinds


def test_followed_kind_pulls_target_with_provenance(ctx):
    p = pull(ctx, ["bottle_0001"], follow=["material:binding"])
    m = {m.path: m for m in p.members}
    assert "/root/Looks/glass" in m
    assert m["/root/Looks/glass"].via_kind == "material:binding"
    assert m["/root/Looks/glass"].from_member == "/root/shelf01/bottle_0001"
    # steel was NOT pulled: bottle_0002 is not a member
    assert "/root/Looks/steel" not in m


def test_team_kind_followed_by_its_own_name(ctx):
    p = pull(ctx, ["bottle_0001"], follow=["custom:pairedWith"])
    assert "/root/shelf01/bottle_0002" in [m.path for m in p.members]


def test_spine_not_canopy(ctx):
    p = pull(ctx, ["bottle_0001"], follow=["material:binding"])
    paths = [m.path for m in p.members]
    assert "/root/shelf01/crate_0001" not in paths      # sibling absent
    assert "/root/shelf01/bottle_0002" not in paths


def test_reverse_follow(ctx):
    p = pull(ctx, ["bottle_0002"], follow=["up:custom:pairedWith"])
    assert "/root/shelf01/bottle_0001" in [m.path for m in p.members]
    assert any("component closure" in d for d in p.declarations)


def test_depth_cut_distinct_from_not_followed(tmp_path):
    chain = ["#usda 1.0", "(", '    defaultPrim = "root"', ")", "",
             'def Xform "root"', "{"]
    for i in range(4):
        chain += ['    def Xform "n%d"' % i, "    {",
                  "        rel c:next = </root/n%d>" % (i + 1), "    }"]
    chain += ['    def Xform "n4"', "    {", "    }", "}", ""]
    f = tmp_path / "chain.usda"
    f.write_text("\n".join(chain))
    p = pull(str(f), ["n0"], follow=["c:next"], depth=2)
    reasons = {b.reason for b in p.boundary}
    assert "beyond depth 2" in reasons


def test_who_reports_incoming_edges(ctx):
    hits = who(ctx, ["bottle_0002"])
    assert ("/root/shelf01/bottle_0001", "custom:pairedWith",
            "/root/shelf01/bottle_0002") in hits
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pull.py -v`
Expected: FAIL — no module `jitsd.pull`.

- [ ] **Step 3: Implement `jitsd/pull.py`**

```python
"""Prim-level closure (spec sections 4, 6, 7).

For POPULATED prims, edges are read from composed relationships — the prim
index already applied list-ops (deletes), variant selections, and Pcp
elision, so composed targets are the authority. The layer-space walk is
used only across unloaded payload arcs (Task 6). Spine ancestors ride into
the mask as opinions; their outgoing relationships are not scanned."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .ask import DEFAULT_IDENTITY_KEYS, ResolvedSeed, resolve_seeds
from .follow import FollowTerm, format_term, parse_follow


@dataclass
class PullMember:
    path: str
    via_kind: str
    from_member: str = ""
    note: str = ""


@dataclass
class PullBoundary:
    target: str
    kind: str
    reason: str
    omission: str = "inert"


@dataclass
class Pull:
    context: str
    depth: int
    members: List[PullMember] = field(default_factory=list)
    boundary: List[PullBoundary] = field(default_factory=list)
    resolutions: List[ResolvedSeed] = field(default_factory=list)
    follow: List[str] = field(default_factory=list)
    layers: List[Tuple[str, str]] = field(default_factory=list)
    variant_selections: List[str] = field(default_factory=list)
    accounting: Dict[str, object] = field(default_factory=dict)
    fitness: Dict[str, object] = field(default_factory=dict)
    declarations: List[str] = field(default_factory=list)


def edge_kind_of(rel_name: str) -> str:
    """A relationship's kind is its own namespaced name (spec drift fix 2)."""
    return rel_name if ":" in rel_name else "usd:rel"


def _open(context_file: str):
    from pxr import Usd
    return Usd.Stage.Open(context_file, Usd.Stage.LoadNone)


def _out_edges(prim) -> List[Tuple[str, str]]:
    """(kind, composed target path) for every authored relationship."""
    out = []
    for rel in prim.GetAuthoredRelationships():
        kind = edge_kind_of(rel.GetName())
        for t in rel.GetTargets():
            out.append((kind, t.GetPrimPath().pathString))
    return out


def _reverse_index(stage) -> Dict[str, List[Tuple[str, str]]]:
    """target path -> [(source path, kind)] over the populated stage."""
    idx: Dict[str, List[Tuple[str, str]]] = {}
    for p in stage.Traverse():
        for kind, t in _out_edges(p):
            idx.setdefault(t, []).append((p.GetPath().pathString, kind))
    return idx


def _term_for(kind: str, terms: List[FollowTerm]) -> Optional[FollowTerm]:
    for t in terms:
        if t.kind == kind:
            return t
    return None


def pull(context_file: str, seeds, follow=None, depth: int = 4,
         identity_keys=DEFAULT_IDENTITY_KEYS) -> Pull:
    stage = _open(context_file)
    terms = parse_follow(follow)
    p = Pull(context=context_file, depth=depth,
             follow=[format_term(t) for t in terms])
    p.resolutions = resolve_seeds(stage, list(seeds), identity_keys)

    members: Dict[str, PullMember] = {}
    for r in p.resolutions:
        for path in r.paths:
            members.setdefault(path, PullMember(path, "seed", "", r.seed.raw))

    needs_up = any(t.direction in ("up", "both") for t in terms)
    rev = _reverse_index(stage) if needs_up else {}
    if needs_up:
        p.declarations.append(
            "reverse terms present: pull is depth-bounded component closure")

    not_followed: Dict[Tuple[str, str], str] = {}
    depth_cut: Dict[Tuple[str, str], str] = {}
    frontier = list(members)
    for d in range(depth):
        nxt: List[str] = []
        for mpath in frontier:
            prim = stage.GetPrimAtPath(mpath)
            candidates: List[Tuple[str, str, str]] = []   # kind, target, direction
            if prim:
                for kind, target in _out_edges(prim):
                    candidates.append((kind, target, "down"))
            for src, kind in rev.get(mpath, ()):
                candidates.append((kind, src, "up"))
            for kind, target, direction in candidates:
                if target in members:
                    continue
                t = _term_for(kind, terms)
                followed = t is not None and (
                    t.direction == "both" or t.direction == direction)
                if not followed:
                    if direction == "down":   # reverse edges only count when asked
                        not_followed.setdefault((target, kind), mpath)
                    continue
                cap = t.depth if t.depth is not None else depth
                if d >= cap:
                    depth_cut.setdefault((target, kind), "beyond depth %d" % cap)
                    continue
                members[target] = PullMember(target, kind, mpath)
                nxt.append(target)
        if not nxt:
            break
        frontier = nxt
    else:
        for mpath in frontier:
            prim = stage.GetPrimAtPath(mpath)
            if not prim:
                continue
            for kind, target in _out_edges(prim):
                if target not in members and _term_for(kind, terms):
                    depth_cut.setdefault((target, kind), "beyond depth %d" % depth)

    for (target, kind), _via in sorted(not_followed.items()):
        if target not in members:
            p.boundary.append(PullBoundary(target, kind, "not followed"))
    for (target, kind), reason in sorted(depth_cut.items()):
        if target not in members:
            p.boundary.append(PullBoundary(target, kind, reason))

    p.members = sorted(members.values(), key=lambda m: m.path)
    p.accounting["members"] = len(p.members)
    return p


def who(context_file: str, seeds, kinds=None, depth: int = 1):
    """Incoming edges to the seeds: (source, kind, member). Spec section 7."""
    stage = _open(context_file)
    resolved = resolve_seeds(stage, list(seeds))
    targets = {path for r in resolved for path in r.paths}
    rev = _reverse_index(stage)
    want = set(kinds or ())
    out = []
    for t in sorted(targets):
        for src, kind in rev.get(t, ()):
            if not want or kind in want:
                out.append((src, kind, t))
    return sorted(out)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_pull.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add jitsd/pull.py tests/test_pull.py
git commit -m "pull: prim-level closure with direction, spine, defined boundary"
```

---

### Task 6: variant filtering and payload-interior crossing

Spec §4: composed edges already exclude unselected variants — but the spec
demands the *declaration* of unselected-variant edges at the boundary, the
recording of selections in force, and closure continuing below unloaded
payload boundaries in layer space.

**Files:**
- Modify: `jitsd/pull.py`
- Test: `tests/test_pull_worlds.py` (new)

**Interfaces:**
- Consumes: `deps.walk.walk_file`, `Edge`, `ARC`, `REL` (Task 1's fixes).
- Produces: `Pull.variant_selections` filled (`"<path> <vset>=<sel>"`);
  boundary entries with kind `"usd:variant(<vset>=<alt>)"`; members below
  unloaded payloads reachable; `Pull.layers` lists every layer consulted
  (hashes filled in Task 9).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pull_worlds.py
import pytest

pxr = pytest.importorskip("pxr")

from jitsd.pull import pull

VARIANT_CTX = """#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Scope "Looks"
    {
        def Material "hero"
        {
        }
        def Material "cheap"
        {
        }
    }
    def Xform "prop" (
        variants = { string lod = "proxy" }
        prepend variantSets = "lod"
    )
    {
        variantSet "lod" = {
            "full" {
                rel material:binding = </root/Looks/hero>
            }
            "proxy" {
                rel material:binding = </root/Looks/cheap>
            }
        }
    }
}
"""


def test_unselected_variant_edges_declared_not_followed(tmp_path):
    f = tmp_path / "v.usda"
    f.write_text(VARIANT_CTX)
    p = pull(str(f), ["prop"], follow=["material:binding"])
    paths = [m.path for m in p.members]
    assert "/root/Looks/cheap" in paths          # selected world followed
    assert "/root/Looks/hero" not in paths       # unselected world NOT pulled
    variant_kinds = [b for b in p.boundary if b.kind.startswith("usd:variant(")]
    assert any(b.kind == "usd:variant(lod=full)" for b in variant_kinds)
    assert any(s == "/root/prop lod=proxy" for s in p.variant_selections)


def test_payload_interior_member(tmp_path):
    (tmp_path / "inner.usda").write_text("""#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Scope "mtl"
    {
        def Material "usd_full"
        {
        }
    }
}
""")
    (tmp_path / "outer.usda").write_text("""#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Xform "asset" (
        payload = @./inner.usda@
    )
    {
    }
}
""")
    p = pull(str(tmp_path / "outer.usda"), ["path:/root/asset/mtl/usd_full"])
    assert [m.path for m in p.members] == ["/root/asset/mtl/usd_full"]
    assert any("payload" in d for d in p.declarations)
    assert any(l[0].endswith("inner.usda") for l in p.layers)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pull_worlds.py -v`
Expected: first test fails on missing boundary/selection records; second on
empty members (path below unloaded payload is invalid on the LoadNone stage).

- [ ] **Step 3: Implement in `jitsd/pull.py`**

Add imports at top: `import os` and
`from deps.walk import ARC, INTERNAL, walk_file`.

Add three helpers:

```python
def _record_variants(prim, p: Pull) -> None:
    vsets = prim.GetVariantSets()
    for name in vsets.GetNames():
        sel = vsets.GetVariantSet(name).GetVariantSelection()
        if sel:
            entry = "%s %s=%s" % (prim.GetPath().pathString, name, sel)
            if entry not in p.variant_selections:
                p.variant_selections.append(entry)


def _unselected_variant_edges(prim, p: Pull, members) -> None:
    """Declare edges authored in variants NOT selected (spec section 4)."""
    from pxr import Sdf
    vsets = prim.GetVariantSets()
    for spec in prim.GetPrimStack():
        for vset in spec.variantSets:
            selected = vsets.GetVariantSet(vset.name).GetVariantSelection()
            for variant in vset.variants:
                if variant.name == selected:
                    continue
                for vspec in _iter_specs(variant.primSpec):
                    for rel in vspec.relationships:
                        for t in _rel_targets(rel):
                            if t not in members:
                                p.boundary.append(PullBoundary(
                                    t, "usd:variant(%s=%s)" % (vset.name, variant.name),
                                    "not in selected world"))


def _iter_specs(spec):
    yield spec
    for child in spec.nameChildren:
        yield from _iter_specs(child)


def _rel_targets(rel):
    items = []
    lo = rel.targetPathList
    for slot in ("explicitItems", "prependedItems", "appendedItems",
                 "addedItems", "orderedItems"):
        items.extend(getattr(lo, slot, ()) or ())
    return [str(t.GetPrimPath()) for t in items]
```

Payload-interior resolution: add a helper called when
`stage.GetPrimAtPath(path)` is invalid for a `path:` seed or a followed
target —

```python
def _below_payload(stage, path, p: Pull) -> Optional[str]:
    """Confirm `path` exists below an unloaded payload by crossing the
    recorded ARC(payload) edge in layer space. Returns the path if the
    interior layer defines the remainder, else None. Spec section 4."""
    from pxr import Sdf
    cur = path
    while cur and cur != "/":
        cur = cur.rsplit("/", 1)[0] or "/"
        prim = stage.GetPrimAtPath(cur)
        if prim:
            break
    if not prim:
        return None
    rest = path[len(cur):]           # e.g. "/mtl/usd_full"
    for spec in prim.GetPrimStack():
        rec = walk_file(spec.layer.realPath or spec.layer.identifier)
        if rec is None:
            continue
        for e in rec.edges:
            if e.kind == ARC and e.name == "payload" and e.src_prim == str(spec.path):
                target = os.path.normpath(os.path.join(
                    os.path.dirname(spec.layer.realPath), e.target))
                inner = Sdf.Layer.FindOrOpen(target)
                if not inner:
                    continue
                root = inner.defaultPrim or ""
                interior = "/%s%s" % (root, rest)
                if inner.GetPrimAtPath(interior):
                    if (target, "") not in p.layers:
                        p.layers.append((target, ""))
                    p.declarations.append(
                        "%s resolved below unloaded payload via %s"
                        % (path, os.path.basename(target)))
                    return path
    return None
```

Wire into `pull()`:
- after seed resolution, for every resolved path where
  `stage.GetPrimAtPath(path)` is invalid, call `_below_payload`; keep the
  member if it returns the path, else append a declaration
  `"seed path %s: not in composed world" % path` and drop it;
- inside the frontier loop, when a member prim is valid call
  `_record_variants(prim, p)` and, after processing its candidates,
  `_unselected_variant_edges(prim, p, members)`;
- at the end, record consulted layers: every distinct layer in members'
  `GetPrimStack()` appended to `p.layers` as `(identifier, "")`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_pull_worlds.py tests/test_pull.py -v`
Expected: all PASS (Task 5 tests must not regress).

- [ ] **Step 5: Commit**

```bash
git add jitsd/pull.py tests/test_pull_worlds.py
git commit -m "pull: declare unselected-variant edges, record selections, cross payloads"
```

---

### Task 7: instancing, omission classes, physics whole-or-declared

Spec §4 (instancing rule), §6 (omission classes, physics rules, fitness).

**Files:**
- Create: `jitsd/registry.py`
- Modify: `jitsd/pull.py`
- Test: `tests/test_pull_soundness.py` (new)

**Interfaces:**
- Produces in `jitsd/registry.py` (consumed by pull, manifest, CLI):

```python
INERT = "inert"
MEANING_CHANGING = "meaning-changing"
OMISSION_CLASSES: Dict[str, str]   # kind/prefix -> class; unlisted -> INERT

def omission_class(kind: str) -> str
```

Built-in table: `physics:body0`, `physics:body1`, any kind starting
`physics:` → MEANING_CHANGING; `skel:` prefix → MEANING_CHANGING;
`collection:` containing `colliders` → MEANING_CHANGING; everything else
INERT.

- Produces in `jitsd/pull.py`: instance widening notes on members; foreign-
  instance targets widened to instance roots; joint/articulation/rigid-body
  rules; `Pull.fitness` = `{"physics_scene_populated": bool,
  "contact_unevaluated": int, "statement": "contact-incomplete by construction"}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pull_soundness.py
import pytest

pxr = pytest.importorskip("pxr")

from jitsd.pull import pull
from jitsd.registry import MEANING_CHANGING, omission_class


def test_omission_classes():
    assert omission_class("physics:body1") == MEANING_CHANGING
    assert omission_class("material:binding") == "inert"
    assert omission_class("skel:skeleton") == MEANING_CHANGING


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_foreign_instance_target_widens_to_instance_root(tmp_path):
    _write(tmp_path, "proto.usda", """#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Scope "geo"
    {
        def Cube "glass"
        {
        }
    }
}
""")
    ctx = _write(tmp_path, "world.usda", """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Xform "a" (
        instanceable = true
        references = @./proto.usda@
    )
    {
    }
    def Xform "b"
    {
        rel custom:uses = </World/a/geo/glass>
    }
}
""")
    p = pull(ctx, ["name:b"], follow=["custom:uses"])
    m = {m.path: m for m in p.members}
    assert "/World/a" in m
    assert "instance" in m["/World/a"].note


def test_joint_whole_or_declared(tmp_path):
    ctx = _write(tmp_path, "sim.usda", """#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Xform "gripper"
    {
        def PhysicsRevoluteJoint "hinge"
        {
            rel physics:body0 = </root/gripper>
            rel physics:body1 = </root/wrist>
        }
    }
    def Xform "wrist"
    {
    }
}
""")
    p = pull(ctx, ["name:gripper"], follow=[])
    paths = [m.path for m in p.members]
    # wrist not followed -> the joint may not ride along silently:
    assert "/root/gripper/hinge" not in paths or "/root/wrist" in paths
    declared = [b for b in p.boundary if b.omission == MEANING_CHANGING]
    assert declared, "joint exclusion must be declared meaning-changing"
    assert p.fitness["statement"] == "contact-incomplete by construction"
    assert p.fitness["contact_unevaluated"] >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pull_soundness.py -v`
Expected: FAIL — no `jitsd.registry`; no widening note; no fitness dict.

- [ ] **Step 3: Implement**

`jitsd/registry.py`:

```python
"""Omission classes (spec section 6): the semantic effect of NOT populating
a relationship target. Extensible by teams; unlisted kinds default to inert,
and the manifest notes when a class was defaulted."""

from __future__ import annotations

from typing import Dict

INERT = "inert"
MEANING_CHANGING = "meaning-changing"

OMISSION_CLASSES: Dict[str, str] = {
    "physics:": MEANING_CHANGING,      # prefix match: any physics rel
    "skel:": MEANING_CHANGING,
    "collection:colliders": MEANING_CHANGING,
}


def omission_class(kind: str) -> str:
    for key, cls in OMISSION_CLASSES.items():
        if kind == key or (key.endswith(":") and kind.startswith(key)):
            return cls
    return INERT
```

In `jitsd/pull.py`:

1. Every `PullBoundary` construction sets
   `omission=omission_class(kind)` (import from `.registry`; the variant
   boundary kind passes the underlying rel kind when known, else the
   variant label).
2. **Member admission goes through one function** — replace direct
   `members[target] = ...` with:

```python
def _admit(stage, path, via_kind, from_member, members, p: Pull) -> Optional[str]:
    """Admit a composed path as a member, widening per the instancing rule.
    Returns the admitted path (may differ from `path`), or None."""
    prim = stage.GetPrimAtPath(path)
    widened = path
    note = ""
    if prim and prim.IsInstanceProxy():
        anc = prim
        while anc and anc.IsInstanceProxy():
            anc = anc.GetParent()
        widened = anc.GetPath().pathString
        note = ("widened to instance root %s: masks populate prototypes whole"
                % widened)
        p.declarations.append("%s %s" % (path, note))
    if widened in members:
        return widened
    members[widened] = PullMember(widened, via_kind, from_member, note)
    return widened
```

   Seeds and closure both use `_admit`; when the admitted path differs, the
   frontier gets the widened path.
3. **Joint rule**, run after closure, before boundary assembly:

```python
def _apply_physics_rules(stage, members, p: Pull) -> None:
    from pxr import Usd
    drop: List[str] = []
    for mpath in list(members):
        prim = stage.GetPrimAtPath(mpath)
        if not prim:
            continue
        for joint in Usd.PrimRange(prim):
            names = joint.GetAuthoredPropertyNames()
            bodies = []
            for rn in ("physics:body0", "physics:body1"):
                if rn in names:
                    rel = joint.GetRelationship(rn)
                    bodies += [t.GetPrimPath().pathString for t in rel.GetTargets()]
            if not bodies:
                continue
            missing = [b for b in bodies
                       if b not in members
                       and not any(b.startswith(m + "/") or m.startswith(b + "/")
                                   for m in members)]
            if missing:
                jp = joint.GetPath().pathString
                drop.append(jp)
                p.boundary.append(PullBoundary(
                    jp, "physics:joint", "excluded: body %s not populated"
                    % ", ".join(missing), omission=MEANING_CHANGING))
    for jp in drop:
        members.pop(jp, None)
        p.declarations.append(
            "joint %s excluded from population (a joint with an absent body "
            "silently becomes a joint to the world frame)" % jp)
```

   Excluded joints are removed from members when directly admitted; when a
   joint rides inside a member's subtree it cannot be carved out by a mask,
   so instead the declaration records it and the boundary entry stands — the
   consumer decides. (Both branches produce the MEANING_CHANGING boundary
   entry; the test accepts either.)
4. **Fitness**, at the end of `pull()`:

```python
    from pxr import Usd
    scene = any(prim.GetTypeName() == "PhysicsScene" for prim in stage.Traverse())
    contact = 0
    for m in p.members:
        prim = stage.GetPrimAtPath(m.path)
        if prim and any(n.startswith("physics:")
                        for n in prim.GetAuthoredPropertyNames()):
            contact += 1
    p.fitness = {
        "physics_scene_populated": scene,
        "contact_unevaluated": contact,
        "statement": "contact-incomplete by construction",
    }
```

   (The test's joint counts: the gripper member authors no `physics:` props
   itself but contains the joint — count a member when any prim in its
   subtree authors `physics:` props; implement the subtree check with
   `Usd.PrimRange(prim)`.)

- [ ] **Step 4: Run all pull tests**

Run: `python -m pytest tests/test_pull_soundness.py tests/test_pull.py tests/test_pull_worlds.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add jitsd/registry.py jitsd/pull.py tests/test_pull_soundness.py
git commit -m "pull: instance widening, omission classes, physics whole-or-declared, fitness"
```

---

### Task 8: registered edge extractors

Spec §5: attribute-encoded references become real edges via a registered,
versioned extractor table; completeness claims scoped to it.

**Files:**
- Modify: `jitsd/registry.py`, `jitsd/pull.py`
- Test: `tests/test_extractors.py` (new)

**Interfaces:**
- Produces in `registry.py` (consumed by pull, manifest, slice rules):

```python
@dataclass(frozen=True)
class Extractor:
    attr: str        # exact attribute name, e.g. "game:spawnRef"
    kind: str        # edge kind the value encodes, e.g. "game:spawns"
    target: str      # "primPath" | "assetPath"

def parse_extractors(text: str) -> List[Extractor]   # jitsd__extractors JSON doc
def emit_extractors_document(items, name) -> str
```

The document format mirrors rule sets: a USDA whose `customLayerData` holds
`string jitsd__extractors = "<json list of {attr,kind,target}>"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_extractors.py
import pytest

pxr = pytest.importorskip("pxr")

from jitsd.pull import pull
from jitsd.registry import Extractor, emit_extractors_document, parse_extractors


def test_document_roundtrip():
    items = [Extractor("game:spawnRef", "game:spawns", "primPath")]
    doc = emit_extractors_document(items, "game.extractors")
    assert parse_extractors(doc) == items


def test_extractor_makes_string_attr_a_followable_edge(tmp_path):
    f = tmp_path / "g.usda"
    f.write_text("""#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Xform "enemy"
    {
        string game:spawnRef = "/root/tables/spawn01"
    }
    def Xform "tables"
    {
        def Xform "spawn01"
        {
        }
    }
}
""")
    ex = [Extractor("game:spawnRef", "game:spawns", "primPath")]
    p = pull(str(f), ["name:enemy"], follow=["game:spawns"], extractors=ex)
    assert "/root/tables/spawn01" in [m.path for m in p.members]
    # without the extractor the edge is invisible AND the scope is declared
    q = pull(str(f), ["name:enemy"], follow=["game:spawns"])
    assert "/root/tables/spawn01" not in [m.path for m in q.members]
    assert any("registered extractors" in d for d in q.declarations)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_extractors.py -v` — FAIL (no Extractor).

- [ ] **Step 3: Implement**

In `registry.py` append:

```python
import json
import re
from dataclasses import dataclass
from typing import List

EXTRACTORS_RE = re.compile(r'string\s+jitsd__extractors\s*=\s*"((?:[^"\\]|\\.)*)"')


@dataclass(frozen=True)
class Extractor:
    attr: str
    kind: str
    target: str = "primPath"


def parse_extractors(text: str) -> List[Extractor]:
    m = EXTRACTORS_RE.search(text)
    if not m:
        raise ValueError("no jitsd__extractors block")
    raw = json.loads(m.group(1).encode().decode("unicode_escape"))
    return [Extractor(**d) for d in raw]


def emit_extractors_document(items, name: str) -> str:
    body = json.dumps([{"attr": e.attr, "kind": e.kind, "target": e.target}
                       for e in items], separators=(",", ":"), sort_keys=True)
    esc = body.replace("\\", "\\\\").replace('"', '\\"')
    return "\n".join([
        "#usda 1.0",
        "# Registered edge extractors: attribute-encoded references made",
        "# into first-class edges. Apply with `jitsd pull --extractors %s`." % name,
        "(",
        "    customLayerData = {",
        '        string jitsd__extractors = "%s"' % esc,
        "    }",
        ")",
        "",
    ])
```

In `pull.py`: `pull(..., extractors=())` parameter; in `_out_edges` gain an
`extractors` argument — after the relationship loop:

```python
    for ex in extractors:
        a = prim.GetAttribute(ex.attr)
        if a and a.HasAuthoredValue() and ex.target == "primPath":
            out.append((ex.kind, str(a.Get())))
```

Always append the scoping declaration once per pull:

```python
    p.declarations.append(
        "strand-free over relationships, arcs, and registered extractors "
        "(%d registered); attribute-encoded references outside them are not visible"
        % len(extractors))
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_extractors.py tests/test_pull.py -v` — PASS.

- [ ] **Step 5: Commit**

```bash
git add jitsd/registry.py jitsd/pull.py tests/test_extractors.py
git commit -m "pull: registered edge extractors; completeness claim scoped to them"
```

---

### Task 9: the manifest — emit, digest, verification pass (`jitsd/manifest.py`)

Spec §8: complete evaluation inputs, layer hashes, digest, mask file,
mandatory verification.

**Files:**
- Create: `jitsd/manifest.py`
- Modify: `jitsd/pull.py` (fill `Pull.layers` hashes and byte accounting)
- Test: `tests/test_manifest.py` (new)

**Interfaces:**
- Consumes: `Pull`, `PullMember`, `PullBoundary` (Tasks 5–8).
- Produces (consumed by Tasks 10, 12):

```python
def layer_hashes(p: Pull) -> None        # fills p.layers (identifier, sha256) + byte accounting
def to_document(p: Pull, usd_version: str = "") -> str   # USDA, jitsd__pull payload incl. digest
def read_document(text: str) -> dict     # the recorded payload
def digest(payload: dict) -> str         # sha256 over canonical JSON minus the digest field
def mask_paths(p: Pull) -> List[str]
def write_mask(p: Pull, path) -> None    # newline-separated file (ARG_MAX)
def verify(document_text: str) -> List[str]   # [] when valid; findings otherwise
```

`verify` re-hashes every recorded layer, opens the context `OpenMasked` with
the member paths, and asserts every member resolves to a populated prim —
the spec's mandatory pass. Payload guidance: masked stages load payloads
within the mask by default, so payload-interior members resolve.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_manifest.py
import pytest

pxr = pytest.importorskip("pxr")

from jitsd.manifest import (digest, layer_hashes, mask_paths, read_document,
                            to_document, verify, write_mask)
from jitsd.pull import pull

CTX = """#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Scope "Looks"
    {
        def Material "glass"
        {
        }
    }
    def Xform "bottle_0001"
    {
        rel material:binding = </root/Looks/glass>
    }
}
"""


@pytest.fixture
def ctx(tmp_path):
    p = tmp_path / "ctx.usda"
    p.write_text(CTX)
    return str(p)


def test_document_records_evaluation_inputs(ctx):
    p = pull(ctx, ["bottle_*"], follow=["material:binding"], depth=3)
    layer_hashes(p)
    doc = to_document(p)
    d = read_document(doc)
    assert d["context"]["hash"]                      # raw file -> content hash
    assert d["asks"] == ["bottle_*"]
    assert d["follow"] == ["material:binding"]
    assert d["depth"] == 3
    assert d["members"][0]["path"] == "/root/Looks/glass"
    assert all(h for _, h in d["layers"])
    assert d["digest"] == digest(d)


def test_verify_clean_manifest(ctx):
    p = pull(ctx, ["bottle_*"], follow=["material:binding"])
    layer_hashes(p)
    assert verify(to_document(p)) == []


def test_verify_catches_vacuous_member(ctx):
    p = pull(ctx, ["bottle_*"], follow=["material:binding"])
    layer_hashes(p)
    from jitsd.pull import PullMember
    p.members.append(PullMember("/root/no_such_prim", "seed"))
    findings = verify(to_document(p))
    assert any("no_such_prim" in f and "does not resolve" in f for f in findings)


def test_verify_catches_layer_drift(ctx, tmp_path):
    p = pull(ctx, ["bottle_*"])
    layer_hashes(p)
    doc = to_document(p)
    with open(ctx, "a") as fh:
        fh.write("\n# drift\n")
    findings = verify(doc)
    assert any("hash" in f for f in findings)


def test_mask_file(ctx, tmp_path):
    p = pull(ctx, ["bottle_*"])
    f = tmp_path / "pull.mask"
    write_mask(p, f)
    assert f.read_text().splitlines() == mask_paths(p)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_manifest.py -v` — FAIL (no module).

- [ ] **Step 3: Implement `jitsd/manifest.py`**

```python
"""The pull manifest (spec section 8): a USDA document whose customLayerData
records the COMPLETE evaluation inputs, so a pull is verifiable by
recompute-and-compare. A manifest is valid against its recorded layer set,
not a context name."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List

from .pull import Pull, PullMember

PULL_RE = re.compile(r'string\s+jitsd__pull\s*=\s*"((?:[^"\\]|\\.)*)"')
MANIFEST_VERSION = 1


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def layer_hashes(p: Pull) -> None:
    seen: Dict[str, str] = dict(p.layers)
    if p.context not in seen:
        seen[p.context] = ""
    total = 0
    out = []
    for ident in sorted(seen):
        try:
            h = _sha256_file(ident)
            total += Path(ident).stat().st_size
        except OSError:
            h = ""
        out.append((ident, h))
    p.layers = out
    p.accounting["layer_bytes"] = total
    p.accounting["asset_paths_not_priced"] = p.accounting.get(
        "asset_paths_not_priced", 0)


def _payload(p: Pull, usd_version: str) -> dict:
    return {
        "manifestVersion": MANIFEST_VERSION,
        "context": {"path": p.context,
                    "hash": dict(p.layers).get(p.context, "")},
        "usdVersion": usd_version,
        "asks": [r.seed.raw for r in p.resolutions],
        "resolutions": [{"ask": r.seed.raw, "mode": r.mode,
                         "matched": r.matched, "complement": r.complement,
                         "note": r.note} for r in p.resolutions],
        "follow": list(p.follow),
        "depth": p.depth,
        "variantSelections": list(p.variant_selections),
        "members": [asdict(m) for m in p.members],
        "boundary": [asdict(b) for b in p.boundary],
        "layers": [list(l) for l in p.layers],
        "accounting": dict(p.accounting),
        "fitness": dict(p.fitness),
        "declarations": list(p.declarations),
        "loadSet": None,      # reserved (spec section 2)
    }


def digest(payload: dict) -> str:
    body = {k: v for k, v in payload.items() if k != "digest"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def to_document(p: Pull, usd_version: str = "") -> str:
    if not usd_version:
        try:
            from pxr import Usd
            usd_version = ".".join(str(x) for x in Usd.GetVersion())
        except Exception:
            usd_version = "unknown"
    payload = _payload(p, usd_version)
    payload["digest"] = digest(payload)
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    esc = body.replace("\\", "\\\\").replace('"', '\\"')
    return "\n".join([
        "#usda 1.0",
        "# A pull manifest. Valid against its recorded layer set; verify",
        "# with `jitsd pull --verify` before trusting the mask.",
        "(",
        "    customLayerData = {",
        '        string jitsd__pull = "%s"' % esc,
        "    }",
        ")",
        "",
    ])


def read_document(text: str) -> dict:
    m = PULL_RE.search(text)
    if not m:
        raise ValueError("no jitsd__pull block")
    return json.loads(m.group(1).encode().decode("unicode_escape"))


def mask_paths(p: Pull) -> List[str]:
    return [m.path for m in p.members]


def write_mask(p: Pull, path) -> None:
    Path(path).write_text("\n".join(mask_paths(p)) + "\n")


def verify(document_text: str) -> List[str]:
    """The mandatory verification pass (spec section 8)."""
    from pxr import Usd
    d = read_document(document_text)
    findings: List[str] = []
    if d.get("digest") != digest(d):
        findings.append("digest mismatch: manifest was edited or truncated")
    for ident, recorded in d["layers"]:
        if not recorded:
            continue
        try:
            now = _sha256_file(ident)
        except OSError:
            findings.append("layer %s: missing" % ident)
            continue
        if now != recorded:
            findings.append("layer %s: hash changed since manifest" % ident)
    paths = [m["path"] for m in d["members"]]
    if paths:
        mask = Usd.StagePopulationMask(paths)
        stage = Usd.Stage.OpenMasked(d["context"]["path"], mask)
        for path in paths:
            if not stage.GetPrimAtPath(path):
                findings.append(
                    "member %s does not resolve to a populated prim "
                    "(closure over-approximated; fatal)" % path)
    return findings
```

Also in `pull.py`: count member asset-path attributes not priced — in the
frontier loop, for each valid member prim, count authored attributes of type
Asset/AssetArray into `p.accounting["asset_paths_not_priced"]` (enumerate
via `prim.GetAttributes()`, `a.GetTypeName() in ("asset", "asset[]")` and
`a.HasAuthoredValue()`).

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_manifest.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add jitsd/manifest.py jitsd/pull.py tests/test_manifest.py
git commit -m "manifest: self-certifying pull document with digest and verification pass"
```

---

### Task 10: CLI — `jitsd pull` and `jitsd who`

Spec §5/§7/§8; must work **without a repo** on a raw USD file (the
tools-stay-usable rule) and with one when `--context` names a ledger asset.

**Files:**
- Modify: `jitsd/cli.py`
- Test: `tests/test_cli_pull.py` (new)

**Interfaces:**
- Consumes: `pull`, `who` (pull.py); `to_document`, `write_mask`,
  `read_document`, `verify`, `layer_hashes` (manifest.py);
  `parse_extractors` (registry.py).
- Produces: `jitsd pull SEED... --context FILE_OR_ASSET [--follow TERMS]
  [--depth N] [--rules NAME[@REF]] [--extractors FILE] [-o MANIFEST]
  [--mask-out FILE] [--verify MANIFEST]` and
  `jitsd who SEED... --context FILE_OR_ASSET [--kinds K,K]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_pull.py
import pytest

pxr = pytest.importorskip("pxr")

from jitsd.cli import main

CTX = """#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Scope "Looks"
    {
        def Material "glass"
        {
        }
    }
    def Xform "bottle_0001"
    {
        rel material:binding = </root/Looks/glass>
    }
}
"""


def test_pull_raw_file_emits_manifest_and_mask(tmp_path, capsys):
    ctx = tmp_path / "ctx.usda"
    ctx.write_text(CTX)
    out = tmp_path / "pull.usda"
    mask = tmp_path / "pull.mask"
    rc = main(["pull", "bottle_*", "--context", str(ctx),
               "--follow", "material:binding",
               "-o", str(out), "--mask-out", str(mask)])
    assert rc == 0
    text = capsys.readouterr().out
    assert "members (2)" in text
    assert "/root/Looks/glass" in mask.read_text().splitlines()
    from jitsd.manifest import read_document
    assert read_document(out.read_text())["follow"] == ["material:binding"]


def test_pull_verify_roundtrip(tmp_path, capsys):
    ctx = tmp_path / "ctx.usda"
    ctx.write_text(CTX)
    out = tmp_path / "pull.usda"
    assert main(["pull", "bottle_*", "--context", str(ctx), "-o", str(out)]) == 0
    assert main(["pull", "--verify", str(out)]) == 0
    ctx.write_text(CTX + "\n# drift\n")
    assert main(["pull", "--verify", str(out)]) == 1


def test_who_reports_chain(tmp_path, capsys):
    ctx = tmp_path / "ctx.usda"
    ctx.write_text(CTX)
    rc = main(["who", "name:glass", "--context", str(ctx)])
    assert rc == 0
    assert "material:binding" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli_pull.py -v`
Expected: FAIL — argparse: invalid choice 'pull'.
(Confirm `jitsd/cli.py` exposes `main(argv)`; it does — `__main__.py` calls it.)

- [ ] **Step 3: Implement in `jitsd/cli.py`**

Add command functions (after `cmd_select`):

```python
def _context_file(raw: str) -> str:
    """A raw USD file path, or a ledger asset name resolved via the repo."""
    if os.path.exists(raw):
        return raw
    repo = Repo.find()
    rev = repo.ledger.resolve_ref(raw, "approved")
    import tempfile
    out = Path(tempfile.mkdtemp(prefix="jitsd-ctx-")) / ("%s.usda" % raw)
    repo.checkout(raw, rev, out)
    return str(out)


def cmd_pull(args) -> int:
    from . import manifest as _manifest
    from . import pull as _pull
    from .registry import parse_extractors

    if args.verify:
        findings = _manifest.verify(Path(args.verify).read_text())
        for f in findings:
            print("  ! %s" % f)
        print("verify: %s" % ("ok" if not findings else "%d findings" % len(findings)))
        return 0 if not findings else 1

    if not args.context:
        print("pull: --context FILE_OR_ASSET is required", file=sys.stderr)
        return 1
    extractors = []
    if args.extractors:
        extractors = parse_extractors(Path(args.extractors).read_text())
    ctx = _context_file(args.context)
    p = _pull.pull(ctx, args.seeds, follow=args.follow, depth=args.depth,
                   extractors=extractors)
    _manifest.layer_hashes(p)

    for r in p.resolutions:
        line = "seed %s -> %d (%s" % (r.seed.raw, r.matched, r.mode)
        if r.complement:
            line += ", %d do not author the key" % r.complement
        line += ")"
        if r.note:
            line += "  %s" % r.note
        print(line)
    print("members (%d):" % len(p.members))
    for m in p.members:
        via = "seed" if m.via_kind == "seed" else "%s <- %s" % (m.via_kind, m.from_member)
        print("  %-44s %s" % (m.path, via))
    if p.boundary:
        print("boundary (%d):" % len(p.boundary))
        for b in p.boundary:
            print("  %-44s %-24s %s [%s]" % (b.target, b.kind, b.reason, b.omission))
    for d in p.declarations:
        print("  ~ %s" % d)
    print("fitness: %s" % p.fitness.get("statement", ""))

    doc = _manifest.to_document(p)
    findings = _manifest.verify(doc)
    for f in findings:
        print("  ! %s" % f, file=sys.stderr)
    if args.out:
        Path(args.out).write_text(doc)
        print("manifest: %s" % args.out)
    if args.mask_out:
        _manifest.write_mask(p, args.mask_out)
        print('mask: %s  (usdrecord --mask "$(cat %s | tr \'\\n\' \',\')" ...)'
              % (args.mask_out, args.mask_out))
    return 0 if not findings else 1


def cmd_who(args) -> int:
    from . import pull as _pull
    ctx = _context_file(args.context)
    kinds = args.kinds.split(",") if args.kinds else None
    for src, kind, member in _pull.who(ctx, args.seeds, kinds=kinds):
        print("  %-44s %-24s -> %s" % (src, kind, member))
    return 0
```

Parser wiring in `build_parser()` (before the final return):

```python
    s = sub.add_parser("pull", help="prim-level pull: seeds -> manifest + mask")
    s.add_argument("seeds", nargs="*",
                   help="glob, name:, id:, id:occ:, role:, offers:, requires:, "
                        "where:attr=value, near:SEED,R, within:6-floats, path:")
    s.add_argument("--context", default=None, metavar="FILE_OR_ASSET")
    s.add_argument("--follow", default=None, metavar="TERMS",
                   help="direction-qualified kinds: Mount, up:electrical:feeds*8")
    s.add_argument("--depth", type=int, default=4)
    s.add_argument("--extractors", default=None, metavar="FILE",
                   help="a jitsd__extractors document")
    s.add_argument("-o", "--out", default=None, help="write the manifest here")
    s.add_argument("--mask-out", default=None, help="write member paths, one per line")
    s.add_argument("--verify", default=None, metavar="MANIFEST",
                   help="verify an existing manifest instead of pulling")
    s.set_defaults(fn=cmd_pull)

    s = sub.add_parser("who", help="what depends on this prim (incoming edges)")
    s.add_argument("seeds", nargs="+")
    s.add_argument("--context", required=True, metavar="FILE_OR_ASSET")
    s.add_argument("--kinds", default=None)
    s.set_defaults(fn=cmd_who)
```

Note `--follow` is passed as a comma string; `parse_follow` accepts it.
`cmd_pull`/`cmd_who` must not call `Repo.find()` unless the context is not a
file — raw-file pulls run with no repo (the rung-0 rule).

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_cli_pull.py -v` — all PASS.
Also: `python -m pytest -q` — full suite green.

- [ ] **Step 5: Commit**

```bash
git add jitsd/cli.py tests/test_cli_pull.py
git commit -m "cli: jitsd pull and jitsd who, repo-optional"
```

---

### Task 11: carrier emission in extraction

Spec §6: `jitsd:offer:carrier` authored in the interface layer at composed
scope, by a stated recorded rule; advisory only — refused for offers with
physical meaning.

**Files:**
- Modify: `jitsd/extract.py` (`provider_interface`)
- Test: extend `tests/test_extract.py`

**Interfaces:**
- Consumes: `Extraction` (has `.placements`: list of `Placement(name, group,
  translate)` — confirm exact field names by reading
  `jitsd/extract.py:38-45` before editing).
- Produces: `provider_interface(..., carrier_rule=None)`; when
  `carrier_rule="group-furniture"`, each offer over additionally authors:

```
        prepend rel jitsd:offer:carrier = [</lab_workbench01/shelf01/furniture_shelving01_0001>, ...]
        uniform token jitsd:offer:carrierRule = "group-furniture: furniture_* placements of the offer's group"
```

  Carrier targets = placements in the same group whose name starts with
  `furniture_`. Offers whose role/asset name itself starts with `furniture_`
  get no carrier (a shelf is not its own carrier). If a future caller passes
  a nonzero `load_limit` for an offer, `provider_interface` raises
  `ValueError("carrier derivation refused for offers with physical meaning")`
  — v1 has no load limits, so the guard is one `if`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_extract.py`,
  following that file's existing fixture pattern — read it first and reuse
  its assembly fixture builder):

```python
def test_carrier_rule_emits_advisory_carriers(tmp_path):
    # reuse the existing two-placement assembly fixture from this file,
    # extended with one furniture placement in the same group:
    ex = _make_extraction(tmp_path, placements=[
        ("chemistry_bottle01_0001", "shelf01", (1.0, 0.0, 0.0)),
        ("furniture_shelving01_0001", "shelf01", (0.0, 0.0, 0.0)),
    ])
    text = provider_interface(ex, carrier_rule="group-furniture")
    assert "jitsd:offer:carrier" in text
    assert "furniture_shelving01_0001" in text
    assert 'carrierRule = "group-furniture' in text
    # the furniture offer itself carries no carrier
    furniture_block = text[text.index("furniture_shelving01_0001"):]
    assert "jitsd:offer:carrier" not in furniture_block.split("def ", 2)[-1]


def test_no_rule_no_carrier(tmp_path):
    ex = _make_extraction(tmp_path, placements=[
        ("chemistry_bottle01_0001", "shelf01", (1.0, 0.0, 0.0)),
    ])
    assert "jitsd:offer:carrier" not in provider_interface(ex)
```

(`_make_extraction` is whatever helper the file already uses to build an
`Extraction` — if it builds via `read_assembly` on a written fixture, write
the two placements into that fixture instead; keep the test's assertions.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_extract.py -v -k carrier` — FAIL
(`provider_interface() got an unexpected keyword argument`).

- [ ] **Step 3: Implement**

In `provider_interface` (read the function first; it iterates placements
emitting one offer block per placement): add parameter
`carrier_rule: Optional[str] = None`. Before the per-placement loop build:

```python
    furniture_by_group: Dict[str, List[str]] = {}
    if carrier_rule == "group-furniture":
        for pl in ex.placements:
            if pl.name.startswith("furniture_"):
                furniture_by_group.setdefault(pl.group, []).append(pl.name)
```

Inside each offer block, when the placement's name does not start with
`furniture_` and its group has furniture:

```python
            carriers = furniture_by_group.get(pl.group, [])
            if carriers and not pl.name.startswith("furniture_"):
                targets = ", ".join(
                    "</%s/%s/%s>" % (ex.provider, pl.group, c) for c in sorted(carriers))
                lines.append("        prepend rel jitsd:offer:carrier = [%s]" % targets)
                lines.append('        uniform token jitsd:offer:carrierRule = '
                             '"%s: furniture_* placements of the offer\'s group"'
                             % carrier_rule)
```

(Adapt the exact emission style — string building vs list-append — to how
the function already writes offer blocks; the paths must match the prim
paths the interface layer authors for placements.)

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_extract.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add jitsd/extract.py tests/test_extract.py
git commit -m "extract: advisory carrier rel by stated group-furniture rule"
```

---

### Task 12: prim selections in slices, with the authority rule

Spec §9: ask grammar as slice-seed syntax scoped by context; two-tier
members; ask authoritative at other coordinates; pricing from the manifest.

**Files:**
- Modify: `jitsd/slice.py`, `jitsd/cli.py` (receipt only — no new flags)
- Test: `tests/test_slice_prim.py` (new)

**Interfaces:**
- Consumes: `pull`, `Pull` (pull.py); `layer_hashes`, `digest`, `_payload`
  via `to_document`/`read_document` (manifest.py).
- Produces in `jitsd/slice.py`:

```python
@dataclass
class Selection:
    context: str          # ledger asset name
    rev: str              # context revision pinned at resolve time
    ask: str              # the raw ask, authoritative at other coordinates
    paths: List[str]      # cached resolution at (context, rev)
    layer_bytes: int      # priced from the manifest accounting

PRIM_SEED_RE  # matches "CONTEXT:ask" where ask starts with a known plane prefix
SliceResult.selections: List[Selection]
```

A seed of the form `<asset>:<ask>` where `<ask>` starts with one of
`name:`, `id:`, `where:`, `near:`, `within:`, `path:`, `role:`, `offers:`,
`requires:` is a prim seed. Resolution: check out the context asset's source
at the slice's pinned revision (`repo.ledger` has the revision; the asset's
`source` field gives the original file — the same mechanism
`_reference_edges` uses via `_AssetInfo.source`), run `pull`, store a
`Selection`. The receipt prints selections with path counts and layer bytes.
**Authority rule**: `resolve_slice` always re-runs the ask; when a spec
loaded via `--from` carries recorded selections at the SAME context rev, the
recorded paths must equal the replay (diagnostic + error on mismatch —
checkable invariant); at a different rev the replay wins and the diff is a
diagnostic (`"selection drift: +N -M vs recorded"`), never an error.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_slice_prim.py
import pytest

pxr = pytest.importorskip("pxr")

from jitsd.slice import Selection, is_prim_seed, split_prim_seed


def test_prim_seed_detection():
    assert is_prim_seed("lab_workbench01:where:finish=translucent")
    assert is_prim_seed("bench:path:/root/x")
    assert not is_prim_seed("chemistry_bottle01")          # plain asset seed
    assert not is_prim_seed("provides:Mount@1")            # asset-level predicate
    assert split_prim_seed("bench:where:finish=translucent") == (
        "bench", "where:finish=translucent")


def test_selection_resolves_and_prices(tmp_path):
    # end-to-end against a real repo: ingest a tiny context asset whose
    # source file has two placements, prim-seed one of them.
    from jitsd.ledger import Repo
    src = tmp_path / "bench.usda"
    src.write_text("""#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Xform "bottle_0001"
    {
        uniform token finish = "translucent"
    }
    def Xform "bottle_0002"
    {
    }
}
""")
    repo = Repo.init(tmp_path / "repo")
    repo.save("bench", src, "t", "ingest")
    repo.ledger.promote("bench", "approved",
                        repo.ledger.resolve_ref("bench", "wip"), "t")

    from jitsd.slice import SliceSpec, resolve_slice
    spec = SliceSpec(seeds=["bench:where:finish=translucent"])
    result = resolve_slice(repo, spec)
    assert len(result.selections) == 1
    sel = result.selections[0]
    assert sel.context == "bench"
    assert sel.paths == ["/root/bottle_0001"]
    assert sel.layer_bytes > 0
    assert sel.ask == "where:finish=translucent"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_slice_prim.py -v` — FAIL
(`ImportError: cannot import name 'is_prim_seed'`).
(If `Repo.init`/`promote` signatures differ, read `jitsd/ledger.py:352` and
`tests/test_slice.py` first and match how the existing slice tests build a
repo — reuse their fixture helper verbatim.)

- [ ] **Step 3: Implement in `jitsd/slice.py`**

```python
_PRIM_PLANES = ("name:", "id:", "where:", "near:", "within:", "path:",
                "role:", "offers:", "requires:")


def is_prim_seed(seed: str) -> bool:
    ctx, sep, rest = seed.partition(":")
    if not sep or not ctx:
        return False
    return rest.startswith(_PRIM_PLANES) or (
        ":" not in ctx and any(rest.startswith(p) for p in _PRIM_PLANES))


def split_prim_seed(seed: str) -> Tuple[str, str]:
    ctx, _, rest = seed.partition(":")
    return ctx, rest


@dataclass
class Selection:
    context: str
    rev: str
    ask: str
    paths: List[str] = field(default_factory=list)
    layer_bytes: int = 0
```

Add `selections: List[Selection] = field(default_factory=list)` to
`SliceResult`. In `resolve_slice`, partition seeds first:

```python
    prim_seeds = [s for s in spec.seeds if is_prim_seed(s)]
    asset_seeds = [s for s in spec.seeds if not is_prim_seed(s)]
```

(asset seeds flow through the existing path unchanged). After the universe
loads, resolve each prim seed:

```python
    selections: List[Selection] = []
    for seed in prim_seeds:
        ctx_name, ask = split_prim_seed(seed)
        if ctx_name not in universe:
            diagnostics.append("prim seed %r: no context asset %r at this "
                               "coordinate" % (seed, ctx_name))
            errors += 1
            continue
        info = universe[ctx_name]
        if not info.source:
            diagnostics.append("prim seed %r: context %r has no source file"
                               % (seed, ctx_name))
            errors += 1
            continue
        from . import manifest as _manifest
        from .pull import pull as _pull_fn
        p = _pull_fn(info.source, [ask], follow=spec.follow or None,
                     depth=spec.depth)
        _manifest.layer_hashes(p)
        sel = Selection(context=ctx_name, rev=info.rev, ask=ask,
                        paths=[m.path for m in p.members],
                        layer_bytes=int(p.accounting.get("layer_bytes", 0)))
        selections.append(sel)
        if not sel.paths:
            diagnostics.append("prim seed %r matched nothing" % seed)
        # the context asset joins membership so closure/impact see it
        members.setdefault(ctx_name, member_from(
            ctx_name, Provenance("seed", seed)))
```

Authority rule against a spec loaded from a document: store selections in
the emitted document (add to `SliceSpec` an optional
`selections: List[Dict]` field serialized like pins) and on resolve compare:

```python
    for rec in (spec.selections or []):
        cur = next((s for s in selections
                    if s.context == rec["context"] and s.ask == rec["ask"]), None)
        if cur is None:
            continue
        if rec.get("rev") == cur.rev and rec.get("paths") != cur.paths:
            diagnostics.append(
                "selection %s:%s: recorded paths differ from replay at the "
                "same rev %s -- invariant violated" % (cur.context, cur.ask, cur.rev))
            errors += 1
        elif rec.get("rev") != cur.rev:
            old = set(rec.get("paths") or [])
            new = set(cur.paths)
            diagnostics.append(
                "selection drift %s:%s: +%d -%d vs recorded at %s (ask is "
                "authoritative)" % (cur.context, cur.ask,
                                    len(new - old), len(old - new), rec.get("rev")))
    result_selections = selections
```

Return them on the result; extend `receipt()`:

```python
    if result.selections:
        lines.append("")
        lines.append("selections (%d):" % len(result.selections))
        for s in result.selections:
            lines.append("  %s@%s : %s -> %d prims, %s"
                         % (s.context, s.rev, s.ask, len(s.paths),
                            _human(s.layer_bytes)))
```

And serialize: `SliceSpec.selections: Optional[List[Dict]] = None` (a plain
list of dicts so `to_json` works); `emit_query_document` records
`[{"context": s.context, "rev": s.rev, "ask": s.ask, "paths": s.paths}]`
from the result into the spec before emitting (in `cmd_select`, set
`spec.selections = [...]` when `result.selections` is non-empty, before the
`--out` write).

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_slice_prim.py tests/test_slice.py tests/test_slice_rules.py tests/test_slice_references.py -v`
Expected: all PASS — existing slice behavior unchanged for asset seeds.

- [ ] **Step 5: Commit**

```bash
git add jitsd/slice.py jitsd/cli.py tests/test_slice_prim.py
git commit -m "slice: prim selections with pinned revs, pricing, and the authority rule"
```

---

### Task 13: ALab acceptance test and docs truth pass

Spec §11: the three asks reproduce the spike; docs reflect what now exists.

**Files:**
- Create: `tests/test_alab_pull.py` (gated on an env var)
- Modify: `README.md` (What-exists table row), `IMPLEMENTATION.md`,
  `examples/alab/README.md` (a "prim-level pull" section with the real
  commands and real output — run them, paste actual output, never invent)

**Interfaces:**
- Consumes: everything above. The ALab tree location comes from
  `JITSD_ALAB` (path to the `ALab` directory); tests skip without it.

- [ ] **Step 1: Write the acceptance test**

```python
# tests/test_alab_pull.py
import os

import pytest

pxr = pytest.importorskip("pxr")

ALAB = os.environ.get("JITSD_ALAB")
pytestmark = pytest.mark.skipif(
    not ALAB, reason="set JITSD_ALAB to the ALab directory to run acceptance")

WORKBENCH = "entity/lab_workbench01/lab_workbench01.usda"

TRANSLUCENT = ["chemistry_beaker01", "chemistry_beaker02", "chemistry_beaker03",
               "chemistry_bottle01", "decor_bottle_soda01", "decor_glass01",
               "stationary_set_square01", "stationary_set_square02"]


def _ctx():
    return os.path.join(ALAB, WORKBENCH)


def test_ask_one_bottle():
    from jitsd.pull import pull
    p = pull(_ctx(), ["path:/root/shelf01/chemistry_bottle01_0004"])
    assert [m.path for m in p.members] == ["/root/shelf01/chemistry_bottle01_0004"]


def test_ask_translucent_matches_spike_mask():
    from jitsd.pull import pull
    p = pull(_ctx(), ["where:finish=translucent"])
    paths = [m.path for m in p.members]
    # the spike's mask: 26 placements under /root, every one a placement of
    # one of the 8 translucent assets, no common ancestor below /root
    assert len(paths) == 26
    assert all(any(part.startswith(t) for t in TRANSLUCENT
                   for part in p_.split("/")) for p_ in paths)


def test_ask_mount_with_carrier():
    from jitsd.pull import pull
    p = pull(_ctx(), ["path:/root/shelf01/chemistry_bottle01_0004"],
             follow=["Mount"])
    paths = [m.path for m in p.members]
    assert "/root/shelf01/chemistry_bottle01_0004" in paths
    carriers = [x for x in paths if "furniture_" in x]
    assert carriers, "carrier rule must pull the shelf01 furniture"
    assert all("/shelf01/" in c or c.endswith("shelf01") for c in carriers)


def test_manifest_verifies():
    from jitsd.manifest import layer_hashes, to_document, verify
    from jitsd.pull import pull
    p = pull(_ctx(), ["where:finish=translucent"])
    layer_hashes(p)
    assert verify(to_document(p)) == []
```

Note the first ask uses `path:` deliberately: the acceptance criterion's
`'chemistry_bottle01_0004'` bare form also works (lexical plane) — add one
assertion to `test_ask_one_bottle`:

```python
    q = pull(_ctx(), ["chemistry_bottle01_0004"])
    assert [m.path for m in q.members] == [m.path for m in p.members]
```

`test_ask_mount_with_carrier` requires the ALab interfaces to carry
carriers: before running, regenerate the workbench interface with
`provider_interface(..., carrier_rule="group-furniture")` via a small
setup fixture in this file that calls `jitsd.extract.read_assembly` +
`write_interfaces` against the ALab tree IF
`jitsd:offer:carrier` is absent (idempotent, mirrors `examples/alab/poc.py`).
Where the `where:finish` seed resolves from: the interface sublayers author
`jitsd:bind:finish` on the `Represents` offer overs — `_authored` checks
`jitsd:bind:finish`, so the composed workbench stage answers it. If the
local ALab tree lacks the Techvar-derived interfaces, the test must FAIL
with the resolution declaration in the message, not silently pass.

- [ ] **Step 2: Run against the local ALab tree**

Run: `JITSD_ALAB=<scratchpad>/real/alab/ALab-2.3.0/ALab python -m pytest tests/test_alab_pull.py -v`
Expected: all four PASS. Iterate here until they do — this is the
acceptance gate; discrepancies are bugs in Tasks 4–11, not in the test.

- [ ] **Step 3: Update the docs with real output**

Run the CLI forms and paste their actual output into
`examples/alab/README.md` under a new "## Pulling at prim level" section:

```bash
jitsd pull 'where:finish=translucent' --context $JITSD_ALAB/entity/lab_workbench01/lab_workbench01.usda --mask-out /tmp/pull.mask
/usr/bin/usdrecord -w 1280 --mask "$(tr '\n' ',' < /tmp/pull.mask)" $JITSD_ALAB/entity/lab_workbench01/lab_workbench01.usda /tmp/pull.png
```

Add one row to `README.md`'s What-exists table ("prim-level pull — seeds by
identity/attribute/bounds, directional follow, self-certifying manifest,
`jitsd pull` / `jitsd who`") and a matching paragraph in
`IMPLEMENTATION.md`. Every number pasted must come from a real run.

- [ ] **Step 4: Full suite + bare-environment check**

Run: `python -m pytest -q` (usd env) and, in the bare venv,
`python -m pytest -q` — pxr-gated files all skip, nothing errors.

- [ ] **Step 5: Commit**

```bash
git add tests/test_alab_pull.py README.md IMPLEMENTATION.md examples/alab/README.md
git commit -m "acceptance: three spike asks reproduced from one-line pulls on ALab"
```

---

## Self-Review (performed while writing)

- **Spec coverage:** §4 (Tasks 1, 5, 6, 7) · §5 (3, 4, 8) · §6 (7, 11) · §7
  (2, 5) · §8 (9, 10) · §9 (12) · §10–§11 (13, plus per-task tests).
  Deferred spec items (§2's out-of-scope list) intentionally have no tasks:
  federation, effectivity, conjunction, relocates (detected only — note:
  relocates *detection* is folded into Task 6's declarations if
  `layer.relocates` is non-empty: add one line
  `p.declarations.append("relocates present: unsupported in v1")` when any
  consulted layer has relocates), load-set, semantic tier.
- **Placeholder scan:** none; every step carries code or an exact command.
- **Type consistency:** `Pull`/`PullMember`/`PullBoundary` defined in Task 5
  and only extended (never renamed) afterward; `Seed`/`ResolvedSeed` from
  Tasks 3–4 are the only ask types; `FollowTerm` from Task 2 everywhere.
- **Known judgment calls recorded for executors:** composed-relationships-
  as-authority (header) means list-op deletes and Pcp elision are exercised
  through USD itself for populated prims; Task 1's recorded deletes matter
  for the payload-interior walk only. If a task's exact USD API call errs
  (e.g. `GetVersion` tuple shape), fix the call, keep the interface.

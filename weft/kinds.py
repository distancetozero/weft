"""The `weft__kinds` loader -- declare a relationship kind as data
(docs/superpowers/specs/2026-09-04-weft-kinds-loader.md).

One declaration produces one `relkinds.RelationshipKind`, collapsing the four
scattered touchpoints of adding a relationship (authored attr, extractor,
omission class, lens registration) into fields of a single unit. Authored as
`customLayerData weft__kinds` on a weft sidecar layer -- the same mechanism
`weft__extractors` already uses (registry.EXTRACTORS_RE), so this is
evolutionary, not new plumbing.

Population modes:
  read   -- the edge is an authored attribute; v1 ships this fully: the loaded
            kind yields a `registry.Extractor` (so `pull` follows it),
            contributes its omission class (so a cut edge is classified), and
            carries display/facet (so the thread viewer gains the lens).
  derive/mine -- code. The declaration names a registered built-in subclass
            (`{"builtin": "<name>"}`); v1 ships the named-subclass dispatch,
            not any derivers/miners themselves.

Explicit loading (`parse_kinds` -> `load_kinds`, the `--kinds` CLI path)
raises loudly on any misdeclaration -- no silent misload. `discover` is the
viewer-side path and is defensive instead: absence or a malformed block
degrades to the built-in registry, matching threadgraph's guard-everything
contract. `parse_kinds` is pxr-free, like `registry.parse_extractors`.
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional, Tuple

from . import registry as _registry
from .registry import INERT, MEANING_CHANGING, Extractor
from .relkinds import LENS_ORDER, REGISTRY, Context, RelationshipKind

# Both usda string spellings of the block: the escaped one-line form
# (mirroring EXTRACTORS_RE) and the triple-quoted form the spec example uses.
KINDS_RE = re.compile(r'string\s+weft__kinds\s*=\s*"((?:[^"\\]|\\.)*)"')
KINDS_TRIPLE_RE = re.compile(r'string\s+weft__kinds\s*=\s*"""(.*?)"""', re.S)

_MODES = ("read", "derive", "mine")
_FIELDS = {"kind", "label", "color", "structure", "omission", "population",
           "contract"}
_DEFAULT_COLOR = "#9aa0a8"

# Named built-in subclasses a `derive`/`mine` declaration may reference
# (spec open question 3: `{"builtin": "<name>"}`). Empty in v1 -- the
# dispatch mechanism ships now, actual derivers/miners come with the
# interrogation engine. Values are RelationshipKind subclasses.
BUILTIN_DERIVERS: Dict[str, type] = {}
BUILTIN_MINERS: Dict[str, type] = {}


def parse_kinds(text: str) -> List[dict]:
    """Read the `weft__kinds` customLayerData string out of layer text ->
    list of declaration dicts. Pure regex + json (pxr-free), mirroring
    registry.parse_extractors. Raises ValueError when the block is absent
    or malformed."""
    m = KINDS_TRIPLE_RE.search(text)
    if m:
        raw = m.group(1)
    else:
        m = KINDS_RE.search(text)
        if not m:
            raise ValueError("no weft__kinds block")
        raw = m.group(1).encode().decode("unicode_escape")
    try:
        decls = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError("weft__kinds is not valid JSON: %s" % e)
    if not isinstance(decls, list) or not all(isinstance(d, dict) for d in decls):
        raise ValueError("weft__kinds must be a JSON array of objects")
    return decls


def emit_kinds_document(decls: List[dict], name: str) -> str:
    """A weft__kinds sidecar layer as usda text (the escaped one-line form,
    like registry.emit_extractors_document). Round-trips through
    parse_kinds."""
    body = json.dumps(decls, separators=(",", ":"), sort_keys=True)
    esc = body.replace("\\", "\\\\").replace('"', '\\"')
    return "\n".join([
        "#usda 1.0",
        "# Declared relationship kinds: one block per kind (extractor,",
        "# omission, lens display). Apply with `weft pull --kinds %s`." % name,
        "(",
        "    customLayerData = {",
        '        string weft__kinds = "%s"' % esc,
        "    }",
        ")",
        "",
    ])


# -- the loaded kind ---------------------------------------------------------


class DeclaredReadKind(RelationshipKind):
    """A `read`-mode declaration: the edge is an authored attribute, read as a
    first-class edge. Carries the `registry.Extractor` pull follows (identical
    to a weft__extractors entry) plus the declared omission class; contributes
    graph edges via `populate` (stage-global: the authored attr can sit on any
    prim, not only the root -> group -> placement convention)."""

    def __init__(self, type_id: str, attr: str, target: str, facet: bool,
                 display: Dict[str, str], omission: str,
                 contract: Optional[str] = None) -> None:
        self.type_id = type_id
        self.facet = facet
        self.display = display
        self.omission = omission
        self.contract = contract
        self.extractor = Extractor(attr=attr, kind=type_id, target=target)

    @staticmethod
    def _node_type(name: str) -> str:
        return "furniture" if name.startswith("furniture_") else "prop"

    def populate(self, stage, ctx: Context) -> None:
        if stage is None:
            return
        attr_name = self.extractor.attr
        for prim in stage.Traverse(ctx.predicate):
            try:
                a = prim.GetAttribute(attr_name)
                if not (a and a.HasAuthoredValue()):
                    continue
                value = str(a.Get())
                pid = prim.GetPath().pathString
                ctx.builder.add(pid, prim.GetName(),
                                self._node_type(prim.GetName()))
                if self.facet:
                    # A concept node many prims may point at (like finish:).
                    cid = ctx.builder.add("%s:%s" % (self.type_id, value),
                                          value, self.type_id)
                    ctx.builder.add_edge(pid, cid, self.type_id)
                else:
                    target = stage.GetPrimAtPath(value)
                    if not (target and target.IsValid()):
                        continue
                    ctx.builder.add(value, target.GetName(),
                                    self._node_type(target.GetName()))
                    ctx.builder.add_edge(pid, value, self.type_id)
            except Exception:
                continue


def _load_one(decl: dict) -> RelationshipKind:
    unknown = set(decl) - _FIELDS
    if unknown:
        raise ValueError("weft__kinds: unknown field(s) %s in %r"
                         % (", ".join(sorted(unknown)), decl.get("kind")))
    kind = decl.get("kind")
    if not kind or not isinstance(kind, str):
        raise ValueError("weft__kinds: every declaration needs a string 'kind'")

    structure = decl.get("structure", "edge")
    if structure not in ("edge", "facet"):
        raise ValueError("weft__kinds %r: structure must be 'edge' or 'facet', "
                         "got %r" % (kind, structure))
    omission = decl.get("omission", INERT)
    if omission not in (INERT, MEANING_CHANGING):
        raise ValueError("weft__kinds %r: omission must be %r or %r, got %r"
                         % (kind, MEANING_CHANGING, INERT, omission))
    display = {"label": decl.get("label", kind),
               "color": decl.get("color", _DEFAULT_COLOR)}

    population = decl.get("population")
    if not isinstance(population, dict) or len(population) != 1:
        raise ValueError("weft__kinds %r: population must be exactly one of "
                         "%s" % (kind, "/".join(_MODES)))
    mode, config = next(iter(population.items()))
    if mode not in _MODES:
        raise ValueError("weft__kinds %r: unknown population mode %r "
                         "(expected %s)" % (kind, mode, "/".join(_MODES)))
    if not isinstance(config, dict):
        raise ValueError("weft__kinds %r: population.%s must be an object"
                         % (kind, mode))

    if mode == "read":
        attr = config.get("attr")
        if not attr or not isinstance(attr, str):
            raise ValueError("weft__kinds %r: read mode needs an 'attr'" % kind)
        target = config.get("target", "primPath")
        if target != "primPath":
            raise ValueError("weft__kinds %r: read target must be 'primPath', "
                             "got %r" % (kind, target))
        return DeclaredReadKind(kind, attr, target, structure == "facet",
                                display, omission, decl.get("contract"))

    # derive/mine: data references code -- the declaration names a
    # registered built-in subclass; it contains no logic itself.
    table = BUILTIN_DERIVERS if mode == "derive" else BUILTIN_MINERS
    name = config.get("builtin")
    if not name:
        raise ValueError("weft__kinds %r: %s mode needs a 'builtin' naming a "
                         "registered subclass" % (kind, mode))
    cls = table.get(name)
    if cls is None:
        raise ValueError(
            "weft__kinds %r: no built-in %s named %r (registered: %s)"
            % (kind, "deriver" if mode == "derive" else "miner", name,
               ", ".join(sorted(table)) or "none"))
    k = cls()
    k.type_id = kind
    k.facet = structure == "facet"
    k.display = display
    k.omission = omission
    k.extractor = None
    k.contract = decl.get("contract")
    return k


def load_kinds(decls: List[dict]) -> List[RelationshipKind]:
    """Declaration dicts -> RelationshipKind objects. Validates loudly: an
    unknown population mode, a duplicate `kind`, or a `kind` shadowing a
    built-in raises ValueError (spec open question 2: collision is an error;
    force a distinct id). As part of loading, each kind's omission class is
    registered with `registry` so `omission_class` classifies its cut edges
    -- that registration happens only after ALL declarations validate."""
    builtin_ids = {k.type_id for k in REGISTRY} | set(LENS_ORDER)
    out: List[RelationshipKind] = []
    seen: set = set()
    for decl in decls:
        k = _load_one(decl)
        if k.type_id in seen:
            raise ValueError("weft__kinds: duplicate kind %r" % k.type_id)
        if k.type_id in builtin_ids:
            raise ValueError("weft__kinds: kind %r shadows a built-in kind; "
                             "declare a distinct id" % k.type_id)
        seen.add(k.type_id)
        out.append(k)
    for k in out:
        _registry.DECLARED_OMISSIONS[k.type_id] = k.omission
    return out


# -- discovery (the viewer-side path: defensive, cached, never raises) -------

# (identifier, layer mtime, sidecar mtime) -> loaded declared kinds.
_DISCOVER_CACHE: Dict[Tuple, List[RelationshipKind]] = {}


def _layer_of(stage_or_layer):
    """The context layer of whatever was passed: a Usd.Stage's root layer, an
    Sdf.Layer as-is, or None. A plain path string passes through unchanged."""
    if stage_or_layer is None or isinstance(stage_or_layer, str):
        return stage_or_layer
    get_root = getattr(stage_or_layer, "GetRootLayer", None)
    return get_root() if get_root else stage_or_layer


def _layer_path_and_text(layer) -> Tuple[str, str]:
    """(on-disk path or identifier, layer text). Reads the file when the layer
    is one (cheap, and works for a plain path string); falls back to
    ExportToString for an in-memory layer. Returns ("", "") over any failure."""
    if isinstance(layer, str):
        try:
            with open(layer) as fh:
                return layer, fh.read()
        except OSError:
            return "", ""
    path = getattr(layer, "realPath", "") or ""
    if path and os.path.isfile(path):
        try:
            with open(path) as fh:
                return path, fh.read()
        except OSError:
            pass
    try:
        return getattr(layer, "identifier", "") or "", layer.ExportToString()
    except Exception:
        return "", ""


def _sidecar_of(path: str) -> str:
    """The `.weft` sidecar trivially reachable from a context layer on disk:
    `scene.usda` -> `scene.weft.usda` beside it, or ""."""
    if not path:
        return ""
    sidecar = os.path.splitext(path)[0] + ".weft.usda"
    return sidecar if os.path.isfile(sidecar) else ""


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path) if path else 0.0
    except OSError:
        return 0.0


def discover(stage_or_layer) -> List[RelationshipKind]:
    """Every kind in play for a stage: the built-in relkinds.REGISTRY plus any
    `weft__kinds` declared on the context layer or its `.weft` sidecar. The
    viewer-side entry point (threadgraph.build_graph defaults its registry to
    this), so it never raises: no stage, no block, or a malformed block all
    degrade to the built-ins alone. Loads are cached per (layer, mtimes)."""
    try:
        layer = _layer_of(stage_or_layer)
        if layer is None:
            return list(REGISTRY)
        path, text = _layer_path_and_text(layer)
        if not text:
            return list(REGISTRY)
        sidecar = _sidecar_of(path)
        key = (path or getattr(layer, "identifier", ""),
               _mtime(path), sidecar, _mtime(sidecar))
        if key in _DISCOVER_CACHE:
            return list(REGISTRY) + _DISCOVER_CACHE[key]
        decls: List[dict] = []
        for t in (text,) if not sidecar else (text, open(sidecar).read()):
            try:
                decls += parse_kinds(t)
            except ValueError:
                continue                     # absent/malformed: built-ins only
        declared = load_kinds(decls) if decls else []
        _DISCOVER_CACHE[key] = declared
        return list(REGISTRY) + declared
    except Exception:
        return list(REGISTRY)

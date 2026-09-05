"""The resolver brain (phase 1 of the weft:// resolver): one weft
expression -> one referenceable surgical layer.

An expression is the compact string a weft:// URI will carry:

    weft://<context>?<expression>

where <expression> is seed and directive tokens separated by whitespace,
`;`, or `&` -- `&` so a URI query string IS a valid expression verbatim
(no valid token may contain `&`: ask.py reserves it inside `where:` and
follow.py's term grammar refuses it). Tokens:

    follow:<terms>   comma-joined follow terms (repeatable, accumulates)
    depth:<n>        global traversal depth (once)
    anything else    a seed, parsed by ask.parse_seed

    where:finish=translucent&follow:Mount&depth:3

Evaluation is pull() verbatim -- the surgical closure engine is not
reimplemented here. The closure's member paths become a population mask,
and the surgical layer is produced by method (a): flatten of a masked
open --

    Usd.Stage.OpenMasked(context, StagePopulationMask(members)).Flatten()

Tradeoff, measured on ALab: (a) is provably correct -- the flattened
layer reopened composes to EXACTLY the masked stage's prim set (asserted
by compose() on every run, and by tests/test_compose.py) -- at the cost
of materialising a flattened copy (the workbench's translucent pull
flattens to ~2 MB). Method (b), a stub layer referencing the scene and
deactivating the complement, would stay small and keep the reference
live, but enumerating the complement of a closure over a large scene is
its own traversal and every missed sibling is a silent over-inclusion;
correctness first, so (a). The real C++ ArResolver will apply the mask
at OPEN time (usdview's --mask / OpenMasked do exactly this today, see
mask_arg()), so no flatten happens in phase 2 -- the flatten here is a
stand-in that makes the surgical stage a portable, referenceable file.

Certification is the EXISTING pull manifest (manifest.to_document /
verify): the Pull that produced a surgical layer re-verifies against the
original context and layer hashes, unchanged."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .ask import parse_seed
from .follow import parse_follow

_SPLIT = re.compile(r"[\s;&]+")


@dataclass
class Expression:
    seeds: List[str] = field(default_factory=list)
    follow: List[str] = field(default_factory=list)
    depth: int = 4
    raw: str = ""


def parse_expression(text: str, default_depth: int = 4) -> Expression:
    """Parse the compact expression a weft:// URI carries. Loud on
    malformed tokens: every seed goes through ask.parse_seed and every
    follow term through follow.parse_follow, so reserved syntax fails
    here, not inside evaluation."""
    e = Expression(depth=default_depth, raw=text)
    depth_seen = False
    for tok in _SPLIT.split(text.strip()):
        if not tok:
            continue
        if tok.startswith("follow:"):
            terms = tok[len("follow:"):]
            if not terms:
                raise ValueError("follow: directive with no terms")
            e.follow.extend(t for t in terms.split(",") if t)
        elif tok.startswith("depth:"):
            if depth_seen:
                raise ValueError("depth: given twice")
            try:
                e.depth = int(tok[len("depth:"):])
            except ValueError:
                raise ValueError("depth: wants an integer, got %r"
                                 % tok[len("depth:"):])
            depth_seen = True
        else:
            parse_seed(tok)          # validation only; pull re-parses
            e.seeds.append(tok)
    if not e.seeds:
        raise ValueError("expression %r has no seeds" % text)
    parse_follow(e.follow)           # validation only
    return e


def mask_arg(paths: List[str]) -> str:
    """The member paths as usdview's native --mask argument -- the
    open-time-mask delivery of the same surgical stage, and the exact
    semantics the phase-2 C++ resolver applies at open."""
    return ",".join(paths)


def surgical_layer(context_file: str, seeds, follow=None, depth: int = 4,
                   extractors=()) -> Tuple["Pull", "Sdf.Layer"]:
    """Evaluate via pull() and flatten the masked open into a standalone
    surgical layer (method (a) above). Returns (pull, layer); the layer
    is anonymous until exported. Its customLayerData records provenance
    (context, seeds, follow, depth, members) so the layer is
    self-describing."""
    import os
    from pxr import Usd
    from .pull import pull
    from .manifest import mask_paths

    p = pull(context_file, seeds, follow=follow, depth=depth,
             extractors=extractors)
    paths = mask_paths(p)
    if not paths:
        raise ValueError("expression matched nothing; no surgical layer")
    masked = Usd.Stage.OpenMasked(context_file,
                                  Usd.StagePopulationMask(paths))
    layer = masked.Flatten()
    layer.customLayerData = {
        "weft__compose": json.dumps({
            "context": os.path.abspath(context_file),
            "seeds": [r.seed.raw for r in p.resolutions],
            "follow": list(p.follow),
            "depth": p.depth,
            "members": paths,
        }, sort_keys=True, separators=(",", ":"))
    }
    return p, layer


@dataclass
class Composed:
    pull: "Pull"
    layer: "Sdf.Layer"
    prim_count: int          # composed prims of the surgical stage
    member_count: int
    out: Optional[str] = None


def _prim_set(stage) -> set:
    return {pr.GetPath().pathString for pr in stage.Traverse()}


def compose(context_file: str, expression: str, out: Optional[str] = None,
            extractors=(), default_depth: int = 4) -> Composed:
    """The expression-string entry point -- the shape the weft:// URI
    drives. Writes the surgical layer to `out` when given, and PROVES
    method (a) on every run: the produced layer, reopened, must compose
    to exactly the masked stage's prim set, or this raises."""
    from pxr import Usd
    from .manifest import mask_paths

    e = parse_expression(expression, default_depth=default_depth)
    p, layer = surgical_layer(context_file, e.seeds, follow=e.follow,
                              depth=e.depth, extractors=extractors)
    paths = mask_paths(p)
    want = _prim_set(Usd.Stage.OpenMasked(context_file,
                                          Usd.StagePopulationMask(paths)))
    if out:
        layer.Export(out)
        got = _prim_set(Usd.Stage.Open(out))
    else:
        got = _prim_set(Usd.Stage.Open(layer))
    if got != want:
        raise RuntimeError(
            "surgical layer diverged from masked open: %d only in layer, "
            "%d only in masked stage" % (len(got - want), len(want - got)))
    return Composed(pull=p, layer=layer, prim_count=len(got),
                    member_count=len(paths), out=out)

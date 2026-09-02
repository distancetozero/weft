"""Reading .usda, through pxr when it is installed.

Two backends behind one shape:

  pxr        `Sdf.Layer` -- the real thing. Note Sdf, not Usd: the raw
             `(path, field) -> value` data model reads authored `apiSchemas`
             without those schemas being registered, which is exactly what a
             contract surface needs.

  fallback   A restricted hand-rolled parser, used when pxr is absent. It
             handles prims, nested prims, applied API schemas and uniform
             attributes of scalar, tuple and array type -- and nothing else:
             no variants, no references, no composition. Enough for a contract
             surface, and no more.

Contracts had to be authored in real USD -- declaring an interface in JSON
would prove nothing about whether the design fits USD -- but rung 1 must run
with no dependencies at all. Hence both. `tests/test_usda.py` asserts the two
backends agree, because a silent divergence would mean an interface that reads
differently depending on what happens to be installed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_TOKEN = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<comment>\#[^\n]*)
    | (?P<string>"(?:[^"\\]|\\.)*")
    | (?P<punct>[(){}\[\],=])
    | (?P<number>-?\d+\.\d*(?:[eE][-+]?\d+)?|-?\.\d+|-?\d+(?:[eE][-+]?\d+)?)
    | (?P<name>[A-Za-z_][A-Za-z0-9_:.|]*)
    """,
    re.VERBOSE,
)


class UsdaError(ValueError):
    pass


@dataclass
class Prim:
    name: str
    type_name: str = ""
    api_schemas: List[str] = field(default_factory=list)
    attrs: Dict[str, Any] = field(default_factory=dict)
    children: Dict[str, "Prim"] = field(default_factory=dict)
    path: str = ""

    def walk(self):
        yield self
        for c in self.children.values():
            yield from c.walk()

    def has_api(self, name: str) -> bool:
        """True for an exact match or any multiple-apply instance of it."""
        return any(s == name or s.startswith(name + ":") for s in self.api_schemas)

    def api_instances(self, name: str) -> List[str]:
        """Instance names of a multiple-apply schema, e.g. ['frontHub']."""
        out = []
        for s in self.api_schemas:
            if s.startswith(name + ":"):
                out.append(s.split(":", 1)[1])
        return out


def _tokenize(text: str) -> List[str]:
    out: List[str] = []
    pos = 0
    n = len(text)
    while pos < n:
        m = _TOKEN.match(text, pos)
        if not m:
            raise UsdaError("unparsable input at offset %d: %r" % (pos, text[pos:pos + 24]))
        pos = m.end()
        kind = m.lastgroup
        if kind in ("ws", "comment"):
            continue
        out.append(m.group())
    return out


class _Parser:
    def __init__(self, tokens: List[str]):
        self.t = tokens
        self.i = 0

    def peek(self, ahead: int = 0) -> Optional[str]:
        j = self.i + ahead
        return self.t[j] if j < len(self.t) else None

    def next(self) -> str:
        if self.i >= len(self.t):
            raise UsdaError("unexpected end of input")
        tok = self.t[self.i]
        self.i += 1
        return tok

    def expect(self, tok: str) -> None:
        got = self.next()
        if got != tok:
            raise UsdaError("expected %r, got %r" % (tok, got))

    # -- values -----------------------------------------------------------
    def parse_value(self) -> Any:
        tok = self.peek()
        if tok is None:
            raise UsdaError("expected a value")
        if tok == "[":
            self.next()
            items = []
            while self.peek() != "]":
                items.append(self.parse_value())
                if self.peek() == ",":
                    self.next()
            self.expect("]")
            return items
        if tok == "{":
            return self.parse_dict()
        if tok == "(":
            self.next()
            items = []
            while self.peek() != ")":
                items.append(self.parse_value())
                if self.peek() == ",":
                    self.next()
            self.expect(")")
            return tuple(items)
        tok = self.next()
        if tok.startswith('"'):
            return tok[1:-1].encode().decode("unicode_escape")
        if tok in ("true", "false"):
            return tok == "true"
        try:
            return int(tok)
        except ValueError:
            pass
        try:
            return float(tok)
        except ValueError:
            pass
        return tok

    # -- metadata block ( ... ) -------------------------------------------
    def parse_meta(self) -> Dict[str, Any]:
        self.expect("(")
        meta: Dict[str, Any] = {}
        while self.peek() != ")":
            tok = self.next()
            if tok in ("prepend", "append", "add", "delete", "uniform", "custom"):
                continue
            key = tok
            if self.peek() == "=":
                self.next()
                meta[key] = self.parse_value()
            elif self.peek() == "{":
                meta[key] = self.parse_dict()
            else:
                meta[key] = True
        self.expect(")")
        return meta

    def parse_dict(self) -> Dict[str, Any]:
        self.expect("{")
        out: Dict[str, Any] = {}
        while self.peek() != "}":
            tok = self.next()
            if tok in ("string", "token", "dictionary", "bool", "int", "double", "float"):
                key_tok = self.next()
                key = key_tok[1:-1] if key_tok.startswith('"') else key_tok
                if self.peek() == "=":
                    self.next()
                    out[key] = self.parse_value()
                elif self.peek() == "{":
                    out[key] = self.parse_dict()
            else:
                if self.peek() == "=":
                    self.next()
                    out[tok] = self.parse_value()
        self.expect("}")
        return out

    # -- prims ------------------------------------------------------------
    def parse_prim(self, parent_path: str) -> Prim:
        kw = self.next()
        if kw not in ("def", "over", "class"):
            raise UsdaError("expected def/over/class, got %r" % kw)

        type_name = ""
        if not self.peek().startswith('"'):
            type_name = self.next()
        name = self.next()[1:-1]
        path = "%s/%s" % (parent_path.rstrip("/"), name)
        prim = Prim(name=name, type_name=type_name, path=path)

        if self.peek() == "(":
            meta = self.parse_meta()
            schemas = meta.get("apiSchemas") or []
            prim.api_schemas = [s for s in schemas if isinstance(s, str)]

        self.expect("{")
        while self.peek() != "}":
            if self.peek() in ("def", "over", "class"):
                child = self.parse_prim(path)
                prim.children[child.name] = child
                continue
            # attribute:  [uniform|custom] <type> <name> = <value> [( meta )]
            while self.peek() in ("uniform", "custom", "varying"):
                self.next()
            self.next()  # type name, unused: values are self-describing enough here
            attr = self.next()
            if self.peek() == "=":
                self.next()
                prim.attrs[attr] = self.parse_value()
            else:
                prim.attrs[attr] = None
            if self.peek() == "(":
                self.parse_meta()
        self.expect("}")
        return prim


@dataclass
class Layer:
    meta: Dict[str, Any] = field(default_factory=dict)
    prims: Dict[str, Prim] = field(default_factory=dict)

    def walk(self):
        for p in self.prims.values():
            yield from p.walk()


def _have_pxr() -> bool:
    try:
        from pxr import Sdf  # noqa: F401
        return True
    except ImportError:
        return False


def _from_sdf(layer_obj) -> Layer:
    """Build the same shape from an Sdf.Layer."""
    from pxr import Sdf

    def value(v):
        # Normalise pxr's vector and array types to plain tuples/lists so both
        # backends return identical structures.
        if isinstance(v, Sdf.AssetPath):
            return v.path
        if isinstance(v, str) or isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return v
        try:
            items = list(v)
        except TypeError:
            return v
        if items and hasattr(items[0], "__len__") and not isinstance(items[0], str):
            return [tuple(float(x) for x in row) for row in items]
        if all(isinstance(x, (int, float)) for x in items) and hasattr(v, "dimension"):
            return tuple(float(x) for x in items)
        return [value(x) for x in items]

    def convert(spec, parent_path: str) -> Prim:
        prim = Prim(name=spec.name, type_name=spec.typeName or "",
                    path="%s/%s" % (parent_path.rstrip("/"), spec.name))
        if "apiSchemas" in spec.ListInfoKeys():
            prim.api_schemas = list(
                spec.GetInfo("apiSchemas").GetAddedOrExplicitItems())
        for attr in spec.attributes:
            prim.attrs[attr.name] = value(attr.default) if attr.HasDefaultValue() else None
        for child in spec.nameChildren:
            c = convert(child, prim.path)
            prim.children[c.name] = c
        return prim

    out = Layer()
    if layer_obj.customLayerData:
        out.meta["customLayerData"] = dict(layer_obj.customLayerData)
    if layer_obj.HasDefaultPrim():
        out.meta["defaultPrim"] = layer_obj.defaultPrim
    for spec in layer_obj.rootPrims:
        prim = convert(spec, "")
        out.prims[prim.name] = prim
    return out


def parse_pxr(text: str) -> Layer:
    from pxr import Sdf, Tf

    layer_obj = Sdf.Layer.CreateAnonymous(".usda")
    try:
        ok = layer_obj.ImportFromString(text)
    except Tf.ErrorException as e:
        # Normalise to our own error so callers need not know which backend ran.
        raise UsdaError(str(e).strip().splitlines()[-1].strip()) from e
    if not ok:
        raise UsdaError("USD rejected this layer")
    return _from_sdf(layer_obj)


def parse_fallback(text: str) -> Layer:
    text = text.lstrip()
    if not text.startswith("#usda"):
        raise UsdaError("not a .usda layer (missing #usda header)")
    text = text.split("\n", 1)[1] if "\n" in text else ""
    p = _Parser(_tokenize(text))
    layer = Layer()
    if p.peek() == "(":
        layer.meta = p.parse_meta()
    while p.peek() is not None:
        prim = p.parse_prim("")
        layer.prims[prim.name] = prim
    return layer


def parse(text: str, force_fallback: bool = False) -> Layer:
    """Parse a .usda layer. Uses pxr when installed."""
    if not force_fallback and _have_pxr():
        return parse_pxr(text)
    return parse_fallback(text)


def parse_file(path: Path, force_fallback: bool = False) -> Layer:
    return parse(Path(path).read_text(), force_fallback=force_fallback)

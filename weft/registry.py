"""Omission classes (spec section 6): the semantic effect of NOT populating
a relationship target. Extensible by teams; unlisted kinds default to inert,
and the manifest notes when a class was defaulted."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Dict, List

INERT = "inert"
MEANING_CHANGING = "meaning-changing"

# Prefix -> class. A kind matches when it equals the key or starts with it
# (keys end in ":" to mark them as prefixes).
OMISSION_CLASSES: Dict[str, str] = {
    "physics:": MEANING_CHANGING,      # any physics: relationship
    "skel:": MEANING_CHANGING,
}


def omission_class(kind: str) -> str:
    for key, cls in OMISSION_CLASSES.items():
        if kind == key or (key.endswith(":") and kind.startswith(key)):
            return cls
    if kind.startswith("collection:") and "colliders" in kind:
        return MEANING_CHANGING
    return INERT


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
        "# into first-class edges. Apply with `weft pull --extractors %s`." % name,
        "(",
        "    customLayerData = {",
        '        string jitsd__extractors = "%s"' % esc,
        "    }",
        ")",
        "",
    ])

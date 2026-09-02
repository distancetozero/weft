"""Omission classes (spec section 6): the semantic effect of NOT populating
a relationship target. Extensible by teams; unlisted kinds default to inert,
and the manifest notes when a class was defaulted."""

from __future__ import annotations

from typing import Dict

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

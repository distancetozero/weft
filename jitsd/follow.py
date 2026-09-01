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

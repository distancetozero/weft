"""Carry an existing AGENTS.md / CLAUDE.md below the maat section, untouched."""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

HEADING = "## Existing rules (carried over, prune by hand)"

# Ends the maat-owned part of AGENTS.md / CLAUDE.md; everything below it is the project's.
MARKER = "<!-- maat:end -->"

# maat rule number -> what an existing line looks like when that rule covers it
COVERED_PATTERNS: Dict[int, "re.Pattern[str]"] = {
    1: re.compile(r"explicit authori[sz]ation|never (merge|ship)", re.I),
    2: re.compile(r"worktree|pull request|--no-verify", re.I),
    3: re.compile(r"acceptance", re.I),
    4: re.compile(r"\bbd\b|beads", re.I),
    5: re.compile(r"plain rule|machinery|enforcement", re.I),
    6: re.compile(r"precedence", re.I),
}


def covered(existing: str) -> List[str]:
    """Existing lines that match any pattern, in file order, deduplicated."""
    seen = set()
    out = []
    for line in existing.splitlines():
        if line in seen:
            continue
        if any(p.search(line) for p in COVERED_PATTERNS.values()):
            seen.add(line)
            out.append(line)
    return out


def split_at_marker(text: str) -> Optional[Tuple[str, str]]:
    """(text up to and including the marker line, the rest), or None without a marker."""
    i = text.find(MARKER)
    if i < 0:
        return None
    j = i + len(MARKER)
    return text[:j], text[j:]


def keep_below_marker(rendered: str, existing: str) -> Optional[str]:
    """Fresh maat part up to its marker, then the existing file's text after its marker."""
    old, new = split_at_marker(existing), split_at_marker(rendered)
    if old is None or new is None:
        return None
    return new[0] + old[1]


def merge_existing(rendered: str, existing: str) -> Tuple[str, List[str]]:
    """Rendered maat section, then the existing text verbatim under a heading."""
    marker = "\n" + HEADING + "\n\n"
    # Re-running over a file maat already merged: keep only the carried text.
    if marker in "\n" + existing:
        existing = ("\n" + existing).split(marker, 1)[1]
    body = existing.rstrip("\n") + "\n" if existing.strip() else ""
    merged = rendered.rstrip("\n") + "\n\n" + HEADING + "\n\n" + body
    return merged, covered(existing)

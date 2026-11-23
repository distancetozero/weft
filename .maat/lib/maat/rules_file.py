"""Carry an existing AGENTS.md / CLAUDE.md below the maat section, untouched.

Also the start-and-end block maat owns inside a repository's own CONTRIBUTING.md.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

HEADING = "## Existing rules (carried over, prune by hand)"

# Ends the maat-owned part of AGENTS.md / CLAUDE.md; everything below it is the project's.
MARKER = "<!-- maat:end -->"

# Opens the maat-owned block of CONTRIBUTING.md (Issues tracker); MARKER closes it.
START = "<!-- maat:start -->"

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


class BlockError(ValueError):
    """A text whose block markers do not form exactly one start-then-end pair."""


def split_block(text: str) -> Optional[Tuple[str, str, str]]:
    """(before, block, after) with before + block + after == text, or None without markers.

    The block runs from the START line through the MARKER line, without the
    MARKER line's line ending. Only a marker alone on its line counts, and not
    inside a fenced code block (``` or ~~~, closed by a line opening with the same three).
    """
    starts: List[Tuple[int, int]] = []
    ends: List[Tuple[int, int]] = []
    pos = 0
    fence = ""
    for line in text.split("\n"):
        stripped = line.strip()
        body = line[:-1] if line.endswith("\r") else line
        if fence:
            if stripped.startswith(fence):
                fence = ""
        elif stripped.startswith(("```", "~~~")):
            fence = stripped[:3]
        elif stripped == START:
            starts.append((pos, pos + len(body)))
        elif stripped == MARKER:
            ends.append((pos, pos + len(body)))
        pos += len(line) + 1
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1 or ends[0][0] < starts[0][0]:
        raise BlockError("needs exactly one start and one end marker (%s, then %s), each on "
                         "its own line; found %d start and %d end"
                         % (START, MARKER, len(starts), len(ends)))
    i, j = starts[0][0], ends[0][1]
    return text[:i], text[i:j], text[j:]


def _block(text: str) -> str:
    parts = split_block(text)
    if parts is None:
        raise BlockError("no block: needs one start and one end marker")
    return parts[1]


def replace_block(existing: str, rendered: str) -> str:
    """existing with its block replaced by rendered's; every other byte kept."""
    parts = split_block(existing)
    if parts is None:
        raise BlockError("no block to replace: needs one start and one end marker")
    return parts[0] + _block(rendered) + parts[2]


def append_block(existing: str, rendered: str) -> str:
    """existing unchanged, one blank line, then rendered's block and a final newline.

    No blank line is added when existing already ends with one.
    """
    head = existing if existing.endswith("\n") else existing + "\n"
    blank = "" if head.endswith(("\n\n", "\n\r\n")) else "\n"
    return head + blank + _block(rendered) + "\n"

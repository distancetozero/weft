"""absent -- find what a USD stage refers to that is no longer there.

USD can tell you what is in a scene. This tells you what isn't, and why.
"""

from .detect import (  # noqa: F401
    ANCHOR_KEY,
    AUTHORED_AGAINST_KEY,
    DEAD,
    MOVED,
    UNKNOWN,
    Finding,
    Report,
    anchor_index,
    scan,
    scan_file,
)

__all__ = [
    "ANCHOR_KEY", "AUTHORED_AGAINST_KEY", "DEAD", "MOVED", "UNKNOWN",
    "Finding", "Report", "anchor_index", "scan", "scan_file",
]

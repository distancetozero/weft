"""deps -- what depends on what, in USD, without opening a scene.

No stock USD API answers this. The composition-arc APIs report which *files* a
file needs and never see a material binding, a skel binding, an attribute
connection, or a class arc -- and none of them can tell you what points *at*
something, which is the question people actually ask before republishing.
"""

from .graph import Cache, Graph, Unresolved, build, discover  # noqa: F401
from .walk import (  # noqa: F401
    ARC, ASSET_ATTR, COLLECTION, CONN, INHERIT, REL,
    Edge, LayerRecord, walk_file, walk_layer,
)

__all__ = [
    "Cache", "Graph", "Unresolved", "build", "discover",
    "Edge", "LayerRecord", "walk_file", "walk_layer",
    "ARC", "ASSET_ATTR", "COLLECTION", "CONN", "INHERIT", "REL",
]

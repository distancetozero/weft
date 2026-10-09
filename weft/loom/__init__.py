"""The Loom: a read-only "USD as data" inspector/query surface
(docs/superpowers/specs/2026-10-07-the-loom.md).

Point it at a stage you didn't build and see it as data -- profile, relationship
graph, table -- then follow/slice/certify what you need. Deliberately not an
authoring tool and not a renderer: it *consumes* what any DCC/pipeline authored
(native rels, collections, material bindings) and makes it queryable. All logic
reuses weft's engine (threadgraph, data, pull, compose, manifest); this package
is just a localhost transport over it plus a page.
"""
from .server import LoomState, serve, export  # noqa: F401

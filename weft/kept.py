"""Kept sets: keep a box expression's set, and report how it moved -- in plain
terms, matching by identity so a rename doesn't count. General over any weft
expression (cf. drift.py, the ALab finish specialist). Read-only on the stage;
storage writes only under `.weft/kept/`."""
from __future__ import annotations

import datetime
import json
import os
import re
from pathlib import Path
from typing import List, Optional

DIRNAME = ".weft"


# -- engine ---------------------------------------------------------------

def read(prim) -> dict:
    """The few things whose change is the move that matters."""
    from pxr import UsdShade
    mat = None
    try:
        m = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial(UsdShade.Tokens.full)[0]
        if m and m.GetPrim() and m.GetPrim().IsValid():
            mat = m.GetPath().pathString
    except Exception:
        pass
    return {"type": str(prim.GetTypeName()), "material": mat}


def _members(stage, context, expression) -> List[dict]:
    from . import compose as _compose, pull as _pull, ask as _ask
    e = _compose.parse_expression(expression)
    p = _pull.pull(context, e.seeds, follow=e.follow, depth=e.depth)
    out = []
    for m in p.members:
        prim = stage.GetPrimAtPath(m.path)
        if not prim or not prim.IsValid():
            continue
        out.append({"path": m.path, "id": _ask.identity_of(prim), "read": read(prim)})
    return out


def capture(stage, context, expression, name) -> dict:
    """The kept-set record. Raises ValueError on an expression that does not
    parse (callers turn that into an honest {error})."""
    return {"name": name, "expression": expression,
            "created": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "members": _members(stage, context, expression)}


def check(record, stage, context) -> dict:
    """Diff the recorded set against the current stage. Never raises: a bad
    expression comes back as holds=False with an `error`."""
    recorded = record.get("members", [])
    try:
        current = _members(stage, context, record["expression"])
    except Exception as e:
        return {"holds": False, "arrived": [], "changed": [], "gone": [],
                "renamed": [], "counts": {"arrived": 0, "changed": 0, "gone": 0, "renamed": 0},
                "error": "%s" % e}
    by_id_rec = {m["id"]: m for m in recorded if m.get("id")}
    by_path_rec = {m["path"]: m for m in recorded}
    used = set()
    arrived, changed, gone, renamed = [], [], [], []
    for c in current:
        r = (by_id_rec.get(c["id"]) if c.get("id") else None) or by_path_rec.get(c["path"])
        if not r or r["path"] in used:
            arrived.append({"path": c["path"], "read": c["read"]})
            continue
        used.add(r["path"])
        if r["read"] != c["read"]:
            changed.append({"path": c["path"], "old": r["read"], "new": c["read"]})
        elif r["path"] != c["path"]:
            renamed.append({"old_path": r["path"], "new_path": c["path"]})
    for r in recorded:
        if r["path"] not in used:
            gone.append({"path": r["path"]})
    counts = {"arrived": len(arrived), "changed": len(changed),
              "gone": len(gone), "renamed": len(renamed)}
    return {"holds": not (arrived or changed or gone), "arrived": arrived,
            "changed": changed, "gone": gone, "renamed": renamed, "counts": counts}

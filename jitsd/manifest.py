"""The pull manifest (spec section 8): a USDA document whose customLayerData
records the COMPLETE evaluation inputs, so a pull is verifiable by
recompute-and-compare. A manifest is valid against its recorded layer set,
not a context name."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List

from .pull import Pull, PullMember

PULL_RE = re.compile(r'string\s+jitsd__pull\s*=\s*"((?:[^"\\]|\\.)*)"')
MANIFEST_VERSION = 1


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def layer_hashes(p: Pull) -> None:
    seen: Dict[str, str] = dict(p.layers)
    if p.context not in seen:
        seen[p.context] = ""
    total = 0
    out = []
    for ident in sorted(seen):
        try:
            h = _sha256_file(ident)
            total += Path(ident).stat().st_size
        except OSError:
            h = ""
        out.append((ident, h))
    p.layers = out
    p.accounting["layer_bytes"] = total
    p.accounting["asset_paths_not_priced"] = p.accounting.get(
        "asset_paths_not_priced", 0)


def _payload(p: Pull, usd_version: str) -> dict:
    return {
        "manifestVersion": MANIFEST_VERSION,
        "context": {"path": p.context,
                    "hash": dict(p.layers).get(p.context, "")},
        "usdVersion": usd_version,
        "asks": [r.seed.raw for r in p.resolutions],
        "resolutions": [{"ask": r.seed.raw, "mode": r.mode,
                         "matched": r.matched, "complement": r.complement,
                         "note": r.note} for r in p.resolutions],
        "follow": list(p.follow),
        "depth": p.depth,
        "variantSelections": list(p.variant_selections),
        "members": [asdict(m) for m in p.members],
        "boundary": [asdict(b) for b in p.boundary],
        "layers": [list(l) for l in p.layers],
        "accounting": dict(p.accounting),
        "fitness": dict(p.fitness),
        "declarations": list(p.declarations),
        "loadSet": None,      # reserved (spec section 2)
    }


def digest(payload: dict) -> str:
    body = {k: v for k, v in payload.items() if k != "digest"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def to_document(p: Pull, usd_version: str = "") -> str:
    if not usd_version:
        try:
            from pxr import Usd
            usd_version = ".".join(str(x) for x in Usd.GetVersion())
        except Exception:
            usd_version = "unknown"
    payload = _payload(p, usd_version)
    payload["digest"] = digest(payload)
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    esc = body.replace("\\", "\\\\").replace('"', '\\"')
    return "\n".join([
        "#usda 1.0",
        "# A pull manifest. Valid against its recorded layer set; verify",
        "# with `jitsd pull --verify` before trusting the mask.",
        "(",
        "    customLayerData = {",
        '        string jitsd__pull = "%s"' % esc,
        "    }",
        ")",
        "",
    ])


def read_document(text: str) -> dict:
    m = PULL_RE.search(text)
    if not m:
        raise ValueError("no jitsd__pull block")
    return json.loads(m.group(1).encode().decode("unicode_escape"))


def mask_paths(p: Pull) -> List[str]:
    return [m.path for m in p.members]


def write_mask(p: Pull, path) -> None:
    Path(path).write_text("\n".join(mask_paths(p)) + "\n")


def verify(document_text: str) -> List[str]:
    """The mandatory verification pass (spec section 8)."""
    from pxr import Usd
    d = read_document(document_text)
    findings: List[str] = []
    if d.get("digest") != digest(d):
        findings.append("digest mismatch: manifest was edited or truncated")
    for ident, recorded in d["layers"]:
        if not recorded:
            continue
        try:
            now = _sha256_file(ident)
        except OSError:
            findings.append("layer %s: missing" % ident)
            continue
        if now != recorded:
            findings.append("layer %s: hash changed since manifest" % ident)
    paths = [m["path"] for m in d["members"]]
    if paths:
        mask = Usd.StagePopulationMask(paths)
        stage = Usd.Stage.OpenMasked(d["context"]["path"], mask)
        for path in paths:
            if not stage.GetPrimAtPath(path):
                findings.append(
                    "member %s does not resolve to a populated prim "
                    "(closure over-approximated; fatal)" % path)
    return findings

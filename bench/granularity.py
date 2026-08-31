"""Open question 9, settled by measurement rather than argument.

The claim under test: byte-level chunking cannot survive a DCC re-export, but
hashing per `(path, field)` -- USD's own decomposition -- can.

A re-export is not one thing, so each perturbation is measured separately:

  reserialise   same scene, written again from scratch. No semantic change.
  one-mesh      one mesh edited; everything else semantically identical.
  reorder       prims emitted in a different order, values unchanged.
  float-noise   every float perturbed in its low bits.

For each, two strategies are scored on how much of version B is already present
after storing version A:

  bytes    content-defined chunking over the .usdc file  (what we ship today)
  fields   sha256 over each (path, field) canonical value
"""

from __future__ import annotations

import hashlib
import random
import struct
import sys
import tempfile
from pathlib import Path
from typing import Dict, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pxr import Gf, Sdf, Usd, UsdGeom, Vt  # noqa: E402

from jitsd.store import ObjectStore  # noqa: E402

MESHES = 4000
PTS = 300


def human(n: float) -> str:
    for u in ("B", "KiB", "MiB", "GiB"):
        if abs(n) < 1024 or u == "GiB":
            return "%.1f %s" % (n, u)
        n /= 1024.0
    return "%.1f GiB" % n


# -- authoring -------------------------------------------------------------

def build(path: str, seed: int = 7, order=None, jitter: float = 0.0,
          edit_mesh: int = -1) -> str:
    rng = random.Random(seed)
    stage = Usd.Stage.CreateNew(path)
    UsdGeom.Xform.Define(stage, "/World")
    names = ["mesh_%03d" % i for i in range(MESHES)]
    if order == "reverse":
        names = list(reversed(names))
    for name in names:
        i = int(name.split("_")[1])
        r = random.Random(seed * 1000 + i)
        m = UsdGeom.Mesh.Define(stage, "/World/%s" % name)
        pts = []
        for k in range(PTS):
            v = [r.uniform(-1, 1) for _ in range(3)]
            if jitter:
                v = [x + random.Random(i * 99999 + k).uniform(-jitter, jitter) for x in v]
            if i == edit_mesh:
                v = [x + 0.05 for x in v]
            pts.append(Gf.Vec3f(*v))
        m.CreatePointsAttr(Vt.Vec3fArray(pts))
        m.CreateFaceVertexCountsAttr(Vt.IntArray([3] * (PTS // 3)))
        m.CreateFaceVertexIndicesAttr(Vt.IntArray(list(range(PTS))))
        m.CreateDisplayColorAttr(Vt.Vec3fArray([Gf.Vec3f(0.5, 0.5, 0.5)]))
    stage.GetRootLayer().Save()
    del stage
    return path


# -- field-level hashing ---------------------------------------------------

def canonical(value) -> bytes:
    """A stable encoding of a typed value, independent of serialisation."""
    if isinstance(value, (Vt.Vec3fArray, Vt.Vec3dArray)):
        return b"v3:" + struct.pack("<%df" % (len(value) * 3),
                                    *[c for v in value for c in v])
    if isinstance(value, Vt.IntArray):
        return b"i:" + struct.pack("<%di" % len(value), *value)
    if isinstance(value, Vt.FloatArray):
        return b"f:" + struct.pack("<%df" % len(value), *value)
    if isinstance(value, (Gf.Vec3f, Gf.Vec3d)):
        return b"v:" + struct.pack("<3f", *value)
    return ("s:%r" % (value,)).encode()


def field_hashes(usd_path: str) -> Dict[str, Tuple[str, int]]:
    """{key: (hash, size)} for every (path, field) in the layer."""
    layer = Sdf.Layer.FindOrOpen(usd_path)
    out: Dict[str, Tuple[str, int]] = {}

    def visit(spec):
        for attr in spec.attributes:
            if not attr.HasDefaultValue():
                continue
            blob = canonical(attr.default)
            key = "%s.%s" % (spec.path, attr.name)
            out[key] = (hashlib.sha256(blob).hexdigest(), len(blob))
        for child in spec.nameChildren:
            visit(child)

    for root in layer.rootPrims:
        visit(root)
    return out


# -- scoring ---------------------------------------------------------------

def score_bytes(a: str, b: str, avg: int = 64 * 1024) -> Tuple[int, int]:
    """(new bytes for B given A, size of B) by content-defined chunking.

    NOTE ON avg: an earlier run of this benchmark used the shipping 1 MiB
    default against a 710 KiB file -- two chunks -- and concluded byte
    chunking recovered nothing. That was a parameterisation artifact, not a
    property of crate. Chunk size must be small relative to the file or the
    measurement is meaningless.
    """
    from jitsd.chunker import chunk

    A, B = Path(a).read_bytes(), Path(b).read_bytes()
    kw = dict(min_size=avg // 4, avg_size=avg, max_size=avg * 4)
    seen = {hashlib.sha256(c).hexdigest() for c in chunk(A, **kw)}
    new = sum(len(c) for c in chunk(B, **kw)
              if hashlib.sha256(c).hexdigest() not in seen)
    return new, len(B)


def score_fields(a: str, b: str) -> Tuple[int, int, int, int]:
    """(new bytes, total bytes, new fields, total fields) for B given A."""
    ha, hb = field_hashes(a), field_hashes(b)
    seen = {h for h, _ in ha.values()}
    new_bytes = sum(sz for h, sz in hb.values() if h not in seen)
    total = sum(sz for _, sz in hb.values())
    new_fields = sum(1 for h, _ in hb.values() if h not in seen)
    return new_bytes, total, new_fields, len(hb)


def main() -> int:
    d = Path(tempfile.mkdtemp(prefix="q9-scenes-"))

    print("Is crate output deterministic for identical data?")
    x1 = build(str(d / "det1.usdc"))
    x2 = build(str(d / "det2.usdc"))
    b1, b2 = Path(x1).read_bytes(), Path(x2).read_bytes()
    print("  same scene written twice: %s  (%s vs %s)\n"
          % ("IDENTICAL" if b1 == b2 else "DIFFERENT", human(len(b1)), human(len(b2))))

    base = build(str(d / "base.usdc"))
    cases = [
        ("reserialise", build(str(d / "re.usdc"))),
        ("one-mesh",    build(str(d / "one.usdc"), edit_mesh=7)),
        ("reorder",     build(str(d / "ord.usdc"), order="reverse")),
        ("float-noise", build(str(d / "noise.usdc"), jitter=1e-4)),
    ]

    print("scene: %d meshes x %d points  ·  %s on disk\n"
          % (MESHES, PTS, human(Path(base).stat().st_size)))
    print("%-13s %12s %12s %s"
          % ("perturbation", "bytes new", "fields new", "fields changed"))
    print("-" * 58)
    for label, other in cases:
        nb, tb = score_bytes(base, other)
        nf, tf, cnt, total = score_fields(base, other)
        print("%-13s %11.1f%% %11.1f%%  %d / %d"
              % (label, 100.0 * nb / tb, 100.0 * nf / tf, cnt, total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

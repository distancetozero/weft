"""Price the closure operation (docs/10-slices.md, plan step 1).

Builds a chain of K assets -- link_i offers Chain@1 at slot_i and requires
slot_{i+1} -- so selecting link_000 with needs-closure pulls the entire chain.
This is the worst closure shape: maximally deep, one edge per hop.

Everything here is phase A: revisions and surfaces, no geometry, no payloads
beyond a token blob per asset.
"""

from __future__ import annotations

import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jitsd.ledger import Repo               # noqa: E402
from jitsd.slice import SliceSpec, resolve_slice  # noqa: E402

IFACE = """#usda 1.0
def Xform "link_%03d" (
    prepend apiSchemas = ["JitsdOfferAPI"%s]
)
{
    uniform token jitsd:offer:contract = "Chain@1"
    uniform token jitsd:mount:role = "slot_%03d"
%s}
"""

REQ = """    uniform token jitsd:require:next:contract = "Chain@1"
    uniform token jitsd:require:next:role = "slot_%03d"
    uniform token jitsd:require:next:cardinality = "one"
    uniform token jitsd:require:next:failurePolicy = "required"
"""


def build(root: Path, k: int) -> Repo:
    repo = Repo(root)
    repo.init()
    blob = root / "payload.bin"
    blob.write_bytes(random.Random(1).randbytes(4096))
    for i in range(k):
        req = REQ % (i + 1) if i < k - 1 else ""
        api = ', "JitsdRequireAPI:next"' if req else ""
        iface = root / ("l%03d.usda" % i)
        iface.write_text(IFACE % (i, api, i, req))
        repo.save("link_%03d" % i, blob, "bench", interface=iface)
        repo.promote("link_%03d" % i, "v001", "approved")
    return repo


def main() -> int:
    print("%8s %12s %12s %10s" % ("chain", "build s", "select ms", "members"))
    print("-" * 46)
    for k in (50, 200, 500, 1000):
        root = Path(tempfile.mkdtemp(prefix="jitsd-closure-"))
        try:
            t0 = time.perf_counter()
            repo = build(root, k)
            built = time.perf_counter() - t0

            t1 = time.perf_counter()
            res = resolve_slice(repo, SliceSpec(seeds=["link_000"], depth=k))
            sel = (time.perf_counter() - t1) * 1000.0

            assert len(res.members) == k, (len(res.members), k)
            assert res.ok
            print("%8d %12.1f %12.1f %10d" % (k, built, sel, len(res.members)))
        finally:
            shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

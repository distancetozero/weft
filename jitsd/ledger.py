"""Revisions, channels and baselines.

The three-layer model from docs/03-versioning.md:

  revisions   immutable, content-addressed. Every save makes one.
  channels    the ONLY mutable object in the system -- a pointer to a revision.
  baselines   immutable, named, complete resolution maps. The lockfile.

Revision and baseline files are real .usda layers, so they open in usdview and
diff as text. Rung 1 has no pxr dependency, so machine-readable state travels
in a compact JSON string inside customLayerData (`jitsd__meta`) which one regex
recovers. When pxr is available this is read properly through the USD API and
the shim goes away -- the file on disk does not change either way.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

from .contracts import Surface, Resolution, Violation, check_compatibility, extract_text, resolve
from .store import ObjectStore

META_RE = re.compile(r'string\s+jitsd__meta\s*=\s*"""(.*?)"""', re.DOTALL)

DEFAULT_CHANNELS = ("wip", "review", "approved")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


@dataclass
class Revision:
    asset: str
    rev: str
    blob: Optional[str]
    size: int
    parent: Optional[str]
    author: str
    created: str
    message: str = ""
    # Contract surface, extracted at save time from an authored .usda interface.
    # Stored on the revision so resolution never re-parses and never needs the
    # payload -- resolution is a relational-plane operation (docs/02).
    interface_blob: Optional[str] = None
    surface: Optional[Dict] = None
    # A revision is EITHER a stored payload (a constant) or a generator
    # reference (a function). Both are generators; a constant is one with no
    # parameters. See docs/04-contracts.md.
    generator: Optional[str] = None
    params: Optional[Dict] = None


@dataclass
class Baseline:
    number: str
    label: str
    parent: Optional[str]
    cut: str
    cut_by: str
    pins: Dict[str, str]
    merkle_root: str


class Ledger:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.assets = self.root / "assets"
        self.baselines_dir = self.root / "baselines"
        self.logdir = self.root / "log"

    def init(self) -> None:
        for d in (self.assets, self.baselines_dir, self.logdir):
            d.mkdir(parents=True, exist_ok=True)

    # -- event log --------------------------------------------------------
    def log_event(self, kind: str, **fields) -> None:
        rec = {"t": _now(), "kind": kind}
        rec.update(fields)
        day = time.strftime("%Y-%m-%d", time.gmtime())
        self.logdir.mkdir(parents=True, exist_ok=True)
        with (self.logdir / ("%s.jsonl" % day)).open("a") as fh:
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")

    # -- asset layout -----------------------------------------------------
    def _adir(self, asset: str) -> Path:
        return self.assets / asset

    def _revdir(self, asset: str) -> Path:
        return self._adir(asset) / "revisions"

    def _chandir(self, asset: str) -> Path:
        return self._adir(asset) / "channels"

    def asset_names(self) -> List[str]:
        if not self.assets.exists():
            return []
        return sorted(p.name for p in self.assets.iterdir() if p.is_dir())

    def revisions(self, asset: str) -> List[str]:
        d = self._revdir(asset)
        if not d.exists():
            return []
        return sorted(p.stem for p in d.glob("v*.usda"))

    def next_rev(self, asset: str) -> str:
        existing = self.revisions(asset)
        n = max((int(r[1:]) for r in existing), default=0) + 1
        return "v%03d" % n

    # -- revisions --------------------------------------------------------
    def write_revision(self, r: Revision) -> Path:
        self._revdir(r.asset).mkdir(parents=True, exist_ok=True)
        meta = json.dumps(asdict(r), separators=(",", ":"))
        if r.generator:
            plist = "".join(
                "    uniform double jitsd:param:%s = %s\n" % (k, v)
                for k, v in sorted((r.params or {}).items()))
            payload = ('    uniform string jitsd:generator = "%s"\n%s'
                       % (_esc(r.generator), plist))
        else:
            payload = ('    uniform int64 jitsd:payloadSize = %d\n'
                       '    prepend payload = @jitsd:obj/sha256:%s@\n' % (r.size, r.blob))
        body = f'''#usda 1.0
(
    customLayerData = {{
        string jitsd__revision = "{r.rev}"
        string jitsd__asset    = "{_esc(r.asset)}"
        string jitsd__parent   = "{r.parent or ""}"
        string jitsd__author   = "{_esc(r.author)}"
        string jitsd__created  = "{r.created}"
        string jitsd__message  = "{_esc(r.message)}"
        string jitsd__meta = """{meta}"""
    }}
)

def "{r.asset}" (
    prepend apiSchemas = ["JitsdGeneratorAPI"]
)
{{
{payload}}}
'''
        p = self._revdir(r.asset) / ("%s.usda" % r.rev)
        p.write_text(body)
        return p

    def read_revision(self, asset: str, rev: str) -> Revision:
        p = self._revdir(asset) / ("%s.usda" % rev)
        if not p.exists():
            raise KeyError("no such revision: %s %s" % (asset, rev))
        m = META_RE.search(p.read_text())
        if not m:
            raise IOError("revision %s/%s has no jitsd__meta block" % (asset, rev))
        return Revision(**json.loads(m.group(1)))

    # -- channels ---------------------------------------------------------
    def channels(self, asset: str) -> Dict[str, str]:
        d = self._chandir(asset)
        if not d.exists():
            return {}
        return {p.name: p.read_text().strip() for p in sorted(d.iterdir()) if p.is_file()}

    def set_channel(self, asset: str, channel: str, rev: str) -> None:
        """The one mutation in the system."""
        self._chandir(asset).mkdir(parents=True, exist_ok=True)
        prev = self.channels(asset).get(channel)
        (self._chandir(asset) / channel).write_text(rev + "\n")
        self.log_event("channel_move", asset=asset, channel=channel, frm=prev, to=rev)

    def resolve_ref(self, asset: str, ref: str) -> str:
        """Accept 'v012', '@approved', or 'approved'."""
        if ref.startswith("@"):
            ref = ref[1:]
        chans = self.channels(asset)
        if ref in chans:
            return chans[ref]
        if ref in self.revisions(asset):
            return ref
        raise KeyError("cannot resolve %r for asset %r" % (ref, asset))

    # -- baselines --------------------------------------------------------
    def baseline_numbers(self) -> List[str]:
        if not self.baselines_dir.exists():
            return []
        return sorted(p.stem for p in self.baselines_dir.glob("*.usda"))

    def next_baseline(self) -> str:
        existing = self.baseline_numbers()
        n = max((int(b) for b in existing), default=0) + 1
        return "%06d" % n

    def write_baseline(self, b: Baseline) -> Path:
        self.baselines_dir.mkdir(parents=True, exist_ok=True)
        meta = json.dumps(asdict(b), separators=(",", ":"))
        pins = "\n".join(
            '            string "%s" = "%s"' % (_esc(k), v) for k, v in sorted(b.pins.items())
        )
        body = f'''#usda 1.0
(
    customLayerData = {{
        string jitsd__baseline   = "{b.number}"
        string jitsd__label      = "{_esc(b.label)}"
        string jitsd__parent     = "{b.parent or ""}"
        string jitsd__cut        = "{b.cut}"
        string jitsd__cutBy      = "{_esc(b.cut_by)}"
        string jitsd__merkleRoot = "sha256:{b.merkle_root}"
        string jitsd__meta = """{meta}"""
    }}
)

over "World" (
    customData = {{
        dictionary jitsd__pins = {{
{pins}
        }}
    }}
)
'''
        p = self.baselines_dir / ("%s.usda" % b.number)
        p.write_text(body)
        return p

    def read_baseline(self, number: str) -> Baseline:
        p = self.baselines_dir / ("%s.usda" % number)
        if not p.exists():
            raise KeyError("no such baseline: %s" % number)
        m = META_RE.search(p.read_text())
        if not m:
            raise IOError("baseline %s has no jitsd__meta block" % number)
        return Baseline(**json.loads(m.group(1)))


class BreakingChange(Exception):
    def __init__(self, asset: str, rev: str, channel: str, violations: List[Violation]):
        self.asset, self.rev, self.channel, self.violations = asset, rev, channel, violations
        super().__init__("%s %s -> @%s is a breaking change" % (asset, rev, channel))


class Repo:
    """A jitsd working root: object store + ledger."""

    DIRNAME = ".jitsd"

    def __init__(self, root: Path):
        self.root = Path(root)
        self.dir = self.root / self.DIRNAME
        self.store = ObjectStore(self.dir / "objects")
        self.ledger = Ledger(self.dir / "ledger")

    @classmethod
    def find(cls, start: Optional[Path] = None) -> "Repo":
        cur = Path(start or Path.cwd()).resolve()
        for cand in [cur, *cur.parents]:
            if (cand / cls.DIRNAME).is_dir():
                return cls(cand)
        raise SystemExit("not a jitsd repository (no .jitsd found) -- run `jitsd init`")

    def exists(self) -> bool:
        return self.dir.is_dir()

    def init(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.store.init()
        self.ledger.init()

    # -- the save path ----------------------------------------------------
    def save(self, asset: str, path: Path, author: str, message: str = "",
             interface: Optional[Path] = None) -> Revision:
        data = Path(path).read_bytes()
        blob = self.store.put_bytes(data)
        chans = self.ledger.channels(asset)
        parent = chans.get("wip")

        iface_blob = None
        surface = None
        if interface is not None:
            text = Path(interface).read_text()
            surface = extract_text(text).to_dict()   # fails loudly on bad .usda
            iface_blob = self.store.put_bytes(text.encode())
        elif parent:
            # Carry the previous interface forward when only the payload moved.
            prev = self.ledger.read_revision(asset, parent)
            iface_blob, surface = prev.interface_blob, prev.surface

        if parent:
            prev = self.ledger.read_revision(asset, parent)
            if prev.blob == blob and prev.interface_blob == iface_blob:
                return prev  # nothing changed; do not mint a revision

        rev = Revision(
            asset=asset,
            rev=self.ledger.next_rev(asset),
            blob=blob,
            size=len(data),
            parent=parent,
            author=author,
            created=_now(),
            message=message,
            interface_blob=iface_blob,
            surface=surface,
        )
        self.ledger.write_revision(rev)
        self.ledger.set_channel(asset, "wip", rev.rev)
        self.ledger.log_event("save", asset=asset, rev=rev.rev, blob=blob, size=len(data))
        return rev

    def check_promotion(self, asset: str, ref: str, to: str) -> List[Violation]:
        """Compatibility of a candidate against what is currently on `to`.

        The gate from docs/03-versioning.md: compatibility is measured, not
        asserted. Nothing on the channel yet means nothing to break.
        """
        rev = self.ledger.resolve_ref(asset, ref)
        current = self.ledger.channels(asset).get(to)
        if not current or current == rev:
            return []
        old = Surface.from_dict(self.ledger.read_revision(asset, current).surface)
        new = Surface.from_dict(self.ledger.read_revision(asset, rev).surface)
        if not old:
            return []
        return check_compatibility(old, new)

    def declare(self, asset: str, generator: str, params: Optional[Dict],
                author: str, message: str = "") -> Revision:
        """Create a generator-backed revision.

        The contract surface is not authored here -- it is COMPUTED by the
        generator from its parameters, and recorded on the revision so
        resolution never has to call the generator to know what it offers.
        """
        from .generators import get as get_generator

        gen = get_generator(generator)
        bound = gen.bind_params(params)
        surface = gen.surface(bound).to_dict()

        chans = self.ledger.channels(asset)
        parent = chans.get("wip")
        if parent:
            prev = self.ledger.read_revision(asset, parent)
            if (prev.generator == generator and prev.params == bound
                    and prev.surface == surface):
                return prev

        rev = Revision(
            asset=asset, rev=self.ledger.next_rev(asset), blob=None, size=0,
            parent=parent, author=author, created=_now(), message=message,
            surface=surface, generator=generator, params=bound,
        )
        self.ledger.write_revision(rev)
        self.ledger.set_channel(asset, "wip", rev.rev)
        self.ledger.log_event("declare", asset=asset, rev=rev.rev, generator=generator)
        return rev

    def promote(self, asset: str, ref: str, to: str, force: bool = False) -> str:
        rev = self.ledger.resolve_ref(asset, ref)
        self.ledger.read_revision(asset, rev)  # existence check
        violations = self.check_promotion(asset, ref, to)
        if violations and not force:
            raise BreakingChange(asset, rev, to, violations)
        self.ledger.set_channel(asset, to, rev)
        self.ledger.log_event("promote", asset=asset, rev=rev, channel=to,
                              forced=bool(violations and force))
        return rev

    # -- contracts --------------------------------------------------------
    def surfaces(self, pins: Dict[str, str]) -> Dict[str, Surface]:
        out: Dict[str, Surface] = {}
        for asset, rev in pins.items():
            s = Surface.from_dict(self.ledger.read_revision(asset, rev).surface)
            if s:
                out[asset] = s
        return out

    def bind(self, baseline: Optional[str] = None, channel: str = "approved") -> Resolution:
        """Type-directed resolution across every pinned asset.

        No prim path crosses an asset boundary: a requirement names a contract,
        never a provider.
        """
        return resolve(self.surfaces(self.resolve(baseline=baseline, channel=channel)))

    # -- resolution -------------------------------------------------------
    def resolve(self, baseline: Optional[str] = None, channel: str = "approved") -> Dict[str, str]:
        """Pin every asset. A baseline is replayed; floating mints a new one."""
        if baseline:
            return dict(self.ledger.read_baseline(baseline).pins)
        pins: Dict[str, str] = {}
        for asset in self.ledger.asset_names():
            chans = self.ledger.channels(asset)
            rev = chans.get(channel) or chans.get("wip")
            if rev:
                pins[asset] = rev
        return pins

    def merkle_root(self, pins: Dict[str, str]) -> str:
        """Rung 1: a hash over the pinned revision blobs.

        Real subtree-level Merkle hashing (docs/06-storage.md) needs a prim
        hierarchy, which arrives with the resolver. This gives the same
        top-level property -- an identical world hashes identically -- but not
        yet O(changes) subtree diffs.
        """
        import hashlib

        h = hashlib.sha256()
        for asset, rev in sorted(pins.items()):
            r = self.ledger.read_revision(asset, rev)
            ident = r.blob or "%s|%s" % (r.generator, json.dumps(r.params, sort_keys=True))
            h.update(("%s\0%s\0%s\n" % (asset, rev, ident)).encode())
        return h.hexdigest()

    def cut_baseline(self, label: str = "", cut_by: str = "user",
                     channel: str = "approved") -> Baseline:
        pins = self.resolve(channel=channel)
        nums = self.ledger.baseline_numbers()
        b = Baseline(
            number=self.ledger.next_baseline(),
            label=label,
            parent=nums[-1] if nums else None,
            cut=_now(),
            cut_by=cut_by,
            pins=pins,
            merkle_root=self.merkle_root(pins),
        )
        self.ledger.write_baseline(b)
        self.ledger.log_event("baseline_cut", baseline=b.number, label=label,
                              merkle=b.merkle_root)
        return b

    def reachable_blobs(self) -> List[str]:
        """Everything a baseline pins, plus every current channel head."""
        keep = set()
        for num in self.ledger.baseline_numbers():
            for asset, rev in self.ledger.read_baseline(num).pins.items():
                try:
                    r = self.ledger.read_revision(asset, rev)
                except KeyError:
                    continue
                keep.update(b for b in (r.blob, r.interface_blob) if b)
        for asset in self.ledger.asset_names():
            for rev in self.ledger.channels(asset).values():
                try:
                    r = self.ledger.read_revision(asset, rev)
                except KeyError:
                    continue
                keep.update(b for b in (r.blob, r.interface_blob) if b)
        return sorted(keep)

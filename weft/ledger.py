"""Revisions, channels and baselines.

The three-layer model from docs/03-versioning.md:

  revisions   immutable, content-addressed. Every save makes one.
  channels    the ONLY mutable object in the system -- a pointer to a revision.
  baselines   immutable, named, complete resolution maps. The lockfile.

Revision and baseline files are real .usda layers, so they open in usdview and
diff as text. Rung 1 has no pxr dependency, so machine-readable state travels
in a compact JSON string inside customLayerData (`weft__meta`) which one regex
recovers. When pxr is available this is read properly through the USD API and
the shim goes away -- the file on disk does not change either way.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .contracts import Surface, Resolution, Violation, check_compatibility, extract_text, resolve
from .store import ObjectStore

META_RE = re.compile(r'string\s+weft__meta\s*=\s*"""(.*?)"""', re.DOTALL)

DEFAULT_CHANNELS = ("wip", "review", "approved")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _esc(s: str) -> str:
    """Escape for a single-quoted USD string.

    Newlines and tabs must be escaped too: a commit message containing one
    otherwise emits a revision layer that real USD refuses to parse, which
    breaks the module's central promise that these files open in usdview.
    """
    return (s.replace("\\", "\\\\")
             .replace('"', '\\"')
             .replace("\n", "\\n")
             .replace("\r", "\\r")
             .replace("\t", "\\t"))


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_text_atomic(path: Path, text: str) -> None:
    """Write durably: temp file, fsync, rename, fsync the directory.

    A plain write_text truncates first, so a crash mid-write leaves a
    zero-length file. For a channel pointer that means the channel is *gone*
    rather than stale, on an otherwise healthy repository.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp-%d" % os.getpid())
    try:
        with tmp.open("w") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


class RevisionExists(IOError):
    """A revision file already exists. Revisions are never overwritten."""


class ChannelRaced(IOError):
    """A channel moved under us between the check and the write."""


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
    # Which *function* produced this, not just which name was typed.
    # specs/revision-layer.usda has always specified weft:generatorVersion;
    # without it a baseline pins its inputs and not its function, so the same
    # coordinate can resolve to different geometry after a generator edit.
    generator_version: Optional[str] = None
    generator_hash: Optional[str] = None
    # Where the payload was read from. The blob is what the revision IS; the
    # source is where its relative references resolve from, which is what a
    # slice needs to follow `references`, `payload` and `material:binding`
    # edges on assets that declare no contracts -- i.e. every real USD asset.
    source: Optional[str] = None


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
                "    uniform double weft:param:%s = %s\n" % (k, v)
                for k, v in sorted((r.params or {}).items()))
            body_attrs = ('    uniform string weft:generator = "%s"\n%s'
                          % (_esc(r.generator), plist))
            prim_meta = ""
        else:
            body_attrs = "    uniform int64 weft:payloadSize = %d\n" % r.size
            # payload is prim METADATA -- it belongs in the ( ) block. Real USD
            # rejects it in the prim body.
            prim_meta = "\n    prepend payload = @weft:obj/sha256:%s@" % r.blob
        body = f'''#usda 1.0
(
    customLayerData = {{
        string weft__revision = "{r.rev}"
        string weft__asset    = "{_esc(r.asset)}"
        string weft__parent   = "{r.parent or ""}"
        string weft__author   = "{_esc(r.author)}"
        string weft__created  = "{r.created}"
        string weft__message  = "{_esc(r.message)}"
        string weft__meta = """{meta}"""
    }}
)

def "{r.asset}" (
    prepend apiSchemas = ["WeftGeneratorAPI"]{prim_meta}
)
{{
{body_attrs}}}
'''
        p = self._revdir(r.asset) / ("%s.usda" % r.rev)
        # O_EXCL, because a revision is immutable. next_rev() is a read of the
        # directory followed by a write, so two concurrent saves both compute
        # v039 and the second would otherwise silently replace the first --
        # destroying a revision the ledger has already promised never changes.
        try:
            fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            raise RevisionExists("revision %s/%s already exists" % (r.asset, r.rev))
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(body)
                fh.flush()
                os.fsync(fh.fileno())
        except BaseException:
            p.unlink(missing_ok=True)
            raise
        _fsync_dir(p.parent)
        return p

    def read_revision(self, asset: str, rev: str) -> Revision:
        p = self._revdir(asset) / ("%s.usda" % rev)
        if not p.exists():
            raise KeyError("no such revision: %s %s" % (asset, rev))
        m = META_RE.search(p.read_text())
        if not m:
            raise IOError("revision %s/%s has no weft__meta block" % (asset, rev))
        return Revision(**json.loads(m.group(1)))

    # -- channels ---------------------------------------------------------
    def channels(self, asset: str) -> Dict[str, str]:
        d = self._chandir(asset)
        if not d.exists():
            return {}
        return {p.name: p.read_text().strip() for p in sorted(d.iterdir()) if p.is_file()}

    def set_channel(self, asset: str, channel: str, rev: str,
                    expect: Optional[str] = "__any__") -> None:
        """The one mutation in the system, so it is the one that must be safe.

        Compare-and-swap: pass `expect` as the value the caller believes the
        channel currently holds, and the move is refused if it has changed.
        Without that, a promotion gate evaluates compatibility against one
        revision and then writes over whatever landed in the meantime -- the
        "compatibility is measured" guarantee holds only up to the race.

        Passing expect=None asserts the channel does not exist yet. The default
        skips the check, for callers that genuinely want last-writer-wins.
        """
        d = self._chandir(asset)
        d.mkdir(parents=True, exist_ok=True)
        target = d / channel
        prev = self.channels(asset).get(channel)

        if expect != "__any__" and prev != expect:
            raise ChannelRaced(
                "%s@%s is at %s, expected %s -- refusing to move it"
                % (asset, channel, prev or "(unset)", expect or "(unset)"))

        _write_text_atomic(target, rev + "\n")
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
        string weft__baseline   = "{b.number}"
        string weft__label      = "{_esc(b.label)}"
        string weft__parent     = "{b.parent or ""}"
        string weft__cut        = "{b.cut}"
        string weft__cutBy      = "{_esc(b.cut_by)}"
        string weft__merkleRoot = "sha256:{b.merkle_root}"
        string weft__meta = """{meta}"""
    }}
)

over "World" (
    customData = {{
        dictionary weft__pins = {{
{pins}
        }}
    }}
)
{{
}}
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
            raise IOError("baseline %s has no weft__meta block" % number)
        return Baseline(**json.loads(m.group(1)))


class BreakingChange(Exception):
    def __init__(self, asset: str, rev: str, channel: str, violations: List[Violation]):
        self.asset, self.rev, self.channel, self.violations = asset, rev, channel, violations
        super().__init__("%s %s -> @%s is a breaking change" % (asset, rev, channel))


class Repo:
    """A weft working root: object store + ledger."""

    DIRNAME = ".weft"

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
        raise SystemExit("not a weft repository (no .weft found) -- run `weft init`")

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
            source=os.path.normpath(os.path.abspath(str(path))),
        )
        self.ledger.write_revision(rev)
        self.ledger.set_channel(asset, "wip", rev.rev)
        self.ledger.log_event("save", asset=asset, rev=rev.rev, blob=blob, size=len(data))
        return rev

    def check_promotion(self, asset: str, ref: str, to: str,
                        view: Optional[List[str]] = None) -> List:
        """Compatibility of a candidate against what is currently on `to`.

        Two halves, both from docs/03-versioning.md:

          1. the provider against its own promise -- check_compatibility();
          2. every consumer bound to it, re-evaluated with the candidate
             pinned and its manifest diffed -- reeval.reevaluate().

        The second is what makes compatibility measured rather than asserted.
        Nothing on the channel yet means nothing to break.
        """
        rev = self.ledger.resolve_ref(asset, ref)
        current = self.ledger.channels(asset).get(to)
        if not current or current == rev:
            return []
        old = Surface.from_dict(self.ledger.read_revision(asset, current).surface)
        new = Surface.from_dict(self.ledger.read_revision(asset, rev).surface)
        if not old:
            return []
        out: List = list(check_compatibility(old, new))
        out.extend(self.reevaluate(asset, rev, to, view).violations)
        return out

    def exemplar_surfaces(self, pins: Dict[str, str]) -> Dict[str, Surface]:
        """Every pinned asset's surface, plus one per declared exemplar.

        A generator that declares exemplars contributes an extra consumer
        surface per exemplar, keyed `asset#name`, computed at those parameters.
        A constant contributes one: its stored surface. Offers on exemplar
        surfaces are hidden so an exemplar never provides for anyone.
        """
        from .generators import get as get_generator

        out: Dict[str, Surface] = {}
        for asset, rev in pins.items():
            r = self.ledger.read_revision(asset, rev)
            s = Surface.from_dict(r.surface)
            if s:
                out[asset] = s
            if not r.generator:
                continue
            try:
                gen = get_generator(r.generator)
            except KeyError:
                continue
            for i, params in enumerate(gen.exemplars or ()):
                bound = gen.bind_params({**(r.params or {}), **params})
                es = gen.surface(bound)
                for o in es.offers:
                    o.public = False
                out["%s#%d" % (asset, i)] = es
        return out

    def reevaluate(self, asset: str, rev: str, channel: str = "approved",
                   view: Optional[List[str]] = None):
        """Re-evaluate every consumer of `asset` with `rev` pinned in its place.

        Standalone so slices can ask the same question -- "what does this
        candidate break, inside and outside my slice" -- without promoting.
        """
        from .reeval import reevaluate

        pins_old = self.resolve(channel=channel)
        if asset not in pins_old:
            from .reeval import ReEvaluation
            return ReEvaluation(consumers=[], violations=[], proof="")
        pins_new = dict(pins_old)
        pins_new[asset] = rev
        return reevaluate(self.exemplar_surfaces(pins_old),
                          self.exemplar_surfaces(pins_new), {asset}, view)

    def declare(self, asset: str, generator: str, params: Optional[Dict],
                author: str, message: str = "") -> Revision:
        """Create a generator-backed revision.

        The contract surface is not authored here -- it is COMPUTED by the
        generator from its parameters, and recorded on the revision so
        resolution never has to call the generator to know what it offers.
        """
        from .generators import code_hash, get as get_generator, pin as pin_generator

        gen = get_generator(generator)
        pinned = pin_generator(generator)   # never store the bare name
        ghash = code_hash(gen)
        bound = gen.bind_params(params)
        surface = gen.surface(bound).to_dict()

        chans = self.ledger.channels(asset)
        parent = chans.get("wip")
        if parent:
            prev = self.ledger.read_revision(asset, parent)
            if (prev.generator == pinned and prev.params == bound
                    and prev.surface == surface
                    and prev.generator_hash == ghash):
                return prev

        rev = Revision(
            asset=asset, rev=self.ledger.next_rev(asset), blob=None, size=0,
            parent=parent, author=author, created=_now(), message=message,
            surface=surface, generator=pinned, params=bound,
            generator_version=gen.version, generator_hash=ghash,
        )
        self.ledger.write_revision(rev)
        self.ledger.set_channel(asset, "wip", rev.rev)
        self.ledger.log_event("declare", asset=asset, rev=rev.rev, generator=pinned)
        return rev

    def promote(self, asset: str, ref: str, to: str,
                force: bool = False) -> Tuple[str, List[Violation]]:
        """Move a channel pointer, gated on measured compatibility.

        Returns (revision, violations-that-were-forced-over). The gate is
        evaluated against the revision the channel held when we read it, and
        the write refuses if it moved in between -- otherwise "compatibility is
        measured" holds only until two people promote at once.
        """
        rev = self.ledger.resolve_ref(asset, ref)
        self.ledger.read_revision(asset, rev)  # existence check
        current = self.ledger.channels(asset).get(to)
        violations = self.check_promotion(asset, ref, to)
        if violations and not force:
            raise BreakingChange(asset, rev, to, violations)
        self.ledger.set_channel(asset, to, rev, expect=current)
        self.ledger.log_event("promote", asset=asset, rev=rev, channel=to,
                              forced=bool(violations and force))
        return rev, violations

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
        """Rung 1: a hash over the pinned revisions.

        Real subtree-level Merkle hashing (docs/06-storage.md) needs a prim
        hierarchy, which arrives with the resolver. This gives the same
        top-level property -- an identical world hashes identically -- but not
        yet O(changes) subtree diffs.

        For a generator-backed revision the identity includes the generator's
        *code hash*, not only its name and parameters. Hashing the name alone
        means a rewritten generator produces an identical root, so `drift`
        reports nothing about the one change most likely to alter every
        downstream projection.
        """
        import hashlib

        h = hashlib.sha256()
        for asset, rev in sorted(pins.items()):
            r = self.ledger.read_revision(asset, rev)
            if r.blob:
                ident = r.blob
            else:
                ident = "%s|%s|%s" % (
                    r.generator,
                    r.generator_hash or "unpinned",
                    json.dumps(r.params, sort_keys=True))
            h.update(("%s\0%s\0%s\n" % (asset, rev, ident)).encode())
        return h.hexdigest()

    def stale_generators(self) -> List[Dict[str, str]]:
        """Revisions whose generator no longer matches the code they recorded.

        A pinned baseline is only reproducible if the function it names still
        behaves the same way. This is the check that says otherwise.
        """
        from .generators import code_hash, get as get_generator

        out: List[Dict[str, str]] = []
        for asset in self.ledger.asset_names():
            for rev in self.ledger.revisions(asset):
                try:
                    r = self.ledger.read_revision(asset, rev)
                except (KeyError, IOError):
                    continue
                if not r.generator:
                    continue
                try:
                    gen = get_generator(r.generator)
                except KeyError:
                    out.append({"asset": asset, "rev": rev,
                                "generator": r.generator, "why": "not registered"})
                    continue
                if r.generator_hash is None:
                    out.append({"asset": asset, "rev": rev,
                                "generator": r.generator, "why": "no code hash recorded"})
                elif code_hash(gen) != r.generator_hash:
                    out.append({"asset": asset, "rev": rev,
                                "generator": r.generator, "why": "code changed"})
        return out

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

    def reachable_blobs(self, prune_history: bool = False) -> List[str]:
        """Blobs that must survive a gc.

        By default this is *every revision the ledger still lists*, not just
        the ones a channel or baseline currently points at. Rooting only at
        heads and pins deletes the payload of every intermediate revision while
        `weft log` goes on listing it -- which silently destroys exactly the
        rung-1 features that justify the tool: instant rollback, named
        checkpoints, and diff between any two revisions.

        Git keeps refs *and history*; so does this. `prune_history=True` asks
        for the narrow behaviour explicitly, for a caller that really does want
        unreferenced history collected.
        """
        keep = set()

        def take(asset: str, rev: str) -> None:
            try:
                r = self.ledger.read_revision(asset, rev)
            except (KeyError, IOError):
                return
            keep.update(b for b in (r.blob, r.interface_blob) if b)

        for num in self.ledger.baseline_numbers():
            for asset, rev in self.ledger.read_baseline(num).pins.items():
                take(asset, rev)

        for asset in self.ledger.asset_names():
            if prune_history:
                for rev in self.ledger.channels(asset).values():
                    take(asset, rev)
            else:
                for rev in self.ledger.revisions(asset):
                    take(asset, rev)

        return sorted(keep)

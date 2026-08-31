"""Content-addressed object store.

Two levels, because they answer different questions:

  chunks/   deduplicated variable-size pieces. Physical bytes on disk.
  blobs/    a manifest per stored file: its size and its chunk list.

A blob's id is the sha256 of the whole file, so identical files collapse at the
blob level and near-identical files collapse at the chunk level. Nothing here is
ever mutated or overwritten -- writes are atomic renames, and a chunk that
already exists is simply not written again.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from . import chunker
from .chunker import chunk

READ_BUF = 8 * 1024 * 1024


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            b = fh.read(READ_BUF)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class Stats:
    blobs: int
    logical_bytes: int
    chunks: int
    physical_bytes: int

    @property
    def ratio(self) -> float:
        return self.logical_bytes / self.physical_bytes if self.physical_bytes else 1.0


class ObjectStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.chunks = self.root / "chunks"
        self.blobs = self.root / "blobs"
        self.config_path = self.root / "config.json"
        self._params: Optional[Dict[str, int]] = None

    def init(self) -> None:
        self.chunks.mkdir(parents=True, exist_ok=True)
        self.blobs.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            self.config_path.write_text(json.dumps(self.default_params(), indent=2) + "\n")

    # -- chunker parameters ----------------------------------------------
    @staticmethod
    def default_params() -> Dict[str, int]:
        return {"min_size": chunker.MIN_SIZE,
                "avg_size": chunker.AVG_SIZE,
                "max_size": chunker.MAX_SIZE}

    def params(self) -> Dict[str, int]:
        """Chunker settings this store was created with.

        Recorded because they are not a tuning knob after the fact: different
        boundaries mean nothing new dedups against anything already stored, and
        the damage is silent -- the store keeps working, it just stops saving
        space. A store is therefore self-describing, and re-chunking is an
        explicit migration rather than an accident.
        """
        if self._params is None:
            if self.config_path.exists():
                self._params = json.loads(self.config_path.read_text())
            else:
                self._params = self.default_params()
        return self._params

    # -- paths ------------------------------------------------------------
    def _chunk_path(self, digest: str) -> Path:
        return self.chunks / digest[:2] / digest[2:4] / digest

    def _blob_path(self, digest: str) -> Path:
        return self.blobs / digest[:2] / (digest + ".json")

    # -- writes -----------------------------------------------------------
    def _write_atomic(self, path: Path, data: bytes) -> bool:
        """Returns True if the object was newly written, False if it existed."""
        if path.exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp-%d" % os.getpid())
        tmp.write_bytes(data)
        try:
            os.replace(tmp, path)
        except OSError:
            tmp.unlink(missing_ok=True)
            raise
        return True

    def put_bytes(self, data: bytes) -> str:
        """Store one payload. Returns its blob id."""
        blob_id = sha256_bytes(data)
        bp = self._blob_path(blob_id)
        if bp.exists():
            return blob_id

        chunk_ids: List[str] = []
        for piece in chunk(data, **self.params()):
            cid = sha256_bytes(piece)
            chunk_ids.append(cid)
            self._write_atomic(self._chunk_path(cid), piece)

        manifest = json.dumps(
            {"size": len(data), "chunks": chunk_ids}, separators=(",", ":")
        ).encode()
        self._write_atomic(bp, manifest)
        return blob_id

    def put_file(self, path: Path) -> str:
        return self.put_bytes(Path(path).read_bytes())

    # -- reads ------------------------------------------------------------
    def has_blob(self, blob_id: str) -> bool:
        return self._blob_path(blob_id).exists()

    def manifest(self, blob_id: str) -> Dict:
        bp = self._blob_path(blob_id)
        if not bp.exists():
            raise KeyError("no such blob: %s" % blob_id)
        return json.loads(bp.read_text())

    def get_bytes(self, blob_id: str) -> bytes:
        man = self.manifest(blob_id)
        out = bytearray()
        for cid in man["chunks"]:
            out += self._chunk_path(cid).read_bytes()
        if len(out) != man["size"]:
            raise IOError("blob %s: size mismatch on reassembly" % blob_id)
        return bytes(out)

    def checkout(self, blob_id: str, dest: Path) -> None:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        man = self.manifest(blob_id)
        with dest.open("wb") as fh:
            for cid in man["chunks"]:
                fh.write(self._chunk_path(cid).read_bytes())

    # -- introspection ----------------------------------------------------
    def iter_blob_ids(self) -> Iterable[str]:
        for p in self.blobs.rglob("*.json"):
            yield p.stem

    def stats(self) -> Stats:
        logical = 0
        nblobs = 0
        for bid in self.iter_blob_ids():
            logical += self.manifest(bid)["size"]
            nblobs += 1
        physical = 0
        nchunks = 0
        for p in self.chunks.rglob("*"):
            if p.is_file() and not p.name.endswith(".tmp"):
                physical += p.stat().st_size
                nchunks += 1
        return Stats(nblobs, logical, nchunks, physical)

    # -- gc ---------------------------------------------------------------
    def gc(self, reachable_blob_ids: Iterable[str]) -> Dict[str, int]:
        """Drop blobs and chunks not reachable from the given roots."""
        keep_blobs = set(reachable_blob_ids)
        keep_chunks = set()
        dropped_blobs = 0
        for bid in list(self.iter_blob_ids()):
            if bid in keep_blobs:
                keep_chunks.update(self.manifest(bid)["chunks"])
            else:
                self._blob_path(bid).unlink()
                dropped_blobs += 1
        dropped_chunks = 0
        freed = 0
        for p in list(self.chunks.rglob("*")):
            if p.is_file() and p.name not in keep_chunks:
                freed += p.stat().st_size
                p.unlink()
                dropped_chunks += 1
        return {"blobs": dropped_blobs, "chunks": dropped_chunks, "bytes": freed}

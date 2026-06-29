"""Core :class:`CheckpointStore` — reversible, deduplicated checkpoint timeline."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from typing import Dict, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
import knotcore  # noqa: E402

from .pack import pack_path, unpack_to  # noqa: E402

DEFAULT_DIR = ".checkpointtime"
DEFAULT_CHUNK_SIZE = 1024  # small chunks -> maximal dedup on small deltas


class CheckpointError(Exception):
    """Raised for invalid checkpoint ids, corrupt state, or restore failures."""


class CheckpointStore:
    """A disk-backed, content-addressed checkpoint timeline.

    Parameters
    ----------
    root:
        Directory the store lives in (created if absent). Defaults to
        ``./.checkpointtime``.
    chunk_size:
        Chunk size for the underlying dedup store. Smaller chunks dedup small
        deltas more aggressively at the cost of more bookkeeping.

    The store persists everything to disk and reloads faithfully: re-opening the
    same ``root`` in a fresh process restores the full timeline, HEAD and
    branches.
    """

    def __init__(self, root: str = DEFAULT_DIR, chunk_size: int = DEFAULT_CHUNK_SIZE):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        self._store = knotcore.PersistentKnotStore(self.root, chunk_size=chunk_size)
        self._meta_path = os.path.join(self.root, "meta.json")
        # in-memory model, mirrored to meta.json
        self.checkpoints = {}  # type: Dict[str, dict]
        self.order = []        # type: List[str]   chronological insertion order
        self.head = None       # type: Optional[str]
        self.branch_name = "main"
        self.branches = {}     # type: Dict[str, str]  name -> checkpoint id (tip)
        self._log = knotcore.ProvenanceLog(route_depth=8)
        self._load()

    # ------------------------------------------------------------------ public
    def snapshot(self, state: bytes, label: str = "") -> str:
        """Store ``state`` content-addressed and append it to the timeline.

        Returns a short checkpoint id. Identical chunks shared with earlier
        checkpoints are stored only once by the underlying dedup engine.
        """
        if not isinstance(state, (bytes, bytearray)):
            raise TypeError("state must be bytes")
        state = bytes(state)
        cid = self._make_id(state)
        manifest = self._store.put(state, name="cp-" + cid)
        self._store.save_manifest(manifest, name="cp-" + cid)

        step = self._log.add(cid)
        record = {
            "id": cid,
            "label": label,
            "time": time.time(),
            "size": len(state),
            "fingerprint": step.fingerprint_after,
            "parent": self.head,
            "branch": self.branch_name,
        }
        self.checkpoints[cid] = record
        self.order.append(cid)
        self.head = cid
        self.branches[self.branch_name] = cid
        self._save()
        return cid

    def snapshot_path(self, path: str, label: str = "") -> str:
        """Pack a file or directory deterministically, then snapshot it."""
        blob = pack_path(path)
        if not label:
            label = os.path.basename(os.path.normpath(path))
        return self.snapshot(blob, label=label)

    def restore(self, checkpoint_id: str) -> bytes:
        """Return the exact bytes stored at ``checkpoint_id``."""
        self._require(checkpoint_id)
        manifest = self._store.load_manifest("cp-" + checkpoint_id)
        if not self._store.verify(manifest):
            raise CheckpointError("checkpoint %s failed integrity check" % checkpoint_id)
        return self._store.get(manifest)

    def restore_path(self, checkpoint_id: str, dest: str) -> None:
        """Restore a checkpoint and unpack it (file or dir tree) to ``dest``."""
        unpack_to(self.restore(checkpoint_id), dest)

    def timeline(self) -> List[dict]:
        """Return checkpoints in chronological order as light dicts."""
        return [
            {
                "id": c["id"],
                "label": c["label"],
                "time": c["time"],
                "size": c["size"],
                "fingerprint": c["fingerprint"],
                "branch": c["branch"],
            }
            for c in (self.checkpoints[i] for i in self.order)
        ]

    def rewind(self, checkpoint_id: str) -> str:
        """Move HEAD back to an earlier checkpoint (reversible — no data lost)."""
        self._require(checkpoint_id)
        self.head = checkpoint_id
        self.branches[self.branch_name] = checkpoint_id
        self._save()
        return self.head

    def branch(self, checkpoint_id: str, name: str) -> str:
        """Fork a new named timeline whose tip starts at ``checkpoint_id``."""
        self._require(checkpoint_id)
        if not name or name == "main":
            raise CheckpointError("branch name must be non-empty and not 'main'")
        if name in self.branches:
            raise CheckpointError("branch %r already exists" % name)
        self.branches[name] = checkpoint_id
        self.branch_name = name
        self.head = checkpoint_id
        self._save()
        return name

    def stats(self) -> dict:
        """Return logical vs physical byte usage and the dedup ratio."""
        logical = sum(c["size"] for c in self.checkpoints.values())
        physical = self._store.bytes_on_disk()
        ratio = (float(logical) / physical) if physical else 0.0
        return {
            "logical_bytes": logical,
            "physical_bytes_on_disk": physical,
            "dedup_ratio": ratio,
            "checkpoints": len(self.checkpoints),
        }

    # ----------------------------------------------------------------- helpers
    def _make_id(self, state: bytes) -> str:
        h = hashlib.sha256()
        h.update(state)
        h.update(str(len(self.order)).encode())  # disambiguate identical states
        return h.hexdigest()[:12]

    def _require(self, checkpoint_id: str) -> None:
        if checkpoint_id not in self.checkpoints:
            raise CheckpointError("unknown checkpoint id: %r" % checkpoint_id)

    def _save(self) -> None:
        meta = {
            "checkpoints": self.checkpoints,
            "order": self.order,
            "head": self.head,
            "branch_name": self.branch_name,
            "branches": self.branches,
        }
        tmp = self._meta_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2, sort_keys=True)
        os.replace(tmp, self._meta_path)

    def _load(self) -> None:
        if not os.path.exists(self._meta_path):
            return
        with open(self._meta_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
        self.checkpoints = meta.get("checkpoints", {})
        self.order = meta.get("order", [])
        self.head = meta.get("head")
        self.branch_name = meta.get("branch_name", "main")
        self.branches = meta.get("branches", {})
        # rebuild the reversible provenance chain in recorded order
        self._log = knotcore.ProvenanceLog(route_depth=8)
        for cid in self.order:
            self._log.add(cid)

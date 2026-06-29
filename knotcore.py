"""
knotcore — the single public entry point to the KNOTstore engine.

Every downloadable app (KnotVault, PrefixForge, DriftLedger, CheckpointTime)
imports from here, so the engine's flat module layout under ``knotstore/`` is an
implementation detail no app has to know about.

It re-exports the engine's public API and adds ``PersistentKnotStore`` — a
disk-backed, write-through store so content survives across process runs (the
base ``KnotStore`` keeps its backend in memory only).

Stdlib only. Python 3.8+.
"""
from __future__ import annotations

import os
import sys

# --- make the engine's flat modules importable, wherever knotcore lives -------
_ENGINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knotstore")
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

# --- re-export the engine's public surface ------------------------------------
from knotstore import KnotStore, Manifest, TinyPointer            # noqa: E402
from codec import encode_manifest, decode_manifest, size_report    # noqa: E402
from signature import simhash64, shard_of, hamming                 # noqa: E402
from cube import MacroCube                                         # noqa: E402
from provenance import ProvenanceLog, Step                         # noqa: E402

__all__ = [
    "KnotStore", "Manifest", "TinyPointer",
    "encode_manifest", "decode_manifest", "size_report",
    "simhash64", "shard_of", "hamming",
    "MacroCube", "ProvenanceLog", "Step",
    "PersistentKnotStore",
]


class _DiskBackend(dict):
    """A dict that mirrors every write to a content-addressed file on disk and
    repopulates itself from disk on construction. Because ``KnotStore`` only
    touches its backend through ``dict`` ops, this gives persistence for free
    with no engine changes."""

    def __init__(self, objects_dir: str):
        super().__init__()
        self._dir = objects_dir
        os.makedirs(self._dir, exist_ok=True)
        for name in os.listdir(self._dir):
            path = os.path.join(self._dir, name)
            if os.path.isfile(path):
                with open(path, "rb") as fh:
                    super().__setitem__(name, fh.read())

    def __setitem__(self, key: str, value: bytes) -> None:
        super().__setitem__(key, value)
        # addresses are hex strings -> filesystem-safe; write atomically
        path = os.path.join(self._dir, key)
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(value)
        os.replace(tmp, path)


class PersistentKnotStore(KnotStore):
    """A ``KnotStore`` whose deduplicated chunk backend lives on disk under
    ``root/objects`` and whose manifests are saved as the compact binary
    (1-byte-pointer) format under ``root/manifests``.

    Example
    -------
    >>> store = PersistentKnotStore("/tmp/myvault")
    >>> m = store.put(b"hello world", name="greeting")
    >>> store.save_manifest(m)
    >>> store.get(store.load_manifest("greeting")) == b"hello world"
    True
    """

    def __init__(self, root: str, **kwargs):
        super().__init__(**kwargs)
        self.root = os.path.abspath(root)
        self._objects_dir = os.path.join(self.root, "objects")
        self._manifests_dir = os.path.join(self.root, "manifests")
        os.makedirs(self._manifests_dir, exist_ok=True)
        self.backend = _DiskBackend(self._objects_dir)

    # --- manifest persistence (binary, compact) -------------------------------
    def manifest_path(self, name: str) -> str:
        safe = name.replace(os.sep, "_")
        return os.path.join(self._manifests_dir, safe + ".knotm")

    def save_manifest(self, manifest: Manifest, name: str = None) -> str:
        path = self.manifest_path(name or manifest.name)
        with open(path, "wb") as fh:
            fh.write(encode_manifest(manifest))
        return path

    def load_manifest(self, name: str) -> Manifest:
        path = self.manifest_path(name)
        with open(path, "rb") as fh:
            return decode_manifest(fh.read())

    def list_manifests(self):
        if not os.path.isdir(self._manifests_dir):
            return []
        return sorted(
            f[:-6] for f in os.listdir(self._manifests_dir) if f.endswith(".knotm")
        )

    def bytes_on_disk(self) -> int:
        total = 0
        for d in (self._objects_dir, self._manifests_dir):
            for n in os.listdir(d):
                p = os.path.join(d, n)
                if os.path.isfile(p):
                    total += os.path.getsize(p)
        return total


if __name__ == "__main__":
    import tempfile, shutil
    tmp = tempfile.mkdtemp()
    try:
        s = PersistentKnotStore(tmp, chunk_size=64)
        m = s.put(b"the quick brown fox " * 50, name="demo")
        s.save_manifest(m)
        # fresh instance proves it survives process-like reload
        s2 = PersistentKnotStore(tmp, chunk_size=64)
        assert s2.get(s2.load_manifest("demo")) == b"the quick brown fox " * 50
        assert s2.verify(s2.load_manifest("demo"))
        print("knotcore PersistentKnotStore: PASS  (objects+manifests survive reload)")
    finally:
        shutil.rmtree(tmp)

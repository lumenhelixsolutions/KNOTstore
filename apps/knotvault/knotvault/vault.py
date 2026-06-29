"""Core archiver for KnotVault.

A :class:`Vault` is a directory on disk that holds a content-addressed,
deduplicated object store (provided by the KNOTstore engine), the per-file
binary manifests, and a small JSON index describing every archive.

Each archived *file* becomes one engine manifest. An *archive* is a named
collection of files (e.g. the recursive contents of a directory). The archive's
overall integrity is a Merkle root computed over the per-file root digests, so a
single 64-hex-char string proves the integrity of the whole archive.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Optional

# --- engine bootstrap: knotcore lives at the repo root, not pip-installed -----
# This module is apps/knotvault/knotvault/vault.py, so the repo root (which holds
# knotcore.py) is three directories up. We search a couple of candidate roots so
# the import works whether KnotVault is run in-place, via PYTHONPATH, or pipx.
def _bootstrap_knotcore():
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.abspath(os.path.join(here, "..", "..", "..")),  # repo root
        os.path.abspath(os.path.join(here, "..", "..")),        # fallback
    ]
    for c in candidates:
        if os.path.isfile(os.path.join(c, "knotcore.py")):
            if c not in sys.path:
                sys.path.insert(0, c)
            return
    # Last resort: let the normal import machinery try (e.g. installed on path).


_bootstrap_knotcore()
import knotcore  # noqa: E402


class VaultError(Exception):
    """Base class for all expected, user-facing vault errors."""


class TamperError(VaultError):
    """Raised when verification detects corruption or tampering.

    Attributes:
        archive: name of the archive being verified.
        relpath: the file within the archive whose integrity failed.
        detail:  human-readable explanation from the engine.
    """

    def __init__(self, archive: str, relpath: str, detail: str):
        self.archive = archive
        self.relpath = relpath
        self.detail = detail
        super().__init__(
            "tamper/corruption detected in archive {!r}: file {!r}: {}".format(
                archive, relpath, detail
            )
        )


class ArchiveEntry:
    """One file inside an archive.

    Wraps the index record: the file's relative path, the engine manifest name
    that reconstructs it, its byte size, and its Merkle root digest.
    """

    __slots__ = ("relpath", "manifest_name", "size", "root_digest")

    def __init__(self, relpath: str, manifest_name: str, size: int, root_digest: str):
        self.relpath = relpath
        self.manifest_name = manifest_name
        self.size = size
        self.root_digest = root_digest

    def to_dict(self) -> Dict[str, object]:
        return {
            "relpath": self.relpath,
            "manifest_name": self.manifest_name,
            "size": self.size,
            "root_digest": self.root_digest,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, object]) -> "ArchiveEntry":
        return cls(
            relpath=str(d["relpath"]),
            manifest_name=str(d["manifest_name"]),
            size=int(d["size"]),
            root_digest=str(d["root_digest"]),
        )


class AddResult:
    """Summary returned by :meth:`Vault.add`."""

    __slots__ = ("name", "files", "input_bytes", "bytes_on_disk",
                 "dedup_savings_pct", "root_digest")

    def __init__(self, name, files, input_bytes, bytes_on_disk,
                 dedup_savings_pct, root_digest):
        self.name = name
        self.files = files
        self.input_bytes = input_bytes
        self.bytes_on_disk = bytes_on_disk
        self.dedup_savings_pct = dedup_savings_pct
        self.root_digest = root_digest


def _safe_token(text: str) -> str:
    """Make a string safe to use as a filesystem manifest name component."""
    out = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        else:
            out.append("_")
    token = "".join(out).strip("._") or "x"
    return token


class Vault:
    """A tamper-evident, deduplicating archive store backed by KNOTstore.

    Parameters
    ----------
    root:
        Directory for the vault. Created if absent. Defaults to ``./.knotvault``.
    chunk_size:
        Engine chunk size in bytes. Smaller chunks dedup more aggressively at the
        cost of more pointers; the default mirrors the engine default.
    """

    INDEX_NAME = "index.json"

    def __init__(self, root: str = "./.knotvault", chunk_size: int = 4096):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        self.store = knotcore.PersistentKnotStore(
            self.root, chunk_size=chunk_size, placement="content"
        )
        self._index_path = os.path.join(self.root, self.INDEX_NAME)
        self._index: Dict[str, List[ArchiveEntry]] = self._load_index()

    # ------------------------------------------------------------------ index
    def _load_index(self) -> Dict[str, List[ArchiveEntry]]:
        if not os.path.exists(self._index_path):
            return {}
        try:
            with open(self._index_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError) as exc:
            raise VaultError("corrupt vault index at {}: {}".format(self._index_path, exc))
        index: Dict[str, List[ArchiveEntry]] = {}
        try:
            for name, entries in raw.items():
                index[name] = [ArchiveEntry.from_dict(e) for e in entries]
        except (KeyError, TypeError, ValueError) as exc:
            raise VaultError("malformed vault index: {}".format(exc))
        return index

    def _save_index(self) -> None:
        serializable = {
            name: [e.to_dict() for e in entries]
            for name, entries in self._index.items()
        }
        tmp = self._index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(serializable, fh, indent=2, sort_keys=True)
        os.replace(tmp, self._index_path)

    def archives(self) -> List[str]:
        """Names of all archives in this vault, sorted."""
        return sorted(self._index)

    def entries(self, name: str) -> List[ArchiveEntry]:
        """Entries of one archive, or raise if it does not exist."""
        if name not in self._index:
            raise VaultError("no such archive: {!r}".format(name))
        return list(self._index[name])

    # ------------------------------------------------------------- file walk
    @staticmethod
    def _collect(paths: List[str]) -> List[tuple]:
        """Expand the given paths into a list of (abs_file_path, relpath).

        Files keep their basename as relpath. Directories are recursed and each
        file's relpath is preserved relative to the directory's parent (so the
        top-level directory name is included).
        """
        collected: List[tuple] = []
        for raw in paths:
            p = os.path.abspath(raw)
            if not os.path.exists(p):
                raise VaultError("path does not exist: {}".format(raw))
            if os.path.isfile(p):
                collected.append((p, os.path.basename(p)))
            elif os.path.isdir(p):
                base = os.path.dirname(p.rstrip(os.sep))
                for dirpath, dirnames, filenames in os.walk(p):
                    dirnames.sort()
                    for fn in sorted(filenames):
                        fp = os.path.join(dirpath, fn)
                        if not os.path.isfile(fp):
                            continue  # skip symlinks-to-dir, fifos, etc.
                        rel = os.path.relpath(fp, base)
                        collected.append((fp, rel))
            else:
                raise VaultError("not a regular file or directory: {}".format(raw))
        if not collected:
            raise VaultError("nothing to archive (no regular files found)")
        return collected

    # -------------------------------------------------------------------- add
    def add(self, paths: List[str], name: Optional[str] = None) -> AddResult:
        """Archive the given files/directories under archive ``name``.

        Returns an :class:`AddResult` with byte/dedup/root stats.
        """
        files = self._collect(paths)
        if name is None:
            # Derive a default name from the first path.
            name = _safe_token(os.path.basename(os.path.abspath(paths[0]).rstrip(os.sep)))
        if name in self._index:
            raise VaultError(
                "archive {!r} already exists (choose another --name)".format(name)
            )

        entries: List[ArchiveEntry] = []
        input_bytes = 0
        # Use the relpath in the manifest name so files stay distinguishable.
        for fp, rel in files:
            try:
                with open(fp, "rb") as fh:
                    data = fh.read()
            except OSError as exc:
                raise VaultError("cannot read {}: {}".format(fp, exc))
            manifest_name = "{}__{}".format(_safe_token(name), _safe_token(rel))
            manifest = self.store.put(data, name=manifest_name)
            self.store.save_manifest(manifest, name=manifest_name)
            entries.append(ArchiveEntry(
                relpath=rel,
                manifest_name=manifest_name,
                size=manifest.total_size,
                root_digest=manifest.root_digest,
            ))
            input_bytes += manifest.total_size

        self._index[name] = entries
        self._save_index()

        bytes_on_disk = self.store.bytes_on_disk()
        savings = 0.0
        if input_bytes > 0:
            savings = max(0.0, (1.0 - bytes_on_disk / input_bytes) * 100.0)
        return AddResult(
            name=name,
            files=len(entries),
            input_bytes=input_bytes,
            bytes_on_disk=bytes_on_disk,
            dedup_savings_pct=savings,
            root_digest=self.archive_root(name),
        )

    # ----------------------------------------------------------------- roots
    def archive_root(self, name: str) -> str:
        """Merkle root over the per-file root digests of an archive."""
        entries = self.entries(name)
        leaves = [e.root_digest for e in entries]
        return knotcore.KnotStore.merkle_root(leaves)

    # ------------------------------------------------------------- resync
    def _resync_from_disk(self) -> None:
        """Reload the chunk backend straight from the objects directory.

        The engine caches the chunk backend in memory at construction time. For
        honest tamper-evidence we must check the *current on-disk* bytes, so we
        rebuild the backend from disk before any integrity-sensitive read. This
        mirrors what a fresh process would see.
        """
        objects_dir = os.path.join(self.root, "objects")
        backend = {}
        if os.path.isdir(objects_dir):
            for nm in os.listdir(objects_dir):
                p = os.path.join(objects_dir, nm)
                if os.path.isfile(p):
                    with open(p, "rb") as fh:
                        dict.__setitem__(backend, nm, fh.read())
        # _DiskBackend mirrors writes to disk; swapping the dict contents keeps
        # that behaviour while reflecting external edits.
        self.store.backend.clear()
        for k, v in backend.items():
            dict.__setitem__(self.store.backend, k, v)

    # ---------------------------------------------------------------- verify
    def verify(self, name: str) -> str:
        """Re-derive and check every chunk of every file in the archive.

        Returns the archive Merkle root on success. Raises :class:`TamperError`
        identifying the offending file on the first integrity failure, or
        :class:`VaultError` for structural problems (missing manifest, etc.).
        """
        entries = self.entries(name)
        self._resync_from_disk()
        for e in entries:
            try:
                manifest = self.store.load_manifest(e.manifest_name)
            except (OSError, ValueError) as exc:
                raise VaultError(
                    "archive {!r}: missing/corrupt manifest for {!r}: {}".format(
                        name, e.relpath, exc
                    )
                )
            if manifest.root_digest != e.root_digest:
                raise TamperError(name, e.relpath, "manifest root digest changed")
            try:
                # get() re-hashes every chunk and re-checks the Merkle root.
                self.store.get(manifest)
            except ValueError as exc:
                raise TamperError(name, e.relpath, str(exc))
        return self.archive_root(name)

    # --------------------------------------------------------------- extract
    def extract(self, name: str, dest: str) -> List[str]:
        """Restore an archive to ``dest``, preserving structure.

        Every file is verified (re-hashed) as it is written. Returns the list of
        absolute paths written. Raises :class:`TamperError` on any failure.
        """
        entries = self.entries(name)
        self._resync_from_disk()
        dest = os.path.abspath(dest)
        os.makedirs(dest, exist_ok=True)
        written: List[str] = []
        for e in entries:
            # Guard against path traversal from a tampered index.
            rel = os.path.normpath(e.relpath)
            if rel.startswith("..") or os.path.isabs(rel):
                raise VaultError("unsafe relative path in archive: {!r}".format(e.relpath))
            out_path = os.path.join(dest, rel)
            try:
                manifest = self.store.load_manifest(e.manifest_name)
            except (OSError, ValueError) as exc:
                raise VaultError(
                    "missing/corrupt manifest for {!r}: {}".format(e.relpath, exc)
                )
            try:
                data = self.store.get(manifest)  # verifies on the way out
            except ValueError as exc:
                raise TamperError(name, e.relpath, str(exc))
            os.makedirs(os.path.dirname(out_path) or dest, exist_ok=True)
            tmp = out_path + ".knotvault.tmp"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, out_path)
            written.append(out_path)
        return written

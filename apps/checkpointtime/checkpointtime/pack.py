"""Deterministic packing of a file or directory tree into a single byte blob.

The format is intentionally simple and self-describing so it can be unpacked
without external metadata. Directory entries are emitted in sorted path order so
that the same tree always produces byte-identical output (a prerequisite for the
content-addressed dedup to work across snapshots).

Wire format (all integers big-endian)::

    magic:    b"CKPT1\\n"
    kind:     1 byte  -> b"F" (single file)  or  b"D" (directory tree)
    if kind == F:
        payload: raw file bytes (rest of blob)
    if kind == D:
        count:  4 bytes (uint32)        number of entries
        repeated count times:
            path_len:  2 bytes (uint16)
            path:      path_len bytes (utf-8, '/'-separated, relative)
            data_len:  8 bytes (uint64)
            data:      data_len bytes
"""
from __future__ import annotations

import os
import struct
from typing import List, Tuple

MAGIC = b"CKPT1\n"


def pack_path(path: str) -> bytes:
    """Pack a file or directory at ``path`` into a single deterministic blob."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    if os.path.isfile(path):
        with open(path, "rb") as fh:
            return MAGIC + b"F" + fh.read()

    if os.path.isdir(path):
        entries = _collect_dir(path)
        out = [MAGIC, b"D", struct.pack(">I", len(entries))]
        for rel, data in entries:
            rel_b = rel.encode("utf-8")
            out.append(struct.pack(">H", len(rel_b)))
            out.append(rel_b)
            out.append(struct.pack(">Q", len(data)))
            out.append(data)
        return b"".join(out)

    raise ValueError("path is neither a regular file nor a directory: %r" % path)


def unpack_to(blob: bytes, dest: str) -> None:
    """Reverse :func:`pack_path`, writing the contents to ``dest``.

    For a single-file blob, ``dest`` is the file to write (parent dirs created).
    For a directory blob, ``dest`` is the root directory to populate.
    """
    if not blob.startswith(MAGIC):
        raise ValueError("not a CheckpointTime blob (bad magic)")
    body = blob[len(MAGIC):]
    if not body:
        raise ValueError("truncated blob")
    kind, rest = body[:1], body[1:]

    if kind == b"F":
        parent = os.path.dirname(os.path.abspath(dest))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(rest)
        return

    if kind == b"D":
        os.makedirs(dest, exist_ok=True)
        (count,) = struct.unpack(">I", rest[:4])
        off = 4
        for _ in range(count):
            (plen,) = struct.unpack(">H", rest[off:off + 2]); off += 2
            rel = rest[off:off + plen].decode("utf-8"); off += plen
            (dlen,) = struct.unpack(">Q", rest[off:off + 8]); off += 8
            data = rest[off:off + dlen]; off += dlen
            target = os.path.join(dest, *rel.split("/"))
            os.makedirs(os.path.dirname(target) or dest, exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(data)
        return

    raise ValueError("unknown blob kind: %r" % kind)


def _collect_dir(root: str) -> List[Tuple[str, bytes]]:
    out = []  # type: List[Tuple[str, bytes]]
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            with open(full, "rb") as fh:
                out.append((rel, fh.read()))
    out.sort(key=lambda kv: kv[0])
    return out

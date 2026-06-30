"""Tests for the shared knotcore entry point and PersistentKnotStore."""
from __future__ import annotations

import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import knotcore  # noqa: E402


def _tmp():
    d = tempfile.mkdtemp()
    return d


def test_reexports_present():
    for name in ("KnotStore", "Manifest", "PersistentKnotStore",
                 "encode_manifest", "decode_manifest", "size_report",
                 "simhash64", "shard_of", "hamming", "MacroCube", "ProvenanceLog"):
        assert hasattr(knotcore, name), "knotcore missing {}".format(name)


def test_persist_roundtrip_across_instances():
    d = _tmp()
    try:
        payload = b"the quick brown fox " * 200
        s1 = knotcore.PersistentKnotStore(d, chunk_size=64)
        m = s1.put(payload, name="doc")
        s1.save_manifest(m)
        # a fresh instance must read objects + manifest back from disk
        s2 = knotcore.PersistentKnotStore(d, chunk_size=64)
        assert "doc" in s2.list_manifests()
        assert s2.get(s2.load_manifest("doc")) == payload
        assert s2.verify(s2.load_manifest("doc")) is True
    finally:
        shutil.rmtree(d)


def test_exact_duplicates_collapse_on_disk():
    d = _tmp()
    try:
        s = knotcore.PersistentKnotStore(d, chunk_size=64)
        block = b"A" * 64
        m1 = s.put(block * 10, name="a")          # 10 identical chunks
        before = s.bytes_on_disk()
        m2 = s.put(block * 10, name="b")          # same content again
        after = s.bytes_on_disk()
        # second identical object adds (almost) nothing but its manifest
        assert after - before < len(block) * 5
        assert s.get(m1) == s.get(m2)
    finally:
        shutil.rmtree(d)


def test_tamper_is_detected_on_reload():
    d = _tmp()
    try:
        s = knotcore.PersistentKnotStore(d, chunk_size=64)
        m = s.put(b"important record " * 50, name="rec")
        s.save_manifest(m)
        # corrupt one object file on disk
        objdir = os.path.join(d, "objects")
        victim = os.path.join(objdir, sorted(os.listdir(objdir))[0])
        with open(victim, "r+b") as fh:
            fh.seek(0); fh.write(b"\x00\x00\x00\x00")
        s2 = knotcore.PersistentKnotStore(d, chunk_size=64)
        assert s2.verify(s2.load_manifest("rec")) is False
    finally:
        shutil.rmtree(d)


def test_manifest_codec_is_compact():
    d = _tmp()
    try:
        s = knotcore.PersistentKnotStore(d, chunk_size=256)
        m = s.put(os.urandom(4096), name="blob")
        report = knotcore.size_report(m)
        assert report["binary_pointer_bytes_avg"] <= report["json_pointer_bytes_avg"]
    finally:
        shutil.rmtree(d)

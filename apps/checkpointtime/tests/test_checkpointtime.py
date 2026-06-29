from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from checkpointtime import CheckpointStore, CheckpointError  # noqa: E402


def _slowly_mutating(n=20, size=40000):
    base = bytearray((b"STATE-BLOCK-" * (size // 12 + 1)))[:size]
    states = []
    for step in range(n):
        for k in range(32):
            pos = (step * 911 + k * 137) % len(base)
            base[pos] = (base[pos] + step + k) % 256
        states.append(bytes(base))
    return states


def test_snapshot_restore_roundtrip(tmp_path):
    store = CheckpointStore(str(tmp_path / "s"))
    data = os.urandom(5000)
    cid = store.snapshot(data, label="x")
    assert store.restore(cid) == data


def test_dedup_makes_physical_much_smaller(tmp_path):
    store = CheckpointStore(str(tmp_path / "s"), chunk_size=1024)
    states = _slowly_mutating(n=20, size=40000)
    for i, st in enumerate(states):
        store.snapshot(st, label="step-%d" % i)
    stats = store.stats()
    assert stats["logical_bytes"] == sum(len(s) for s in states)
    # near-identical checkpoints must cost far less than their logical sum
    assert stats["physical_bytes_on_disk"] < stats["logical_bytes"] / 3.0
    assert stats["dedup_ratio"] > 3.0


def test_timeline_order_and_fields(tmp_path):
    store = CheckpointStore(str(tmp_path / "s"))
    ids = [store.snapshot(os.urandom(1000), label="l%d" % i) for i in range(4)]
    tl = store.timeline()
    assert [r["id"] for r in tl] == ids
    for r in tl:
        assert set(["id", "label", "time", "size", "fingerprint", "branch"]) <= set(r)


def test_rewind_is_reversible(tmp_path):
    store = CheckpointStore(str(tmp_path / "s"))
    ids = [store.snapshot(os.urandom(800), label=str(i)) for i in range(5)]
    store.rewind(ids[1])
    assert store.head == ids[1]
    # rewind loses no data: all checkpoints still restorable
    for cid in ids:
        assert store.restore(cid) is not None
    assert len(store.timeline()) == 5


def test_branch(tmp_path):
    store = CheckpointStore(str(tmp_path / "s"))
    ids = [store.snapshot(os.urandom(800), label=str(i)) for i in range(3)]
    store.branch(ids[0], "exp")
    assert store.branch_name == "exp"
    assert store.head == ids[0]
    new_id = store.snapshot(os.urandom(800), label="branched")
    assert store.checkpoints[new_id]["branch"] == "exp"
    with pytest.raises(CheckpointError):
        store.branch(ids[0], "exp")  # duplicate name


def test_reload_from_disk(tmp_path):
    root = str(tmp_path / "s")
    store = CheckpointStore(root)
    data = [os.urandom(1500) for _ in range(5)]
    ids = [store.snapshot(d, label="d%d" % i) for i, d in enumerate(data)]
    store.rewind(ids[2])

    reopened = CheckpointStore(root)
    assert [r["id"] for r in reopened.timeline()] == ids
    assert reopened.head == ids[2]
    for cid, d in zip(ids, data):
        assert reopened.restore(cid) == d
    assert reopened._log.verify_chain()


def test_snapshot_path_file_and_dir(tmp_path):
    store = CheckpointStore(str(tmp_path / "s"))
    f = tmp_path / "f.bin"
    f.write_bytes(b"hello-file")
    cid = store.snapshot_path(str(f))
    out = tmp_path / "out.bin"
    store.restore_path(cid, str(out))
    assert out.read_bytes() == b"hello-file"

    d = tmp_path / "tree"
    (d / "sub").mkdir(parents=True)
    (d / "a.txt").write_bytes(b"aaa")
    (d / "sub" / "b.txt").write_bytes(b"bbb")
    cid2 = store.snapshot_path(str(d))
    dest = tmp_path / "restored_tree"
    store.restore_path(cid2, str(dest))
    assert (dest / "a.txt").read_bytes() == b"aaa"
    assert (dest / "sub" / "b.txt").read_bytes() == b"bbb"


def test_unknown_id_raises(tmp_path):
    store = CheckpointStore(str(tmp_path / "s"))
    with pytest.raises(CheckpointError):
        store.restore("deadbeef")

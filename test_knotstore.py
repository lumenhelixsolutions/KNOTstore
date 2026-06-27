"""Tests for the corrected KnotStore. Run: python3 -m pytest -q  (or python3 test_knotstore.py)."""
from __future__ import annotations

import os
from hashlib import sha256
from knotstore import KnotStore
from codec import encode_manifest, decode_manifest
from signature import simhash64
from cube import MacroCube, RhoMove, compile_route as cube_route
from provenance import ProvenanceLog


def test_roundtrip_multichunk():
    ks = KnotStore(chunk_size=64)
    data = b"abc" * 1000
    m = ks.put(data, "roundtrip.bin")
    assert ks.get(m) == data
    assert ks.verify(m)


def test_empty():
    ks = KnotStore(chunk_size=64)
    m = ks.put(b"", "empty.bin")
    assert ks.get(m) == b""
    assert ks.verify(m)


def test_one_byte():
    ks = KnotStore(chunk_size=64)
    m = ks.put(b"Z", "one.bin")
    assert ks.get(m) == b"Z"


def test_dedupe():
    ks = KnotStore(chunk_size=32)
    data = b"A" * 1024  # 32 identical chunks
    m = ks.put(data, "dedupe.bin")
    assert len(ks.backend) < len(m.pointers)
    assert ks.get(m) == data


def test_corruption_detected():
    ks = KnotStore(chunk_size=32)
    m = ks.put(b"payload" * 100, "corrupt.bin")
    key = next(iter(ks.backend.keys()))
    ks.backend[key] = b"corrupted"
    assert not ks.verify(m)


def test_retrieval_is_address_regeneration_not_scan():
    """get() must reach the chunk via the regenerated address, not a scan.
    We prove it by removing the chunk at the regenerated address and asserting
    failure -- a scan-based get would still find an identical chunk elsewhere."""
    ks = KnotStore(chunk_size=32)
    data = os.urandom(32)
    m = ks.put(data, "addr.bin")
    digest = bytes.fromhex(m.digests[0])
    addr = ks.address_for(digest, m.pointers[0].probe)
    assert addr in ks.backend  # the regenerated address is the real key
    del ks.backend[addr]
    try:
        ks.get(m)
        assert False, "expected MISSING_CHUNK after deleting regenerated address"
    except ValueError:
        pass


def test_collision_recovery_small_address_space():
    """Shrink the address space so genuine (different-content) collisions occur,
    then confirm open-address probing still round-trips."""
    ks = KnotStore(chunk_size=16, address_bits=16)  # 65536-cell space
    blobs = [os.urandom(16) for _ in range(4000)]
    data = b"".join(blobs)
    m = ks.put(data, "collide.bin")
    assert any(p.probe > 0 for p in m.pointers), "expected at least one collision probe"
    assert ks.get(m) == data
    assert ks.verify(m)


def test_regenerated_address_matches_stored():
    ks = KnotStore(chunk_size=48)
    data = os.urandom(48 * 20)
    m = ks.put(data, "match.bin")
    for ptr, dhex in zip(m.pointers, m.digests):
        addr = ks.address_for(bytes.fromhex(dhex), ptr.probe)
        assert ks.digest(ks.backend[addr]) == bytes.fromhex(dhex)


def test_content_placement_roundtrip():
    """Content-based knot selection must not break exact retrieval: the knot is
    stored in the pointer, so get() regenerates the address without the chunk."""
    ks = KnotStore(chunk_size=64, placement="content")
    data = os.urandom(64 * 25)
    m = ks.put(data, "content.bin")
    assert m.placement == "content"
    assert ks.get(m) == data
    assert ks.verify(m)


def test_content_placement_gives_knot_locality():
    """Near-duplicate chunks should share a knot in content mode, far more than
    in digest mode."""
    import random
    from collections import Counter
    rng = random.Random(20240101)  # deterministic -> not flaky
    base = bytearray(rng.randbytes(256))
    variants = []
    for _ in range(60):
        v = bytearray(base)
        for _ in range(2):
            v[rng.randrange(256)] = rng.randrange(256)
        variants.append(bytes(v))
    ks_c = KnotStore(chunk_size=256, placement="content")
    ks_d = KnotStore(chunk_size=256, placement="digest")
    knots_c = Counter(ks_c.knot_for(v, sha256(v).digest()) for v in variants)
    knots_d = Counter(ks_d.knot_for(v, sha256(v).digest()) for v in variants)
    frac_c = knots_c.most_common(1)[0][1] / len(variants)
    frac_d = knots_d.most_common(1)[0][1] / len(variants)
    # content mode concentrates near-dups onto a dominant knot far more than the
    # digest-derived selector, which spreads them ~uniformly over the 7 knots
    assert frac_c > 2 * frac_d
    assert len(knots_c) < len(knots_d)


def test_codec_roundtrip_digest_mode():
    ks = KnotStore(chunk_size=128)
    data = os.urandom(128 * 33 + 7)
    m = ks.put(data, "codec_d.bin")
    back = decode_manifest(encode_manifest(m))
    assert back.to_json() == m.to_json()
    assert ks.get(back) == data


def test_codec_roundtrip_content_mode_and_edge_sizes():
    for data, cs in [(b"", 64), (b"Z", 64), (os.urandom(64 * 4), 64),
                     (os.urandom(64 * 4 + 13), 64)]:
        ks = KnotStore(chunk_size=cs, placement="content")
        m = ks.put(data, "edge.bin")
        back = decode_manifest(encode_manifest(m))
        assert back.to_json() == m.to_json(), f"manifest mismatch for len={len(data)}"
        assert ks.get(back) == data


def test_binary_pointer_is_smaller_than_json():
    ks = KnotStore(chunk_size=256, placement="content")
    data = os.urandom(256 * 50)
    m = ks.put(data, "small.bin")
    json_ptr = sum(len(p.to_json().encode()) for p in m.pointers) / len(m.pointers)
    blob = encode_manifest(m)
    per_ptr_binary = (len(blob) - 32 * len(m.pointers)) / len(m.pointers)
    assert per_ptr_binary < json_ptr / 20  # at least 20x smaller per pointer


def test_codec_large_probe_escape():
    """Force a probe >= 31 so the varint escape path is exercised end-to-end."""
    import random
    rng = random.Random(99)  # deterministic -> not flaky
    ks = KnotStore(chunk_size=16, address_bits=8)  # 256 cells, fill to 255
    data = b"".join(rng.randbytes(16) for _ in range(255))
    m = ks.put(data, "deep.bin")
    assert max(p.probe for p in m.pointers) >= 31
    back = decode_manifest(encode_manifest(m))
    assert back.to_json() == m.to_json()
    assert ks.get(back) == data


def test_cube_single_move_changes_state():
    c = MacroCube()
    assert c.is_identity()
    c.apply_move(RhoMove("X", 1, 1))
    assert not c.is_identity()  # the move actually does something


def test_cube_move_order_4_is_identity():
    """A 90-degree slice turn applied 4x returns to the solved state."""
    for axis in ("X", "Y", "Z"):
        for layer in (-1, 0, 1):
            c = MacroCube()
            for _ in range(4):
                c.apply_move(RhoMove(axis, layer, 1))
            assert c.is_identity(), f"{axis}{layer} order-4 failed"


def test_cube_route_inverse_is_identity():
    """Prop 2 as a tested fact: W^-1 . W = id for random routes."""
    for _ in range(20):
        route = cube_route(os.urandom(16), depth=15)
        c = MacroCube().apply_route(route)
        c.apply_route(MacroCube.inverse_route(route))
        assert c.is_identity()


def test_cube_is_a_permutation_no_face_lost():
    """Every move preserves the multiset of 162 (subcube, home-face) faces."""
    c = MacroCube()
    base = sorted((sid, f) for sid, orient in c.cells for f in orient)
    for _ in range(50):
        m = cube_route(os.urandom(8), depth=1)[0]
        c.apply_move(m)
    after = sorted((sid, f) for sid, orient in c.cells for f in orient)
    assert base == after


def test_provenance_rollback_recovers_each_state():
    log = ProvenanceLog()
    fps = [log.add(ev).fingerprint_after for ev in ["a", "b", "c", "d"]]
    assert log.verify_chain()
    for expected_prior in reversed(fps[:-1]):
        log.rollback()
        assert log.fingerprint() == expected_prior
    log.rollback()
    assert log.cube.is_identity()


def test_provenance_is_order_sensitive():
    a = ProvenanceLog()
    for ev in ["x", "y", "z"]:
        a.add(ev)
    b = ProvenanceLog()
    for ev in ["y", "x", "z"]:
        b.add(ev)
    assert a.fingerprint() != b.fingerprint()


def test_store_routes_are_reversible_cube_paths():
    ks = KnotStore()
    digest = sha256(b"some chunk").digest()
    knot = ks.select_knot(digest)
    fp1 = ks.route_cube_fingerprint(knot, digest)
    fp2 = ks.route_cube_fingerprint(knot, digest)
    assert fp1 == fp2 and fp1 != MacroCube().fingerprint()  # deterministic, non-trivial
    # and the underlying route is invertible
    route = ks.compile_route(knot, digest, ks.route_depth)
    cube = MacroCube().apply_route([RhoMove(m.axis, m.layer, m.direction) for m in route])
    cube.apply_route(MacroCube.inverse_route(
        [RhoMove(m.axis, m.layer, m.direction) for m in route]))
    assert cube.is_identity()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")

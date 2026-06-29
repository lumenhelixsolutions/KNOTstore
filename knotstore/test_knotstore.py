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
    base = bytearray(rng.getrandbits(8) for _ in range(256))  # 3.8-safe (no Random.randbytes)
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
    data = b"".join(bytes(rng.getrandbits(8) for _ in range(16)) for _ in range(255))
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


# ---------------------------------------------------------------------------
# v0.1.4 — braid representation, Cauldron canonical semantics, audit log
# ---------------------------------------------------------------------------

from braid import route_to_braid, braid_fingerprint, BraidWord
from cauldron import CauldronSemantics, CauldronManifest, DELTA_PAIRS, quadratic_moment, cauldron_is_canonical
from audit import AuditLog, AuditEvent
from burau import (
    LaurentPoly, reduced_burau_generator, braid_to_burau_matrix,
    alexander_invariant, alexander_poly_from_braid,
)
from knot_table import KNOT_RECORDS, get_knot, non_invertible_knots, KNOT_BY_NAME


def test_braid_fingerprint_is_deterministic():
    """Same knot+digest always produces the same braid fingerprint."""
    ks = KnotStore()
    digest = sha256(b"braid test").digest()
    knot = ks.select_knot(digest)
    fp1 = ks.route_braid_fingerprint(knot, digest)
    fp2 = ks.route_braid_fingerprint(knot, digest)
    assert fp1 == fp2


def test_braid_fingerprint_is_non_trivial():
    """A 10-move route produces a non-trivial (non-identity) braid."""
    ks = KnotStore()
    digest = sha256(b"non-trivial").digest()
    knot = ks.select_knot(digest)
    fp = ks.route_braid_fingerprint(knot, digest)
    # Trivial braid would be B(0, (0,1,2,...,8)); depth=10 with 4 crossings/move = 40 crossings
    assert fp.startswith("B(40,")


def test_braid_inverse_is_identity_permutation():
    """Composing a route braid with its inverse yields the identity permutation."""
    ks = KnotStore()
    digest = sha256(b"inverse test").digest()
    knot = ks.select_knot(digest)
    route = ks.compile_route(knot, digest, ks.route_depth)
    moves = [(m.axis, m.layer, m.direction) for m in route]
    braid = route_to_braid(moves)
    combined = braid.extend(braid.inverse())
    assert combined.trace_strands() == list(range(9))


def test_cauldron_canonical_ordering():
    """The quadratic moment function gives a strict total order on δ-pairs (no ties)."""
    assert cauldron_is_canonical()
    moments = [quadratic_moment(a, b) for a, b in DELTA_PAIRS]
    assert moments == sorted(moments), "δ-pairs must be in ascending moment order"
    assert len(set(moments)) == len(moments), "all moment values must be distinct"


def test_cauldron_manifest_lift_and_roundtrip():
    """A KNOTstore manifest lifts to a Cauldron manifest and round-trips through JSON."""
    ks = KnotStore(chunk_size=64)
    m = ks.put(os.urandom(64 * 5), "cauldron_test.bin")
    cm = CauldronManifest.from_manifest(m)
    assert cm.phase == 0
    cm.commit()
    fp = cm.current_fingerprint()
    assert fp != "origin"
    rolled = cm.rollback()
    assert rolled == fp
    assert cm.phase == 1  # dual phase after rollback
    assert cm.current_fingerprint() == "origin"


def test_audit_chain_creates_and_verifies():
    """A three-event audit log creates a valid, verifiable chain."""
    log = AuditLog()
    for eid, etype in [("e1", "ACCESS"), ("e2", "COMMIT"), ("e3", "ACCESS")]:
        log.add(AuditEvent(event_id=eid, event_type=etype, actor="user", data="{}"))
    assert log.verify()
    assert log.fingerprint() != sha256(b"cauldron-origin").hexdigest()


def test_audit_chain_is_order_sensitive():
    """Adding events in a different order produces a different fingerprint."""
    log1 = AuditLog()
    log2 = AuditLog()
    events = [
        AuditEvent(event_id="e1", event_type="ACCESS", actor="u", data="{}"),
        AuditEvent(event_id="e2", event_type="COMMIT", actor="u", data="{}"),
    ]
    log1.add(events[0]); log1.add(events[1])
    log2.add(events[1]); log2.add(events[0])
    assert log1.fingerprint() != log2.fingerprint()
    assert log1.reorder_detected(log2)


def test_audit_phase_flip_changes_fingerprint():
    """Flipping to the dual phase produces a different fingerprint."""
    log = AuditLog()
    log.add(AuditEvent(event_id="e1", event_type="ACCESS", actor="u", data="{}"))
    fp_forward = log.fingerprint()
    log.flip_phase()
    fp_dual = log.fingerprint()
    assert fp_forward != fp_dual


# ---------------------------------------------------------------------------
# v0.1.5 — full Burau representation and knot table
# ---------------------------------------------------------------------------


def test_burau_braid_relation():
    """Reduced Burau generators satisfy σ₁σ₂σ₁ = σ₂σ₁σ₂ (fundamental braid relation)."""
    s1 = reduced_burau_generator(3, 0, 1)
    s2 = reduced_burau_generator(3, 1, 1)
    assert (s1 * s2) * s1 == (s2 * s1) * s2, "braid relation must hold in Burau rep"


def test_burau_generator_inverse():
    """σᵢ · σᵢ⁻¹ = I in the reduced Burau representation."""
    from burau import LaurentMatrix
    for n in (2, 3, 4):
        for k in range(n - 1):
            gen = reduced_burau_generator(n, k, 1)
            gen_inv = reduced_burau_generator(n, k, -1)
            assert gen * gen_inv == LaurentMatrix.identity(n - 1), \
                f"σ_{k+1}·σ_{k+1}⁻¹ ≠ I for n={n}"


def test_alexander_poly_trefoil():
    """Trefoil (σ₁³ in B₂) has Alexander polynomial 1 − t + t²."""
    from braid import BraidCrossing
    crossings = [BraidCrossing(0, 1)] * 3
    poly = alexander_invariant(crossings, n_strands=2)
    assert poly == LaurentPoly({0: 1, 1: -1, 2: 1}), f"got {poly}"


def test_alexander_poly_figure_eight():
    """Figure-eight (σ₁σ₂⁻¹σ₁σ₂⁻¹ in B₃) has Alexander polynomial 1 − 3t + t²."""
    from braid import BraidCrossing
    crossings = [BraidCrossing(0, 1), BraidCrossing(1, -1),
                 BraidCrossing(0, 1), BraidCrossing(1, -1)]
    poly = alexander_invariant(crossings, n_strands=3)
    assert poly.normalize() == LaurentPoly({0: 1, 1: -3, 2: 1}), f"got {poly}"


def test_knot_table_seven_entries():
    """KNOT_RECORDS contains exactly the seven KNOTS_V01 knots."""
    from knotstore import KNOTS_V01
    assert len(KNOT_RECORDS) == len(KNOTS_V01)
    for name in KNOTS_V01:
        assert name in KNOT_BY_NAME, f"{name} missing from knot table"


def test_knot_table_invertibility():
    """10_83 is confirmed non-invertible; 10_34 is amphichiral (hence invertible)."""
    assert not get_knot("10_83").invertible, "10_83 should be non-invertible"
    assert get_knot("10_34").amphichiral, "10_34 should be amphichiral"
    bad = non_invertible_knots()
    assert any(k.name == "10_83" for k in bad)


def test_knot_table_non_alternating():
    """10_125 and 10_136 are non-alternating."""
    assert not get_knot("10_125").alternating
    assert not get_knot("10_136").alternating


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")

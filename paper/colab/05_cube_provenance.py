"""
Google Colab Notebook 5: Reversible Macro-Cube and Provenance
=============================================================
Topics covered:
  - MacroCube: 27 subcubes, 162 faces, bijective ρ-moves
  - Route application and state fingerprinting
  - Inverse routes: W⁻¹·W = identity (Proposition 2)
  - ProvenanceLog: reversible audit chain with rollback
  - Route-to-cube fingerprint vs braid fingerprint
"""
import sys, os as _os
sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '../../knotstore'))


# ── Cell 1: MacroCube basics ──────────────────────────────────────────────
from cube import MacroCube, RhoMove, compile_route as cube_route
from knotstore import KnotStore
from hashlib import sha256
import os

cube = MacroCube()
print(f"Initial state: identity = {cube.is_identity()}")
print(f"Fingerprint:   {cube.fingerprint()[:24]}…")

# Apply a single move
cube.apply_move(RhoMove("X", 1, 1))
print(f"\nAfter X+1 move:")
print(f"  identity = {cube.is_identity()}")
print(f"  fingerprint = {cube.fingerprint()[:24]}…")


# ── Cell 2: Order-4 property ──────────────────────────────────────────────
print("\nOrder-4 property (each 90° rotation × 4 = identity):")

for axis in ("X", "Y", "Z"):
    for layer in (-1, 0, 1):
        c = MacroCube()
        for _ in range(4):
            c.apply_move(RhoMove(axis, layer, 1))
        ok = c.is_identity()
        print(f"  {axis}{layer:+d} × 4:  {'✓' if ok else '✗'}")


# ── Cell 3: Inverse route = identity (Proposition 2) ─────────────────────
print("\nProp 2: W⁻¹·W = id  for random routes")

passed = 0
for trial in range(20):
    route = cube_route(os.urandom(16), depth=15)
    c = MacroCube().apply_route(route)
    c.apply_route(MacroCube.inverse_route(route))
    if c.is_identity():
        passed += 1

print(f"  Passed {passed}/20 trials (expected: 20/20)")


# ── Cell 4: No face is lost (bijection proof) ─────────────────────────────
print("\nBijection property: all 162 faces preserved after any route")

c = MacroCube()
base = sorted((sid, f) for sid, orient in c.cells for f in orient)

route = cube_route(os.urandom(32), depth=50)
c.apply_route(route)
after = sorted((sid, f) for sid, orient in c.cells for f in orient)

print(f"  Faces before: {len(base)}")
print(f"  Faces after:  {len(after)}")
print(f"  Multiset preserved: {base == after}")


# ── Cell 5: Route fingerprints ───────────────────────────────────────────
print("\nRoute fingerprints (cube vs braid) for same knot+digest:")

ks = KnotStore()
digest = sha256(b"test chunk payload").digest()
knot = ks.select_knot(digest)

fp_cube  = ks.route_cube_fingerprint(knot, digest)
fp_braid = ks.route_braid_fingerprint(knot, digest)

print(f"  knot:         {knot}")
print(f"  cube_fp:      {fp_cube[:24]}…")
print(f"  braid_fp:     {fp_braid}")
print()
print("  Both are deterministic (same on every call):")
assert ks.route_cube_fingerprint(knot, digest) == fp_cube
assert ks.route_braid_fingerprint(knot, digest) == fp_braid
print("  ✓ verified")


# ── Cell 6: Provenance log ───────────────────────────────────────────────
from provenance import ProvenanceLog

print("\nProvenanceLog: reversible audit chain")

log = ProvenanceLog()
events = ["write_file_A", "read_file_A", "write_file_B", "delete_file_A"]
fps = []
for ev in events:
    link = log.add(ev)
    fps.append(link.fingerprint_after)
    print(f"  {ev:20s} → {link.fingerprint_after[:16]}…")

print(f"\nChain valid: {log.verify_chain()}")
print(f"\nRolling back:")
for i in range(len(events) - 1, -1, -1):
    log.rollback()
    current = log.fingerprint()
    if i > 0:
        expected = fps[i - 1]
        match = current == expected
        print(f"  After rollback {i}: {current[:16]}… (matches fp[{i-1}]: {match})")
    else:
        identity = log.cube.is_identity()
        print(f"  After final rollback: identity cube = {identity}")

print("\nOrder sensitivity:")
log_a = ProvenanceLog()
log_b = ProvenanceLog()
for ev in ["alpha", "beta", "gamma"]:
    log_a.add(ev)
for ev in ["beta", "alpha", "gamma"]:
    log_b.add(ev)
print(f"  log(alpha,beta,gamma) ≠ log(beta,alpha,gamma): {log_a.fingerprint() != log_b.fingerprint()}")

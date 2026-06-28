"""
Google Colab Notebook 4: Cauldron Semantics and Phase-Duality Audit
====================================================================
Topics covered:
  - Cauldron 10-state system: Axis {0,1} + Ring {2..9}
  - Canonical δ-pair ordering via quadratic moment I(a,b) = a² + b²
  - CauldronManifest: enriched storage manifest with commit/rollback
  - Phase-duality audit log: forward (p=0) and dual (p=1) fingerprints
  - Order-sensitivity and tamper detection
"""
import sys, os as _os
sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '../../knotstore'))


# ── Cell 1: Cauldron system ───────────────────────────────────────────────
from cauldron import (
    DELTA_PAIRS, CAULDRON_AXIS, CAULDRON_RING,
    quadratic_moment, cauldron_is_canonical,
    CauldronSemantics, CauldronManifest, DEFAULT_SEMANTICS
)
import json

print("Cauldron 10-state system")
print(f"  Axis:  {CAULDRON_AXIS}  (the 2-element core)")
print(f"  Ring:  {CAULDRON_RING}  (the 8-element outer ring)")
print(f"  Symmetry group: D₈ × ℤ₂ (order 32)")
print()

print("δ-pairs with quadratic moments I(a,b) = a² + b²:")
for a, b in DELTA_PAIRS:
    moment = quadratic_moment(a, b)
    print(f"  {{{a},{b}}}  →  I = {a}² + {b}² = {moment}")

print()
print(f"Canonical ordering holds (all moments distinct): {cauldron_is_canonical()}")


# ── Cell 2: Canonicality proof ────────────────────────────────────────────
print("\n" + "="*55)
print("CANONICALITY PROOF")
print("="*55)

moments = [quadratic_moment(a, b) for a, b in DELTA_PAIRS]
pairs_sorted = sorted(zip(moments, DELTA_PAIRS))

print("""
Theorem: I(a,b) = a² + b² assigns distinct values to the four δ-pairs.

Proof (by enumeration):
""")
for m, (a, b) in pairs_sorted:
    print(f"  I({a},{b}) = {a}² + {b}² = {a**2} + {b**2} = {m}")

all_distinct = len(set(moments)) == len(moments)
ordered = moments == sorted(moments)
print(f"\nAll values distinct: {all_distinct}")
print(f"In ascending order: {ordered}")
print(f"\nConclusion: The ordering {[m for m, _ in pairs_sorted]} is canonical. □")


# ── Cell 3: CauldronSemantics fingerprint ─────────────────────────────────
print("\n" + "="*55)
print("CAULDRON SEMANTICS FINGERPRINT")
print("="*55)

sem = CauldronSemantics()
print("\nSemantics dict:")
print(json.dumps(sem.to_dict(), indent=2))
print(f"\nFingerprint (first 16 hex): {sem.fingerprint()[:16]}…")
print("(Fingerprint is deterministic — same value on every run)")


# ── Cell 4: CauldronManifest lift and commit/rollback ─────────────────────
from knotstore import KnotStore
import os

print("\n" + "="*55)
print("CAULDRON MANIFEST: COMMIT / ROLLBACK")
print("="*55)

ks = KnotStore(chunk_size=64)
m = ks.put(os.urandom(64 * 5), "example.bin")
cm = CauldronManifest.from_manifest(m)

print(f"\nInitial state:")
print(f"  phase = {cm.phase}  (0 = forward)")
print(f"  fingerprint = {cm.current_fingerprint()!r}")

cm.commit()
fp1 = cm.current_fingerprint()
print(f"\nAfter commit():")
print(f"  phase = {cm.phase}")
print(f"  fingerprint = {fp1!r}")

cm.commit()
fp2 = cm.current_fingerprint()
print(f"\nAfter second commit():")
print(f"  fingerprint = {fp2!r}")

rolled_back = cm.rollback()
print(f"\nAfter rollback():")
print(f"  rolled back fp: {rolled_back!r}")
print(f"  current fp:     {cm.current_fingerprint()!r}  (= fp1? {cm.current_fingerprint() == fp1})")
print(f"  phase = {cm.phase}  (1 = dual, after rollback)")

cm.rollback()
print(f"\nAfter second rollback():")
print(f"  fingerprint = {cm.current_fingerprint()!r}  (= 'origin'? {cm.current_fingerprint() == 'origin'})")


# ── Cell 5: Phase-duality audit log ──────────────────────────────────────
from audit import AuditLog, AuditEvent

print("\n" + "="*55)
print("PHASE-DUALITY AUDIT LOG")
print("="*55)

log = AuditLog()
events_data = [
    ("e1", "ACCESS", "alice", "login attempt"),
    ("e2", "COMMIT", "system", "biometric check passed"),
    ("e3", "ACCESS", "alice", "file read"),
]

for eid, etype, actor, data_str in events_data:
    ev = AuditEvent(event_id=eid, event_type=etype, actor=actor, data=data_str)
    link = log.add(ev)
    print(f"\n{eid} ({etype}):")
    print(f"  forward_fp = {link.forward_fp[:16]}…")
    print(f"  dual_fp    = {link.dual_fp[:16]}…")

print(f"\nChain verifies: {log.verify()}")
print(f"Fingerprint:    {log.fingerprint()[:16]}…  (phase={log.phase})")

log.flip_phase()
print(f"\nAfter flip_phase():")
print(f"Fingerprint:    {log.fingerprint()[:16]}…  (phase={log.phase})")
print(f"Same as forward: {log.fingerprint() == log.links[-1].forward_fp}")


# ── Cell 6: Tamper detection ──────────────────────────────────────────────
print("\n" + "="*55)
print("TAMPER DETECTION")
print("="*55)

log2 = AuditLog()
for eid, etype, actor, data_str in events_data:
    log2.add(AuditEvent(event_id=eid, event_type=etype, actor=actor, data=data_str))

print(f"Original chain verifies: {log2.verify()}")

# Tamper: modify the data of event 1
log2.links[1].event.data = "TAMPERED"
print(f"After tampering e2.data: {log2.verify()}")

# Reorder detection
log3 = AuditLog()
for eid, etype, actor, data_str in reversed(events_data):
    log3.add(AuditEvent(event_id=eid, event_type=etype, actor=actor, data=data_str))

log4 = AuditLog()
for eid, etype, actor, data_str in events_data:
    log4.add(AuditEvent(event_id=eid, event_type=etype, actor=actor, data=data_str))

print(f"\nReorder detected (reversed vs original): {log4.reorder_detected(log3)}")
print(f"Fingerprints differ: {log3.fingerprint() != log4.fingerprint()}")

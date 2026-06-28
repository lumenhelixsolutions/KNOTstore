"""
Google Colab Notebook 3: Knot Verification and Table
=====================================================
Topics covered:
  - The seven KNOTS_V01 knots characterized
  - Invertibility, amphichirality, alternating property
  - Non-invertible knots: why 10_83 is problematic
  - Alexander polynomials from KnotInfo
  - Recommendation for KNOTstore v0.1.5
"""
import sys, os as _os
sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '../../knotstore'))


# ── Cell 1: Load knot table ───────────────────────────────────────────────
from knot_table import (
    KNOT_RECORDS, KNOT_BY_NAME, get_knot,
    non_invertible_knots, suitable_for_knotstore, print_summary
)
from knotstore import KNOTS_V01

print_summary()


# ── Cell 2: Detailed properties ───────────────────────────────────────────
print("\nDetailed knot properties:")
print("-" * 70)
for k in KNOT_RECORDS:
    print(f"\n{k.name}:")
    print(f"  Invertible:   {k.invertible}")
    print(f"  Amphichiral:  {k.amphichiral}")
    print(f"  Alternating:  {k.alternating}")
    print(f"  Determinant:  {k.determinant}")
    print(f"  Signature:    {k.signature:+d}")
    print(f"  Braid index:  {k.braid_index}")
    print(f"  Braid word:   {k.braid_word}")
    print(f"  Alexander Δ:  {k.alexander_poly[:60]}")
    if k.notes:
        print(f"  Notes:        {k.notes[:80]}")


# ── Cell 3: Why non-invertibility matters ─────────────────────────────────
print("\n" + "="*60)
print("WHY NON-INVERTIBILITY IS PROBLEMATIC FOR KNOTSTORE")
print("="*60)

print("""
A knot K is INVERTIBLE if it is isotopic to its orientation-reverse
K̄ (the same knot traversed in the opposite direction).

For reversible addressing, we need:
  route R → address A
  inverse route R⁻¹ → same address family A

If the knot is non-invertible:
  K oriented forward  → topological type T₁
  K oriented backward → topological type T₂ ≠ T₁

This means forward routes and backward routes are in DIFFERENT
topological classes, breaking the reversibility invariant.
""")

bad = non_invertible_knots()
for k in bad:
    print(f"  {k.name}: {k.notes[:100]}")

print(f"\nKnots SUITABLE for reversible addressing: {[k.name for k in suitable_for_knotstore()]}")


# ── Cell 4: Shared Alexander polynomial (10_125 vs 10_136) ───────────────
print("\n" + "="*60)
print("SHARED ALEXANDER POLYNOMIAL: 10_125 and 10_136")
print("="*60)

k125 = get_knot("10_125")
k136 = get_knot("10_136")

print(f"\n  10_125 Alexander: {k125.alexander_poly}")
print(f"  10_136 Alexander: {k136.alexander_poly}")
print(f"\n  Same polynomial: {k125.alexander_poly == k136.alexander_poly}")
print(f"\n  Distinguishing invariants:")
print(f"  10_125 alternating={k125.alternating}, det={k125.determinant}, sig={k125.signature:+d}")
print(f"  10_136 alternating={k136.alternating}, det={k136.determinant}, sig={k136.signature:+d}")
print("""
  The Alexander polynomial cannot distinguish these two knots!
  Their Jones polynomials are different (not computed here, requires
  HOMFLY polynomial machinery beyond the Burau representation).
""")


# ── Cell 5: Knot determinants as Alexander values ─────────────────────────
print("="*60)
print("DETERMINANT = |Δ(-1)|")
print("="*60)

print("""
The knot determinant is |Δ(-1)| where Δ is the Alexander polynomial.
For the trefoil: Δ(t) = 1 - t + t², so Δ(-1) = 1+1+1 = 3. det = 3.

For KNOTS_V01 (from KnotInfo table):
""")

for k in KNOT_RECORDS:
    print(f"  {k.name:<8}  det = {k.determinant}")

print("""
Note: 10_20 has the smallest determinant (13) → simplest Alexander structure.
10_85 has the largest (49 = 7²) → most complex for an alternating knot.
""")


# ── Cell 6: Recommendation for v0.1.5 ────────────────────────────────────
print("="*60)
print("RECOMMENDATION FOR KNOTSTORE v0.1.5")
print("="*60)

print("""
Current KNOTS_V01 issues:
  1. 10_83: CONFIRMED non-invertible → replace
  2. 10_85: PROBABLE non-invertible → replace or flag
  3. All 7 are chiral (except 10_34) → preferably use amphichiral

Proposed replacement set for maximum topological robustness:
  ✓ Keep: 10_34  (amphichiral, invertible)
  ✓ Keep: 10_61  (invertible, lowest braid index = 3)
  ✓ Keep: 10_20  (invertible, smallest determinant = 13)
  ✓ Keep: 10_125 (invertible, non-alternating)
  ✓ Keep: 10_136 (invertible, non-alternating, different from 10_125)
  ✗ Replace 10_83 with: 10_99  (amphichiral, invertible)
  ✗ Replace 10_85 with: 10_123 (amphichiral, invertible)

The criterion: prefer amphichiral + invertible knots, which ensure that
the route and its inverse are in the same topological class.
""")

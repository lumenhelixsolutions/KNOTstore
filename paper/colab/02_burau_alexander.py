"""
Google Colab Notebook 2: Burau Representation and Alexander Polynomials
=======================================================================
Topics covered:
  - Laurent polynomials over ℤ
  - Reduced Burau matrices for braid generators
  - Alexander polynomial computation
  - Verification: trefoil, figure-eight, torus knots
  - KNOTstore route Alexander polynomials
"""
import sys, os as _os
sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '../../knotstore'))


# ── Cell 1: Laurent polynomials ──────────────────────────────────────────
from burau import LaurentPoly, LaurentMatrix, reduced_burau_generator
from burau import braid_to_burau_matrix, alexander_invariant, _sum_of_t_powers
from braid import BraidCrossing, BraidWord, route_to_braid
from knotstore import KnotStore
from hashlib import sha256

# Construct some Laurent polynomials
t = LaurentPoly.T                    # the formal variable t
one = LaurentPoly.one()
p = LaurentPoly({0: 1, 1: -1, 2: 1})   # 1 - t + t²

print("Laurent polynomial arithmetic:")
print(f"  t   = {t}")
print(f"  1   = {one}")
print(f"  p   = {p}   (trefoil Alexander polynomial)")
print(f"  p²  = {p * p}")
print(f"  p(2) = {p.evaluate(2)}   (should be 1-2+4=3)")

# Verify normalization
neg = LaurentPoly({0: -1, 1: 1, 2: -1})   # -(1-t+t²)
print(f"\n  normalize(-p) = {neg.normalize()}   (should equal p)")


# ── Cell 2: Burau generators ─────────────────────────────────────────────
print("\nReduced Burau generators for B₃:")

s1 = reduced_burau_generator(3, 0, 1)
s2 = reduced_burau_generator(3, 1, 1)

print("ρ̄(σ₁) =")
for row in s1.rows:
    print(" ", [str(x) for x in row])
print("ρ̄(σ₂) =")
for row in s2.rows:
    print(" ", [str(x) for x in row])

# Verify braid relation σ₁σ₂σ₁ = σ₂σ₁σ₂
lhs = (s1 * s2) * s1
rhs = (s2 * s1) * s2
print(f"\nBraid relation σ₁σ₂σ₁ = σ₂σ₁σ₂: {'HOLDS' if lhs == rhs else 'FAILS'}")

# Verify inverse: σ₁·σ₁⁻¹ = I
s1_inv = reduced_burau_generator(3, 0, -1)
product = s1 * s1_inv
is_identity = all(
    product[i, j] == (LaurentPoly.one() if i == j else LaurentPoly.zero())
    for i in range(2) for j in range(2)
)
print(f"Inverse: σ₁·σ₁⁻¹ = I: {'YES' if is_identity else 'NO'}")


# ── Cell 3: Trefoil Alexander polynomial ─────────────────────────────────
print("\n" + "="*50)
print("Alexander polynomial computations")
print("="*50)

# Trefoil = closure of σ₁³ in B₂
trefoil = [BraidCrossing(0, 1)] * 3
poly_trefoil = alexander_invariant(trefoil, n_strands=2)
expected_trefoil = LaurentPoly({0: 1, 1: -1, 2: 1})
print(f"\nTrefoil (σ₁³ in B₂):")
print(f"  Δ(t) = {poly_trefoil}")
print(f"  Expected: 1 - t + t²")
print(f"  Match: {poly_trefoil == expected_trefoil}")

# Figure-eight = closure of σ₁σ₂⁻¹σ₁σ₂⁻¹ in B₃
fig8 = [BraidCrossing(0, 1), BraidCrossing(1, -1),
        BraidCrossing(0, 1), BraidCrossing(1, -1)]
poly_fig8 = alexander_invariant(fig8, n_strands=3)
expected_fig8 = LaurentPoly({0: 1, 1: -3, 2: 1})
print(f"\nFigure-eight (σ₁σ₂⁻¹σ₁σ₂⁻¹ in B₃):")
print(f"  Δ(t) = {poly_fig8}")
print(f"  Expected: 1 - 3t + t²")
print(f"  Match: {poly_fig8.normalize() == expected_fig8}")


# ── Cell 4: Torus knot T(2,5) (cinquefoil) ───────────────────────────────
# T(2,5) = closure of σ₁⁵ in B₂
# Alexander polynomial: 1 - t + t² - t³ + t⁴
cinquefoil = [BraidCrossing(0, 1)] * 5
poly_cinq = alexander_invariant(cinquefoil, n_strands=2)
expected_cinq = LaurentPoly({0: 1, 1: -1, 2: 1, 3: -1, 4: 1})
print(f"\nCinquefoil T(2,5) (σ₁⁵ in B₂):")
print(f"  Δ(t) = {poly_cinq}")
print(f"  Expected: 1 - t + t² - t³ + t⁴")
print(f"  Match: {poly_cinq == expected_cinq}")


# ── Cell 5: Route Alexander polynomials from KNOTstore ───────────────────
print("\n" + "="*50)
print("Route Alexander polynomials (KNOTstore)")
print("="*50)

from burau import alexander_poly_from_braid

ks = KnotStore()

# Compute Alexander polynomial for several digests
for seed in [b"chunk_alpha", b"chunk_beta", b"chunk_gamma"]:
    digest = sha256(seed).digest()
    knot = ks.select_knot(digest)
    route = ks.compile_route(knot, digest, ks.route_depth)
    moves = [(m.axis, m.layer, m.direction) for m in route]
    braid = route_to_braid(moves)
    poly = alexander_poly_from_braid(braid)
    braid_fp = ks.route_braid_fingerprint(knot, digest)
    print(f"\n  seed={seed.decode()}")
    print(f"  knot={knot}, braid_fingerprint={braid_fp[:30]}...")
    print(f"  Alexander poly: {poly}")

print("\nNote: Routes in B₉ (9 strands, depth 10) produce degree-40 braid words.")
print("The Alexander polynomial is a topological invariant of the route's knot class.")

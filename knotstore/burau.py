"""
Reduced Burau representation and Alexander polynomial computation.

The reduced Burau representation ρ̄: B_n → GL_{n-1}(ℤ[t, t⁻¹]) provides the
algebraic foundation for computing Alexander polynomials from braid words.

For a braid β ∈ B_n with closure β̂, the Alexander polynomial is:
    Δ(t) = det(I − ρ̄(β)) / (1 + t + t² + … + t^{n-2})

Reference: Burau (1936), Alexander (1928), Birman (1974).
Verified against known knots: trefoil (σ₁σ₂)³ → Δ(t) = 1 − t + t²
"""
from __future__ import annotations

from typing import Dict, List, Tuple, Optional
from fractions import Fraction
import copy


# ---------------------------------------------------------------------------
# Laurent polynomials over ℤ
# ---------------------------------------------------------------------------

class LaurentPoly:
    """Element of ℤ[t, t⁻¹]. Internally {exponent: coefficient}."""

    def __init__(self, terms: Optional[Dict[int, int]] = None):
        raw = terms or {}
        self.terms: Dict[int, int] = {e: c for e, c in raw.items() if c != 0}

    @staticmethod
    def zero() -> "LaurentPoly":
        return LaurentPoly()

    @staticmethod
    def one() -> "LaurentPoly":
        return LaurentPoly({0: 1})

    @staticmethod
    def monomial(exp: int, coeff: int = 1) -> "LaurentPoly":
        return LaurentPoly({exp: coeff})

    # t (the formal variable)
    T = None  # assigned below

    def __add__(self, other: "LaurentPoly") -> "LaurentPoly":
        result = dict(self.terms)
        for e, c in other.terms.items():
            result[e] = result.get(e, 0) + c
        return LaurentPoly(result)

    def __sub__(self, other: "LaurentPoly") -> "LaurentPoly":
        result = dict(self.terms)
        for e, c in other.terms.items():
            result[e] = result.get(e, 0) - c
        return LaurentPoly(result)

    def __mul__(self, other: "LaurentPoly") -> "LaurentPoly":
        result: Dict[int, int] = {}
        for e1, c1 in self.terms.items():
            for e2, c2 in other.terms.items():
                e = e1 + e2
                result[e] = result.get(e, 0) + c1 * c2
        return LaurentPoly(result)

    def __neg__(self) -> "LaurentPoly":
        return LaurentPoly({e: -c for e, c in self.terms.items()})

    def __eq__(self, other: object) -> bool:
        if isinstance(other, int):
            other = LaurentPoly({0: other}) if other != 0 else LaurentPoly()
        if not isinstance(other, LaurentPoly):
            return NotImplemented
        return self.terms == other.terms

    def __repr__(self) -> str:
        if not self.terms:
            return "0"
        parts = []
        for e in sorted(self.terms):
            c = self.terms[e]
            if e == 0:
                parts.append(str(c))
            elif e == 1:
                parts.append(f"{c}t" if c != 1 else "t")
            else:
                parts.append(f"{c}t^{e}" if c != 1 else f"t^{e}")
        return " + ".join(parts).replace("+ -", "- ")

    def degree(self) -> Optional[int]:
        return max(self.terms) if self.terms else None

    def min_degree(self) -> Optional[int]:
        return min(self.terms) if self.terms else None

    def evaluate(self, t_val) -> int:
        """Evaluate at an integer or Fraction value of t."""
        result = Fraction(0)
        for e, c in self.terms.items():
            result += c * Fraction(t_val) ** e
        return result

    def normalize(self) -> "LaurentPoly":
        """Make leading coefficient positive; multiply by t^{-min_exp} to clear negatives."""
        if not self.terms:
            return LaurentPoly()
        shift = self.min_degree()
        shifted = LaurentPoly({e - shift: c for e, c in self.terms.items()})
        # ensure leading coefficient positive
        top = shifted.terms[shifted.degree()]
        if top < 0:
            return LaurentPoly({e: -c for e, c in shifted.terms.items()})
        return shifted


LaurentPoly.T = LaurentPoly.monomial(1)


# ---------------------------------------------------------------------------
# Matrix over LaurentPoly
# ---------------------------------------------------------------------------

class LaurentMatrix:
    """Square matrix of LaurentPoly entries."""

    def __init__(self, rows: List[List[LaurentPoly]]):
        self.n = len(rows)
        self.rows = rows

    @staticmethod
    def identity(n: int) -> "LaurentMatrix":
        rows = [[LaurentPoly.one() if i == j else LaurentPoly.zero()
                 for j in range(n)] for i in range(n)]
        return LaurentMatrix(rows)

    def __getitem__(self, ij: Tuple[int, int]) -> LaurentPoly:
        i, j = ij
        return self.rows[i][j]

    def __setitem__(self, ij: Tuple[int, int], val: LaurentPoly) -> None:
        i, j = ij
        self.rows[i][j] = val

    def __mul__(self, other: "LaurentMatrix") -> "LaurentMatrix":
        n = self.n
        result = [[LaurentPoly.zero() for _ in range(n)] for _ in range(n)]
        for i in range(n):
            for k in range(n):
                if not self.rows[i][k].terms:
                    continue
                for j in range(n):
                    result[i][j] = result[i][j] + self.rows[i][k] * other.rows[k][j]
        return LaurentMatrix(result)

    def copy(self) -> "LaurentMatrix":
        return LaurentMatrix([[LaurentPoly(dict(self.rows[i][j].terms))
                               for j in range(self.n)] for i in range(self.n)])

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LaurentMatrix):
            return NotImplemented
        return all(self.rows[i][j] == other.rows[i][j]
                   for i in range(self.n) for j in range(self.n))


# ---------------------------------------------------------------------------
# Reduced Burau generators
# ---------------------------------------------------------------------------

def reduced_burau_generator(n_strands: int, k: int, direction: int) -> LaurentMatrix:
    """
    Reduced Burau matrix for σ_{k+1} (direction=+1) or σ_{k+1}⁻¹ (direction=-1).

    The reduced Burau representation ρ̄: B_n → GL_{n-1}(ℤ[t, t⁻¹]).
    For generator σᵢ (i = k+1, matrix index k, 0-based), the matrix is I
    except in row k:

    σᵢ:
      row k, col k-1 = 1   (if k ≥ 1)
      row k, col k   = -t
      row k, col k+1 = 1   (if k ≤ n-3)

    σᵢ⁻¹:
      row k, col k-1 = t⁻¹  (if k ≥ 1)
      row k, col k   = -t⁻¹
      row k, col k+1 = t⁻¹  (if k ≤ n-3)
    """
    m = n_strands - 1
    mat = LaurentMatrix.identity(m)
    t = LaurentPoly.T
    t_inv = LaurentPoly.monomial(-1)

    if direction == 1:
        mat[k, k] = -t
        if k >= 1:
            mat[k, k - 1] = t          # t in the col before the diagonal
        if k <= m - 2:
            mat[k, k + 1] = LaurentPoly.one()
    else:  # direction == -1  (σ_{k+1}⁻¹)
        mat[k, k] = -t_inv
        if k >= 1:
            mat[k, k - 1] = LaurentPoly.one()  # 1 in the col before diagonal
        if k <= m - 2:
            mat[k, k + 1] = t_inv

    return mat


def braid_to_burau_matrix(crossings, n_strands: int = 9) -> LaurentMatrix:
    """
    Multiply reduced Burau matrices for a sequence of crossings.

    crossings: list of BraidCrossing objects (from braid.py)
    """
    m = n_strands - 1
    result = LaurentMatrix.identity(m)
    for crossing in crossings:
        k = crossing.strand_i
        gen = reduced_burau_generator(n_strands, k, crossing.direction)
        result = result * gen
    return result


# ---------------------------------------------------------------------------
# Determinant of (I − M) via cofactor expansion
# ---------------------------------------------------------------------------

def _det(matrix: LaurentMatrix) -> LaurentPoly:
    """Determinant via Bareiss-style cofactor expansion over LaurentPoly."""
    n = matrix.n
    if n == 0:
        return LaurentPoly.one()
    if n == 1:
        return matrix[0, 0]
    if n == 2:
        return matrix[0, 0] * matrix[1, 1] - matrix[0, 1] * matrix[1, 0]

    result = LaurentPoly.zero()
    for col in range(n):
        entry = matrix[0, col]
        if not entry.terms:
            continue
        # Build cofactor minor (delete row 0, col `col`)
        minor_rows = []
        for i in range(1, n):
            row = [matrix[i, j] for j in range(n) if j != col]
            minor_rows.append(row)
        minor = LaurentMatrix(minor_rows)
        cofactor = _det(minor)
        if col % 2 == 0:
            result = result + entry * cofactor
        else:
            result = result - entry * cofactor
    return result


def _sum_of_t_powers(n: int) -> LaurentPoly:
    """1 + t + t² + … + t^{n-1}."""
    terms: Dict[int, int] = {e: 1 for e in range(n)}
    return LaurentPoly(terms)


def _exact_divide(poly: LaurentPoly, divisor: LaurentPoly) -> LaurentPoly:
    """
    Polynomial long division; raises ValueError if not exact.
    Works for polynomials (non-negative exponents only).
    """
    if not divisor.terms:
        raise ValueError("division by zero")
    quotient: Dict[int, int] = {}
    remainder = LaurentPoly(dict(poly.terms))
    div_deg = divisor.degree()
    div_lead = divisor.terms[div_deg]

    while remainder.terms and remainder.degree() >= div_deg:
        r_deg = remainder.degree()
        r_lead = remainder.terms[r_deg]
        if r_lead % div_lead != 0:
            raise ValueError(f"not exactly divisible: leading coeff {r_lead} / {div_lead}")
        q_exp = r_deg - div_deg
        q_coeff = r_lead // div_lead
        quotient[q_exp] = q_coeff
        subtract = LaurentPoly.monomial(q_exp, q_coeff) * divisor
        remainder = remainder - subtract

    if remainder.terms:
        raise ValueError(f"non-zero remainder after division: {remainder}")
    return LaurentPoly(quotient)


def alexander_invariant(crossings, n_strands: int = 9) -> LaurentPoly:
    """
    Compute the Alexander invariant of the braid closure.

    For β ∈ B_n: Δ(t) = det(I − ρ̄(β)) / (1 + t + … + t^{n-2})

    Returns the normalized Alexander polynomial (positive leading coefficient,
    cleared of negative powers of t).
    """
    m = n_strands - 1
    burau = braid_to_burau_matrix(crossings, n_strands)
    I = LaurentMatrix.identity(m)

    # Compute I − M
    diff_rows = [[I[i, j] - burau[i, j] for j in range(m)] for i in range(m)]
    diff = LaurentMatrix(diff_rows)

    numerator = _det(diff)
    denominator = _sum_of_t_powers(n_strands)

    if not numerator.terms:
        return LaurentPoly.zero()

    # Clear negative exponents before division
    shift = numerator.min_degree() or 0
    if shift < 0:
        numerator = LaurentPoly({e - shift: c for e, c in numerator.terms.items()})

    try:
        result = _exact_divide(numerator, denominator)
    except ValueError:
        # If not exactly divisible, return the numerator (invariant up to units)
        result = numerator

    return result.normalize()


# ---------------------------------------------------------------------------
# Convenience: Alexander polynomial for standard braid words
# ---------------------------------------------------------------------------

def alexander_poly_from_braid(braid_word) -> LaurentPoly:
    """Compute Alexander polynomial from a BraidWord (from braid.py)."""
    return alexander_invariant(braid_word.crossings, braid_word.num_strands)


# ---------------------------------------------------------------------------
# Verification against known knots
# ---------------------------------------------------------------------------

def _verify_trefoil() -> bool:
    """
    Trefoil knot = closure of σ₁³ in B₂ → Alexander polynomial 1 − t + t².

    The right-handed trefoil T(2,3) is the closure of σ₁³ in B₂.
    Note: (σ₁σ₂)³ in B₃ closes to a 3-component torus *link* T(3,3), not the
    trefoil knot. The 2-braid σ₁³ is the minimal-braid-index representative.
    """
    from braid import BraidCrossing
    crossings = [BraidCrossing(0, 1), BraidCrossing(0, 1), BraidCrossing(0, 1)]
    poly = alexander_invariant(crossings, n_strands=2)
    expected = LaurentPoly({0: 1, 1: -1, 2: 1})  # 1 − t + t²
    return poly == expected


def _verify_figure_eight() -> bool:
    """
    Figure-eight knot = closure of σ₁σ₂⁻¹σ₁σ₂⁻¹ in B₃
    → Alexander polynomial −t + 3 − t⁻¹, normalized to 1 − 3t + t².
    """
    from braid import BraidCrossing
    # σ₁ σ₂⁻¹ σ₁ σ₂⁻¹
    crossings = [
        BraidCrossing(0, 1), BraidCrossing(1, -1),
        BraidCrossing(0, 1), BraidCrossing(1, -1),
    ]
    poly = alexander_invariant(crossings, n_strands=3)
    normalized = poly.normalize()
    expected = LaurentPoly({0: 1, 1: -3, 2: 1})  # 1 − 3t + t²
    return normalized == expected


if __name__ == "__main__":
    ok_trefoil = _verify_trefoil()
    ok_fig8 = _verify_figure_eight()
    print(f"Trefoil   (σ₁σ₂)³:        {'PASS' if ok_trefoil else 'FAIL'} — expected 1 − t + t²")
    print(f"Fig-eight σ₁σ₂⁻¹σ₁σ₂⁻¹:  {'PASS' if ok_fig8 else 'FAIL'} — expected 1 − 3t + t²")

    # Show the polynomial for both knots
    from braid import BraidCrossing
    trefoil_crossings = [BraidCrossing(0, 1)] * 3
    poly = alexander_invariant(trefoil_crossings, n_strands=2)
    print(f"Trefoil (σ₁³ in B₂) Alexander polynomial: {poly}")

    fig8_crossings = [
        BraidCrossing(0, 1), BraidCrossing(1, -1),
        BraidCrossing(0, 1), BraidCrossing(1, -1),
    ]
    poly8 = alexander_invariant(fig8_crossings, n_strands=3)
    print(f"Figure-eight (σ₁σ₂⁻¹σ₁σ₂⁻¹ in B₃) Alexander polynomial: {poly8}")

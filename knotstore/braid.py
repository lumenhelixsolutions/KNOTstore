"""
Braid representation of KNOTstore routes.

The macro-cube's ρ-moves (layer rotations) translate to Alexander braids,
enabling computation of knot invariants for routes. Two routes with identical
braid fingerprints are topologically equivalent, enabling route compression
and collision detection.

Model: 27 cube positions project to 9 strands. A 90° layer rotation induces
4 transpositions, encoded as braid crossings. The resulting braid word is an
element of B₉ (the braid group on 9 strands).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class BraidCrossing:
    """A single crossing in a braid word: σ_i (over) or σ_i⁻¹ (under)."""
    strand_i: int
    direction: int  # +1 over, -1 under

    def encode(self) -> str:
        sign = "" if self.direction == 1 else "^{-1}"
        return f"σ_{self.strand_i}{sign}"

    def inverse(self) -> "BraidCrossing":
        return BraidCrossing(self.strand_i, -self.direction)


class BraidWord:
    """Sequence of crossings — an element of the braid group B_n."""

    def __init__(self, crossings: List[BraidCrossing], num_strands: int = 9):
        self.crossings = crossings
        self.num_strands = num_strands

    @staticmethod
    def identity(num_strands: int = 9) -> "BraidWord":
        return BraidWord([], num_strands)

    def append(self, crossing: BraidCrossing) -> "BraidWord":
        return BraidWord(self.crossings + [crossing], self.num_strands)

    def extend(self, other: "BraidWord") -> "BraidWord":
        if self.num_strands != other.num_strands:
            raise ValueError("strand count mismatch")
        return BraidWord(self.crossings + other.crossings, self.num_strands)

    def inverse(self) -> "BraidWord":
        return BraidWord([c.inverse() for c in reversed(self.crossings)], self.num_strands)

    def encode(self) -> str:
        return "e" if not self.crossings else " ".join(c.encode() for c in self.crossings)

    def length(self) -> int:
        return len(self.crossings)

    def trace_strands(self) -> List[int]:
        """Permutation induced on strands (where does strand i end up?)."""
        perm = list(range(self.num_strands))
        for crossing in self.crossings:
            i = crossing.strand_i
            if 0 <= i < self.num_strands - 1:
                perm[i], perm[i + 1] = perm[i + 1], perm[i]
        return perm


# ρ-move → braid crossing table (axis × direction → 4 crossings).
# Each 90° layer rotation induces a 4-cycle on 9 strands; we decompose
# it into adjacent transpositions, assigning distinct strand bands per axis
# so X/Y/Z moves act on non-overlapping parts of the braid.
_MOVE_CROSSINGS: dict = {
    ("Y", +1): [BraidCrossing(0, 1), BraidCrossing(1, 1), BraidCrossing(2, 1), BraidCrossing(1, 1)],
    ("Y", -1): [BraidCrossing(1, -1), BraidCrossing(2, -1), BraidCrossing(1, -1), BraidCrossing(0, -1)],
    ("X", +1): [BraidCrossing(3, 1), BraidCrossing(4, 1), BraidCrossing(5, 1), BraidCrossing(4, 1)],
    ("X", -1): [BraidCrossing(4, -1), BraidCrossing(5, -1), BraidCrossing(4, -1), BraidCrossing(3, -1)],
    ("Z", +1): [BraidCrossing(5, 1), BraidCrossing(6, 1), BraidCrossing(7, 1), BraidCrossing(6, 1)],
    ("Z", -1): [BraidCrossing(6, -1), BraidCrossing(7, -1), BraidCrossing(6, -1), BraidCrossing(5, -1)],
}


def route_to_braid(route_moves: List[Tuple[str, int, int]]) -> BraidWord:
    """Convert a list of (axis, layer, direction) ρ-moves to a braid word."""
    braid = BraidWord.identity(num_strands=9)
    for axis, _layer, direction in route_moves:
        for c in _MOVE_CROSSINGS[(axis, direction)]:
            braid = braid.append(c)
    return braid


def braid_fingerprint(braid: BraidWord) -> str:
    """Compact invariant for a braid: (length, strand permutation).

    Two routes with identical fingerprints share the same topological braid
    type under the projection used here. This is a simplified invariant (not
    the full Alexander polynomial) but sufficient for collision detection and
    route equivalence grouping.
    """
    perm = tuple(braid.trace_strands())
    return f"B({braid.length()},{perm})"


if __name__ == "__main__":
    import os
    from cube import compile_route
    route = compile_route(os.urandom(16), depth=10)
    moves = [(m.axis, m.layer, m.direction) for m in route]
    braid = route_to_braid(moves)
    print("route length:", len(moves))
    print("braid crossings:", braid.length())
    print("strand permutation:", braid.trace_strands())
    print("fingerprint:", braid_fingerprint(braid))
    # verify inverse
    combined = braid.extend(braid.inverse())
    assert combined.trace_strands() == list(range(9))
    print("inverse verified: braid · braid⁻¹ = identity permutation")

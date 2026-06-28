"""
Reversible 32.C.U.B.I.T. macro-cube — a *working* implementation.

In the draft (and the earlier prototype) the rho-moves were never applied to
anything: `compile_route` produced RhoMove objects only so they could be
stringified into hash input. The "reversible macro-cube manifold" was therefore
notational. This module makes it real: an actual 27-subcube / 162-face state
that rho-moves permute, with measured reversibility.

Model: 27 subcubes at positions (x,y,z) in {-1,0,1}^3, each carrying an
orientation = which of its 6 home faces currently points along each physical
direction (+X,-X,+Y,-Y,+Z,-Z). A move rho(axis,layer,dir) rotates the 9 subcubes
whose coordinate along `axis` equals `layer` by 90*dir degrees about that axis,
updating BOTH their positions and their orientations. Every move is a bijection
over the full 27*6 = 162-face state, so routes are exactly invertible. (Prop 2
of the draft becomes `test_*` facts rather than an assertion.)

Stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import List, Tuple

# physical directions
DIRV: Tuple[Tuple[int, int, int], ...] = (
    (1, 0, 0), (-1, 0, 0),   # +X -X
    (0, 1, 0), (0, -1, 0),   # +Y -Y
    (0, 0, 1), (0, 0, -1),   # +Z -Z
)
_DIR_INDEX = {v: i for i, v in enumerate(DIRV)}
AXIS_IDX = {"X": 0, "Y": 1, "Z": 2}


@dataclass(frozen=True)
class RhoMove:
    axis: str
    layer: int
    direction: int

    def inverse(self) -> "RhoMove":
        return RhoMove(self.axis, self.layer, -self.direction)

    def encode(self) -> str:
        return f"{self.axis}{self.layer:+d}{self.direction:+d}"


def _rot(axis: str, v: Tuple[int, int, int], s: int) -> Tuple[int, int, int]:
    """Rotate vector v by 90*s degrees about `axis` (right-hand rule)."""
    x, y, z = v
    if axis == "X":
        return (x, -z, y) if s == 1 else (x, z, -y)
    if axis == "Y":
        return (z, y, -x) if s == 1 else (-z, y, x)
    return (-y, x, z) if s == 1 else (y, -x, z)  # Z


def _pos_of(p: int) -> Tuple[int, int, int]:
    return (p // 9 - 1, (p % 9) // 3 - 1, p % 3 - 1)


def _index(pos: Tuple[int, int, int]) -> int:
    x, y, z = pos
    return (x + 1) * 9 + (y + 1) * 3 + (z + 1)


class MacroCube:
    def __init__(self):
        # cells[position] = (subcube_id, orientation) where orientation[d] is the
        # home-face label currently showing along physical direction d.
        self.cells: List[Tuple[int, Tuple[int, ...]]] = [
            (p, (0, 1, 2, 3, 4, 5)) for p in range(27)
        ]

    def copy(self) -> "MacroCube":
        c = MacroCube()
        c.cells = list(self.cells)
        return c

    def apply_move(self, m: RhoMove) -> "MacroCube":
        a = AXIS_IDX[m.axis]
        perm = [_DIR_INDEX[_rot(m.axis, DIRV[d], m.direction)] for d in range(6)]
        new = list(self.cells)
        for p in range(27):
            pos = _pos_of(p)
            if pos[a] != m.layer:
                continue
            sub_id, orient = self.cells[p]
            new_orient = [0] * 6
            for d in range(6):
                new_orient[perm[d]] = orient[d]
            new[_index(_rot(m.axis, pos, m.direction))] = (sub_id, tuple(new_orient))
        self.cells = new
        return self

    def apply_route(self, route: List[RhoMove]) -> "MacroCube":
        for m in route:
            self.apply_move(m)
        return self

    @staticmethod
    def inverse_route(route: List[RhoMove]) -> List[RhoMove]:
        return [m.inverse() for m in reversed(route)]

    def state_bytes(self) -> bytes:
        out = bytearray()
        for sub_id, orient in self.cells:
            out.append(sub_id)
            out.extend(orient)
        return bytes(out)  # 27 * 7 = 189 bytes

    def fingerprint(self) -> str:
        return sha256(self.state_bytes()).hexdigest()

    def is_identity(self) -> bool:
        return self.cells == MacroCube().cells

    def faces_moved(self, other: "MacroCube") -> int:
        """Number of the 162 faces whose (subcube, home-face) occupant differs."""
        moved = 0
        for (sid_a, or_a), (sid_b, or_b) in zip(self.cells, other.cells):
            for d in range(6):
                if (sid_a, or_a[d]) != (sid_b, or_b[d]):
                    moved += 1
        return moved


def compile_route(seed: bytes, depth: int, person: bytes = b"LENS64S_CUBE") -> List[RhoMove]:
    """Deterministically expand a seed into a rho-route that is actually a valid
    sequence of cube moves (layers in {-1,0,1}, dirs in {-1,+1})."""
    from hashlib import blake2b
    material = blake2b(seed, digest_size=64, person=person).digest()
    axes = ("X", "Y", "Z")
    layers = (-1, 0, 1)
    dirs = (-1, 1)
    route = []
    for i in range(depth):
        b0 = material[(3 * i) % 64]
        b1 = material[(3 * i + 1) % 64]
        b2 = material[(3 * i + 2) % 64]
        route.append(RhoMove(axes[b0 % 3], layers[b1 % 3], dirs[b2 % 2]))
    return route


if __name__ == "__main__":
    import os
    c = MacroCube()
    route = compile_route(os.urandom(16), depth=12)
    c.apply_route(route)
    print("after route, faces moved vs solved:", c.faces_moved(MacroCube()))
    c.apply_route(MacroCube.inverse_route(route))
    print("after inverse, is_identity:", c.is_identity())

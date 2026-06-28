"""
Reversible provenance accumulator built on the macro-cube.

The draft (section 12.4) proposes provenance as H_{t+1} = F(H_t, rho_t): each
transformation of an artifact advances a coordinate. Here that coordinate is a
real cube state, and because every move is invertible the accumulator has a
property a one-way hash chain (H_{t+1} = hash(H_t, op)) does NOT:

  * Rollback: given the current state and an event's route, you can recover the
    EXACT prior state (apply the inverse route). A hash chain is one-way -- you
    cannot recover H_t from H_{t+1}.
  * Replay-to-origin: rolling back the whole lineage returns to the identity
    cube, so a claimed lineage can be verified end to end in either direction.
  * Order sensitivity: cube moves do not commute, so reordering events changes
    the final fingerprint (re-ordered lineage is detectable).

Honest scope: the cube makes provenance *reversible and order-sensitive*; it is
not itself a security primitive -- tamper resistance still rests on the hash used
for the per-event route derivation and the fingerprint. What the cube adds over a
plain hash chain is invertibility, not cryptographic strength.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from cube import MacroCube, RhoMove, compile_route


@dataclass
class Step:
    event: str
    route: List[RhoMove]
    fingerprint_before: str
    fingerprint_after: str


class ProvenanceLog:
    """Forward-builds a reversible provenance chain over a lineage of events."""

    def __init__(self, route_depth: int = 8):
        self.route_depth = route_depth
        self.cube = MacroCube()
        self.steps: List[Step] = []

    def origin(self) -> str:
        return MacroCube().fingerprint()

    def _route_for(self, event: str, before_fp: str) -> List[RhoMove]:
        # route depends on the event AND the current state -> path-dependent
        seed = (event + "|" + before_fp).encode()
        return compile_route(seed, self.route_depth)

    def add(self, event: str) -> Step:
        before = self.cube.fingerprint()
        route = self._route_for(event, before)
        self.cube.apply_route(route)
        step = Step(event, route, before, self.cube.fingerprint())
        self.steps.append(step)
        return step

    def fingerprint(self) -> str:
        return self.cube.fingerprint()

    def rollback(self) -> Step:
        """Undo the last event and recover the exact prior fingerprint."""
        if not self.steps:
            raise IndexError("nothing to roll back")
        step = self.steps.pop()
        self.cube.apply_route(MacroCube.inverse_route(step.route))
        if self.cube.fingerprint() != step.fingerprint_before:
            raise ValueError("rollback did not reproduce the prior state (tamper?)")
        return step

    def verify_chain(self) -> bool:
        """Replay forward from identity; every recorded fingerprint must match."""
        c = MacroCube()
        if c.fingerprint() != (self.steps[0].fingerprint_before if self.steps
                               else c.fingerprint()):
            return False
        for s in self.steps:
            if c.fingerprint() != s.fingerprint_before:
                return False
            c.apply_route(s.route)
            if c.fingerprint() != s.fingerprint_after:
                return False
        return True


def one_way_chain(lineage: List[str]) -> str:
    """Baseline: a conventional one-way hash chain, for contrast. It is forward-
    only -- there is no inverse, so no rollback and no replay-to-origin."""
    from hashlib import sha256
    h = sha256(b"origin").hexdigest()
    for ev in lineage:
        h = sha256((h + "|" + ev).encode()).hexdigest()
    return h


if __name__ == "__main__":
    lineage = ["raw_ingest", "clean_nulls", "normalize", "train_split", "plot"]

    log = ProvenanceLog()
    print("origin fingerprint:", log.origin()[:16])
    for ev in lineage:
        s = log.add(ev)
        print(f"  + {ev:12s} -> {s.fingerprint_after[:16]}")
    print("chain verifies forward:", log.verify_chain())

    # Rollback: recover each prior fingerprint exactly, all the way to origin.
    while log.steps:
        s = log.rollback()
        print(f"  - rolled back {s.event:12s} -> now {log.fingerprint()[:16]}")
    print("rolled back to identity:", log.cube.is_identity())

    # Order sensitivity: swapping two events changes the final fingerprint.
    a = ProvenanceLog()
    for ev in lineage:
        a.add(ev)
    b = ProvenanceLog()
    swapped = lineage[:2][::-1] + lineage[2:]
    for ev in swapped:
        b.add(ev)
    print("reordered lineage -> different fingerprint:",
          a.fingerprint() != b.fingerprint())
    print("(one-way baseline is forward-only: no rollback, no replay-to-origin)")

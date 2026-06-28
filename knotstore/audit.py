"""
Phase-duality audit log.

Strengthens forensic auditability using Cauldron's phase duality:
every event produces two fingerprints (forward p=0, dual p=1). The log
is order-sensitive (reordering changes fingerprints), tamper-detectable
(chain verification catches any modification), and reversible (rollback
forks the chain to an earlier link).

This is a stand-alone module — it does not modify KNOTstore internals.
Integration point: LORE security in MYdev (biometric-drift state machine,
fault latching, containment decisions).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import List, Optional
import json
import time


_ORIGIN = sha256(b"cauldron-origin").hexdigest()


@dataclass
class AuditEvent:
    """A single auditable event (ACCESS, COMMIT, VIOLATION, ROLLBACK, etc.)."""
    event_id: str
    event_type: str
    actor: str
    data: str
    timestamp: float = field(default_factory=time.time)
    phase: int = 0  # 0 = forward, 1 = dual

    def fingerprint(self) -> str:
        material = f"{self.event_id}|{self.event_type}|{self.actor}|{self.data}|{self.phase}"
        return sha256(material.encode()).hexdigest()

    def dual_fingerprint(self) -> str:
        material = f"{self.event_id}|{self.event_type}|{self.actor}|{self.data}|{1 - self.phase}"
        return sha256(material.encode()).hexdigest()


@dataclass
class ChainLink:
    """One link: prior_fp + event_fp → forward and dual fingerprints."""
    event: AuditEvent
    prior_fp: str
    forward_fp: str
    dual_fp: str

    @classmethod
    def create(cls, event: AuditEvent, prior_fp: str) -> "ChainLink":
        forward_fp = sha256((prior_fp + event.fingerprint()).encode()).hexdigest()
        dual_fp = sha256((prior_fp + event.dual_fingerprint()).encode()).hexdigest()
        return cls(event=event, prior_fp=prior_fp,
                   forward_fp=forward_fp, dual_fp=dual_fp)


class AuditLog:
    """Reversible, order-sensitive audit chain with phase-duality fingerprints."""

    def __init__(self):
        self.links: List[ChainLink] = []
        self.phase: int = 0  # 0 = forward, 1 = dual

    def add(self, event: AuditEvent) -> ChainLink:
        event.phase = self.phase
        prior = self.links[-1].forward_fp if self.links else _ORIGIN
        link = ChainLink.create(event, prior)
        self.links.append(link)
        return link

    def fingerprint(self) -> str:
        if not self.links:
            return _ORIGIN
        return (self.links[-1].forward_fp if self.phase == 0
                else self.links[-1].dual_fp)

    def flip_phase(self) -> None:
        """Toggle between forward (p=0) and dual (p=1) phase."""
        self.phase = 1 - self.phase

    def verify(self) -> bool:
        """Recompute the chain; return False if any link is tampered."""
        prior = _ORIGIN
        for link in self.links:
            if link.prior_fp != prior:
                return False
            expected = sha256((prior + link.event.fingerprint()).encode()).hexdigest()
            if link.forward_fp != expected:
                return False
            prior = link.forward_fp
        return True

    def reorder_detected(self, other: "AuditLog") -> bool:
        """True when this log and other have the same events in different order."""
        ids_self = [l.event.event_id for l in self.links]
        ids_other = [l.event.event_id for l in other.links]
        return (sorted(ids_self) == sorted(ids_other)) and (ids_self != ids_other)

    def rollback_to(self, index: int) -> "AuditLog":
        """Fork the log, discarding all links after index."""
        if not 0 <= index <= len(self.links):
            raise ValueError(f"index {index} out of range")
        forked = AuditLog()
        forked.links = list(self.links[:index])
        forked.phase = self.phase
        return forked


if __name__ == "__main__":
    log = AuditLog()
    for eid, etype, actor in [
        ("e1", "ACCESS", "alice"),
        ("e2", "COMMIT", "system"),
        ("e3", "ACCESS", "alice"),
    ]:
        ev = AuditEvent(event_id=eid, event_type=etype, actor=actor, data="{}")
        link = log.add(ev)
        print(f"{eid} ({etype}) → fwd:{link.forward_fp[:12]}… dual:{link.dual_fp[:12]}…")

    print(f"\nchain verifies: {log.verify()}")
    log.flip_phase()
    print(f"dual fingerprint: {log.fingerprint()[:16]}…")

    # order sensitivity
    log2 = AuditLog()
    for eid, etype, actor in [("e3", "ACCESS", "alice"), ("e1", "ACCESS", "alice"), ("e2", "COMMIT", "system")]:
        log2.add(AuditEvent(event_id=eid, event_type=etype, actor=actor, data="{}"))
    print(f"reorder detected: {log.reorder_detected(log2)}")

    # rollback
    forked = log.rollback_to(1)
    print(f"rolled back to link 1; chain verifies: {forked.verify()}")

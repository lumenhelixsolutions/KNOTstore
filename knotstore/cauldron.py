"""
Cauldron canonical semantics and Cauldron-enriched manifest.

The Cauldron is a 10-state reversible system (digits 0–9) with symmetry group
D₈ × ℤ₂ (order 32). Its canonical ordering is derived from the quadratic moment
function I(a,b) = a² + b², which assigns a unique value to each δ-pair and fixes
their order without any arbitrary choice. This is the "parameter-free" property
claimed in the CORE-32 / RUBIC papers.

Manifests can be enriched with Cauldron semantics as an optional overlay, adding:
  - Canonical δ-pair ordering proof (moment values)
  - Phase-pair metadata (p=0 forward, p=1 dual)
  - Symmetry group signature
  - Audit fingerprint trail

Backward compatible: existing KNOTstore manifests parse as degenerate Cauldron
manifests (with default semantics and empty audit trail).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Dict, List, Optional, Tuple
import json

# The four canonical δ-pairs, ordered by I(a,b) = a² + b²
DELTA_PAIRS: Tuple[Tuple[int, int], ...] = (
    (2, 5),   # I = 29   (innermost)
    (4, 7),   # I = 65
    (3, 8),   # I = 73
    (6, 9),   # I = 117  (outermost)
)

CAULDRON_AXIS = (0, 1)   # the core 2-state subspace
CAULDRON_RING = tuple(range(2, 10))  # the 8-state outer ring


def quadratic_moment(a: int, b: int) -> int:
    """Canonical ordering function. Distinct values guarantee strict total order."""
    return a * a + b * b


def cauldron_is_canonical() -> bool:
    """Prove canonicality: all moment values are distinct."""
    values = [quadratic_moment(a, b) for a, b in DELTA_PAIRS]
    return len(set(values)) == len(values)


@dataclass(frozen=True)
class CauldronSemantics:
    """Immutable canonical descriptor for the Cauldron system."""

    # Canonical ordering proof
    moment_values: Tuple[int, ...] = field(
        default_factory=lambda: tuple(quadratic_moment(a, b) for a, b in DELTA_PAIRS)
    )
    # Symmetry group
    symmetry_group: str = "D₈ × ℤ₂"

    def to_dict(self) -> dict:
        pairs = [f"{{{a},{b}}}" for a, b in DELTA_PAIRS]
        return {
            "symmetry_group": self.symmetry_group,
            "delta_pairs": {
                pairs[i]: {
                    "moment": self.moment_values[i],
                    "canonical_rank": i + 1,
                    "phase_0": DELTA_PAIRS[i][0],
                    "phase_1": DELTA_PAIRS[i][1],
                }
                for i in range(len(DELTA_PAIRS))
            },
            "canonical": cauldron_is_canonical(),
            "axis": list(CAULDRON_AXIS),
            "ring": list(CAULDRON_RING),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def fingerprint(self) -> str:
        """Deterministic fingerprint of the canonical semantics."""
        return sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()


DEFAULT_SEMANTICS = CauldronSemantics()


@dataclass
class CauldronManifest:
    """KNOTstore manifest enriched with Cauldron canonical semantics.

    Drop-in overlay: construct from any KNOTstore Manifest dict via
    CauldronManifest.from_manifest(m). Serializes back to JSON that round-trips
    through the standard KNOTstore codec (extra fields are ignored on decode).
    """

    # --- core KNOTstore fields (passed through) ---
    knotstore_manifest: dict

    # --- Cauldron enrichment ---
    semantics: CauldronSemantics = field(default_factory=CauldronSemantics)
    phase: int = 0  # 0 = forward, 1 = dual

    # audit fingerprint trail (fingerprint at each commit point)
    audit_trail: List[str] = field(default_factory=list)

    @classmethod
    def from_manifest(cls, m) -> "CauldronManifest":
        """Lift a KNOTstore Manifest or dict to a CauldronManifest."""
        raw = json.loads(m.to_json()) if hasattr(m, "to_json") else m
        return cls(knotstore_manifest=raw)

    def commit(self, fingerprint: Optional[str] = None) -> None:
        """Record a forward-phase commit point."""
        fp = fingerprint or self._auto_fingerprint()
        self.audit_trail.append(fp)
        self.phase = 0

    def rollback(self) -> Optional[str]:
        """Undo the last commit; return the fingerprint removed."""
        if not self.audit_trail:
            return None
        fp = self.audit_trail.pop()
        self.phase = 1  # dual phase after rollback
        return fp

    def _auto_fingerprint(self) -> str:
        """Fingerprint of the current manifest + audit trail state."""
        material = json.dumps(self.knotstore_manifest, sort_keys=True)
        material += "|" + "|".join(self.audit_trail)
        return sha256(material.encode()).hexdigest()[:16]

    def current_fingerprint(self) -> str:
        return self.audit_trail[-1] if self.audit_trail else "origin"

    def to_json(self) -> str:
        data = dict(self.knotstore_manifest)
        data["cauldron"] = {
            "semantics": self.semantics.to_dict(),
            "phase": self.phase,
            "audit_trail": self.audit_trail,
        }
        return json.dumps(data, indent=2, sort_keys=True)


if __name__ == "__main__":
    print("Cauldron canonical semantics:")
    print(DEFAULT_SEMANTICS.to_json())
    print()
    print("Canonicality proof:", cauldron_is_canonical())
    print("Semantics fingerprint:", DEFAULT_SEMANTICS.fingerprint()[:16])
    print()

    # Example: lift a minimal KNOTstore manifest
    raw = {
        "version": 1, "name": "demo", "chunk_size": 256,
        "total_size": 512, "placement": "content",
        "root_digest": "abc" * 10 + "ab",
    }
    cm = CauldronManifest.from_manifest(raw)
    cm.commit("fp_initial")
    cm.commit("fp_after_op_1")
    print("Enriched manifest (excerpt):")
    print(json.dumps(json.loads(cm.to_json()).get("cauldron"), indent=2))
    print()
    fp = cm.rollback()
    print(f"Rolled back: removed {fp}")
    print(f"Phase after rollback: {cm.phase} (1 = dual)")
    print(f"Current fingerprint: {cm.current_fingerprint()}")

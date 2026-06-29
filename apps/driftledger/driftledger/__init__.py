"""DriftLedger — tamper-evident, time-travel memory for AI agents.

Every agent memory write becomes a reversible, content-addressed step. You can
roll the agent's memory back to step N, replay it, detect tampering, branch an
alternate timeline, and emit a signed audit trail.

Public surface:
    AgentLedger  — the ledger that ties reversible provenance to content-
                   addressed state storage.
"""
from __future__ import annotations

from .ledger import AgentLedger

__all__ = ["AgentLedger"]
__version__ = "0.1.0"

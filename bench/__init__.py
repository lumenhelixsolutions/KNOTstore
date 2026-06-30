"""KNOTstore reproducible benchmark suite.

Measures the headline metric of the engine and each of the four apps, emitting
machine-readable JSON plus a human-readable markdown table. Deterministic.

Run: ``python -m bench.run --quick``
"""
from __future__ import annotations

__all__ = ["benchmarks", "run"]

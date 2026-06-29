"""PrefixForge — a content-addressed LLM prompt/prefix cache with near-duplicate locality.

Exact-match prompt caches only hit on byte-identical prefixes. PrefixForge adds
a near-duplicate layer: when no exact match exists it returns the closest cached
prompt within a SimHash Hamming-distance threshold, catching the near-misses that
exact caches drop.
"""
from __future__ import annotations

from .cache import PrefixCache, Result

__all__ = ["PrefixCache", "Result"]
__version__ = "0.1.0"

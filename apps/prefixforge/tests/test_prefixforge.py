from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from prefixforge.cache import PrefixCache, normalize  # noqa: E402
from prefixforge import demo as demo_mod  # noqa: E402


def test_exact_hit(tmp_path):
    c = PrefixCache(root=str(tmp_path), persist=True)
    c.put("Hello there, world", b"cached-completion", tokens=123)
    r = c.get("Hello there, world")
    assert r.kind == "exact"
    assert r.value == b"cached-completion"
    assert r.similarity == 1.0
    assert r.tokens_saved == 123


def test_normalization_makes_trivial_variants_exact(tmp_path):
    c = PrefixCache(root=str(tmp_path), persist=True)
    c.put("Hello   World", b"v", tokens=10)
    # whitespace + casing collapse to the same key -> still exact
    r = c.get("hello world")
    assert r.kind == "exact"


def test_near_hit(tmp_path):
    c = PrefixCache(root=str(tmp_path), persist=True, threshold=8)
    base = "Summarize the following quarterly earnings report for shareholders"
    c.put(base, b"summary-blob", tokens=500)
    # A perturbed variant: punctuation + trailing suffix.
    r = c.get(base.upper() + " please. thanks!")
    assert r.kind == "near"
    assert r.value == b"summary-blob"
    assert 0.0 < r.similarity < 1.0
    assert r.tokens_saved == 500
    assert r.distance is not None and r.distance <= 8


def test_miss(tmp_path):
    c = PrefixCache(root=str(tmp_path), persist=True, threshold=8)
    c.put("Translate this message into French for me", b"fr", tokens=50)
    r = c.get("Generate a SQL query for the top customers by total revenue")
    assert r.kind == "miss"
    assert r.value is None
    assert r.similarity == 0.0
    assert r.tokens_saved == 0


def test_persistence_across_instances(tmp_path):
    root = str(tmp_path)
    c1 = PrefixCache(root=root, persist=True)
    c1.put("Explain the difference between TCP and UDP", b"answer", tokens=300)
    del c1

    c2 = PrefixCache(root=root, persist=True)
    r = c2.get("Explain the difference between TCP and UDP")
    assert r.kind == "exact"
    assert r.value == b"answer"
    assert r.tokens_saved == 300
    # near-tier also survives
    r2 = c2.get("EXPLAIN the difference between tcp and udp!!")
    assert r2.kind in ("exact", "near")


def test_embedding_fn_semantic_mode(tmp_path):
    # A deterministic toy "embedding": fixed-length char-frequency vector.
    def embed(text):
        vec = [0.0] * 26
        for ch in text:
            o = ord(ch.lower()) - ord("a")
            if 0 <= o < 26:
                vec[o] += 1.0
        return vec

    c = PrefixCache(root=str(tmp_path), persist=True, embedding_fn=embed, threshold=8)
    c.put("the quick brown fox jumps", b"v", tokens=42)
    assert c.get("the quick brown fox jumps").kind == "exact"
    # different surface, similar char profile -> near or exact, not a crash
    r = c.get("the quick brown fox jumps over")
    assert r.kind in ("exact", "near", "miss")


def test_demo_near_beats_exact():
    m = demo_mod.run(n=200, seed=42, threshold=8)
    assert m["forge_hit_rate"] > m["exact_hit_rate"]
    assert m["forge_near_hits"] > 0
    assert m["forge_tokens_saved"] > m["exact_tokens_saved"]


def test_normalize():
    assert normalize("  Hello   World  ") == "hello world"

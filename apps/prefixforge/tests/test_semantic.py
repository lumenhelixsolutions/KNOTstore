"""Coverage for the semantic / embedding_fn signature path (added in v0.2)."""
from __future__ import annotations
import os, sys, tempfile, shutil
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from prefixforge.cache import PrefixCache
from prefixforge.embed import hashing_embedding, project_to_simhash64


def test_projection_is_deterministic():
    v = hashing_embedding("summarize the attached contract", dim=128)
    assert project_to_simhash64(v) == project_to_simhash64(list(v))


def test_hashing_embedding_normalized():
    v = hashing_embedding("alpha beta gamma alpha", dim=64)
    norm = sum(x * x for x in v) ** 0.5
    assert abs(norm - 1.0) < 1e-6 or norm == 0.0


def _near_hit_for(mode, base, query, **kw):
    d = tempfile.mkdtemp()
    try:
        c = PrefixCache(root=d, mode=mode, threshold=10, persist=True, **kw)
        c.put(base, b"VALUE", tokens=100)
        return c.get(query)
    finally:
        shutil.rmtree(d)


def test_semantic_catches_reordered_prompt():
    base = "summarize the attached contract and list the key obligations and risks"
    q = "please summarize the attached contract, and also list the key obligations and risks"
    r = _near_hit_for("semantic", base, q)
    assert r.kind in ("exact", "near")
    assert r.tokens_saved == 100


def test_unrelated_prompt_misses():
    base = "summarize the attached contract and list the key obligations"
    r = _near_hit_for("semantic", base, "what time is the standup tomorrow")
    assert r.kind == "miss"


def test_embedding_fn_takes_precedence():
    # a trivial deterministic embedder; presence must not error and must hit on identity
    def embed(text):
        v = [0.0] * 32
        for w in text.lower().split():
            v[hash(w) % 32] += 1.0
        n = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / n for x in v]
    base = "alpha beta gamma delta epsilon"
    r = _near_hit_for("semantic", base, base, embedding_fn=embed)
    assert r.kind == "exact"

"""Zero-dependency embedding helpers for PrefixForge semantic mode.

Today PrefixForge hashes normalized prompt *text* (byte SimHash), which gives
*syntactic* locality: whitespace/punctuation/casing/edit variants of the same
prompt collide, but paraphrases with different surface words do not.

This module adds a cheap *word-level* path that improves on that without any
external dependency:

* :func:`hashing_embedding` — a deterministic bag-of-words **hashing
  vectorizer**. Each lowercased word is hashed into one of ``dim`` buckets with a
  signed count; the resulting vector is L2-normalized. Reordered words, added
  filler words, and partial paraphrases (shared vocabulary) land close together
  in this space — something char-shingle SimHash misses.

* :func:`project_to_simhash64` — sign-of-random-hyperplane projection of *any*
  float vector down to a 64-bit SimHash int, so the engine's ``knotcore.hamming``
  keeps working unchanged. The planes are derived deterministically from a fixed
  seed, so the projection is reproducible across processes and Python versions.

* :class:`Embedder` — a tiny structural protocol (``__call__(text) -> vector``)
  describing what a *real* embedding model must look like. Pass any callable that
  matches it as ``PrefixCache(..., embedding_fn=model.encode)``.

Honest limits: a hashing bag-of-words is **not** transformer semantics. It has no
notion of synonyms that share no characters ("car" vs "automobile"), word sense,
or order-dependent meaning. It buys cheap lexical-overlap locality for free; for
true semantic locality, plug a real model via ``embedding_fn``.

Stdlib only. Python 3.8+.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import List, Sequence

try:  # pragma: no cover - typing-only import
    from typing import Protocol

    class Embedder(Protocol):
        """Structural type for a pluggable embedding model.

        Any callable ``fn(text: str) -> Sequence[float]`` returning a
        fixed-length vector satisfies this. Example::

            cache = PrefixCache(embedding_fn=my_model.encode)
        """

        def __call__(self, text):
            # type: (str) -> Sequence[float]
            ...
except ImportError:  # pragma: no cover - Protocol added in 3.8
    Embedder = object  # type: ignore


_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text):
    # type: (str) -> List[str]
    return _WORD.findall(text.lower())


def _token_bucket(token, dim):
    # type: (str, int) -> int
    """Stable hash of ``token`` into ``[0, dim)`` (md5 -> not Python-hash-seed
    dependent, so embeddings are reproducible across processes)."""
    h = hashlib.md5(token.encode("utf-8")).digest()
    return int.from_bytes(h[:4], "big") % dim


def _token_sign(token):
    # type: (str) -> float
    """Stable +/-1 sign for ``token`` (signed hashing-trick: reduces collisions
    cancelling vs reinforcing arbitrarily)."""
    h = hashlib.md5((token + "#sign").encode("utf-8")).digest()
    return 1.0 if (h[0] & 1) else -1.0


def hashing_embedding(text, dim=256):
    # type: (str, int) -> List[float]
    """Deterministic L2-normalized bag-of-words hashing vector of ``text``.

    Parameters
    ----------
    text : str
        Input prompt. Tokenized on lowercased ``[a-z0-9]+`` runs.
    dim : int
        Output dimensionality (number of hash buckets). Default 256.

    Returns
    -------
    list[float]
        An L2-normalized vector of length ``dim``. Empty / token-less input
        yields an all-zero vector.
    """
    if dim <= 0:
        raise ValueError("dim must be positive")
    vec = [0.0] * dim
    for tok in _tokens(text):
        vec[_token_bucket(tok, dim)] += _token_sign(tok)
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0.0:
        inv = 1.0 / norm
        vec = [v * inv for v in vec]
    return vec


# --- embedding -> 64-bit SimHash bridge --------------------------------------
PROJECTION_SEED = 0x50524546  # "PREF"


def _planes(dim, seed):
    # type: (int, int) -> List[List[float]]
    """Deterministic 64 x dim Gaussian random hyperplanes via LCG + Box-Muller.

    Reproducible across processes/Python versions (does not depend on the
    ``random`` module's internals).
    """
    state = seed & 0xFFFFFFFFFFFFFFFF
    a = 6364136223846793005
    c = 1442695040888963407
    mask = 0xFFFFFFFFFFFFFFFF

    def _next_float():
        # type: () -> float
        nonlocal state
        state = (a * state + c) & mask
        return (state >> 11) / float(1 << 53)

    planes = []  # type: List[List[float]]
    for _ in range(64):
        row = []  # type: List[float]
        i = 0
        while i < dim:
            u1 = _next_float()
            u2 = _next_float()
            if u1 < 1e-12:
                u1 = 1e-12
            r = math.sqrt(-2.0 * math.log(u1))
            row.append(r * math.cos(2.0 * math.pi * u2))
            if i + 1 < dim:
                row.append(r * math.sin(2.0 * math.pi * u2))
            i += 2
        planes.append(row[:dim])
    return planes


# Cache planes per (dim, seed) so repeated projections are cheap.
_PLANE_CACHE = {}  # type: dict


def project_to_simhash64(vec, seed=PROJECTION_SEED):
    # type: (Sequence[float], int) -> int
    """Project a float vector to a 64-bit SimHash via signed random hyperplanes.

    Bit ``b`` is set iff ``dot(vec, plane_b) > 0``. The planes are deterministic
    in ``(len(vec), seed)``, so the same vector always yields the same signature
    and ``knotcore.hamming`` measures angular closeness in the embedding space.
    """
    dim = len(vec)
    if dim == 0:
        raise ValueError("cannot project an empty vector")
    key = (dim, seed)
    planes = _PLANE_CACHE.get(key)
    if planes is None:
        planes = _planes(dim, seed)
        _PLANE_CACHE[key] = planes
    sig = 0
    for b in range(64):
        plane = planes[b]
        dot = 0.0
        for i in range(dim):
            dot += vec[i] * plane[i]
        if dot > 0.0:
            sig |= (1 << b)
    return sig

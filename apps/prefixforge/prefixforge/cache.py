"""Core PrefixCache implementation.

Indexing strategy
-----------------
Every prompt is **normalized** (lowercased, whitespace collapsed) before any
hashing, so trivial variations ("Hello   world" vs "hello world") collapse to a
single key. Each entry is then indexed two ways:

* **Exact** — ``KnotStore.digest(normalized_bytes)`` is a content hash. A lookup
  whose normalized form digests to a stored key is an *exact* hit (similarity 1.0).
* **Near** — a 64-bit SimHash signature of the normalized prompt. On a miss we
  scan the signature index for the entry with the smallest Hamming distance; if
  that distance is within ``threshold`` it is a *near* hit. Similarity is
  reported as ``1 - hamming/64``.

Values are persisted content-addressed via ``knotcore.PersistentKnotStore`` (so
identical completions dedup), and the signature index is mirrored to JSON so the
cache survives restarts.

Pluggable hasher
----------------
The default path uses byte-SimHash over the normalized text (zero deps,
*syntactic* locality). Pass ``embedding_fn`` to get *semantic* locality: the
embedding vector is projected onto 64 fixed random hyperplanes and the sign bits
form the SimHash signature, so semantically close prompts land at small Hamming
distance even when their surface text differs.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from typing import Callable, Dict, List, Optional, Sequence

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
import knotcore  # noqa: E402

# Default Hamming threshold for a "near" hit on a 64-bit signature.
#
# 64-bit SimHash of independent random text sits ~32 bits apart (half the bits).
# Empirically, prompts that are genuine edits/whitespace/punctuation variants of
# one another land in the ~0..8 range, while unrelated prompts sit well above 12.
# 8 is a conservative middle ground: tight enough to reject unrelated prompts,
# loose enough to catch realistic paraphrase-by-edit near-duplicates. Tune via
# the ``threshold`` constructor argument.
DEFAULT_THRESHOLD = 8

EmbeddingFn = Callable[[str], Sequence[float]]


class Result:
    """Outcome of a :meth:`PrefixCache.get` lookup.

    Attributes
    ----------
    kind : str
        One of ``"exact"``, ``"near"`` or ``"miss"``.
    value : Optional[bytes]
        The cached blob for an exact/near hit, else ``None``.
    similarity : float
        ``1.0`` for exact, ``1 - hamming/64`` for near, ``0.0`` for miss.
    tokens_saved : int
        Token count recorded for the hit entry (``0`` on miss).
    prompt : Optional[str]
        The normalized prompt that produced the hit (``None`` on miss).
    distance : Optional[int]
        Hamming distance to the hit signature (``0`` exact, ``None`` on miss).
    """

    __slots__ = ("kind", "value", "similarity", "tokens_saved", "prompt", "distance")

    def __init__(self, kind, value=None, similarity=0.0, tokens_saved=0,
                 prompt=None, distance=None):
        # type: (str, Optional[bytes], float, int, Optional[str], Optional[int]) -> None
        self.kind = kind
        self.value = value
        self.similarity = similarity
        self.tokens_saved = tokens_saved
        self.prompt = prompt
        self.distance = distance

    @property
    def hit(self):
        # type: () -> bool
        return self.kind != "miss"

    def __repr__(self):
        # type: () -> str
        return ("Result(kind=%r, similarity=%.3f, tokens_saved=%d, distance=%r)"
                % (self.kind, self.similarity, self.tokens_saved, self.distance))


_WS = re.compile(r"\s+")


def normalize(prompt):
    # type: (str) -> str
    """Lowercase and collapse all runs of whitespace to single spaces."""
    return _WS.sub(" ", prompt.strip().lower())


def _project_embedding_to_simhash(vec, planes):
    # type: (Sequence[float], List[List[float]]) -> int
    """Sign-of-random-hyperplane-projection SimHash of an embedding vector."""
    sig = 0
    for b in range(64):
        plane = planes[b]
        dot = 0.0
        for i in range(len(vec)):
            dot += vec[i] * plane[i]
        if dot > 0.0:
            sig |= (1 << b)
    return sig


def _make_planes(dim, seed=1234567):
    # type: (int, int) -> List[List[float]]
    """Deterministic 64 x dim Gaussian-ish random hyperplanes (stdlib only).

    Uses a tiny LCG + Box-Muller so results are reproducible across processes and
    Python versions without depending on ``random`` implementation details.
    """
    state = seed & 0xFFFFFFFFFFFFFFFF
    a = 6364136223846793005
    c = 1442695040888963407
    mask = 0xFFFFFFFFFFFFFFFF

    def _next_float():
        nonlocal state
        state = (a * state + c) & mask
        # top 53 bits -> [0,1)
        return (state >> 11) / float(1 << 53)

    planes = []  # type: List[List[float]]
    for _ in range(64):
        row = []  # type: List[float]
        # Box-Muller in pairs.
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


class PrefixCache:
    """A persistent prompt cache with exact + near-duplicate retrieval.

    Parameters
    ----------
    root : str
        Directory for on-disk state (created if missing).
    threshold : int
        Maximum SimHash Hamming distance accepted as a *near* hit.
    embedding_fn : Optional[Callable[[str], Sequence[float]]]
        If supplied, signatures are derived from this embedding via random
        hyperplane projection (semantic locality) instead of byte-SimHash.
    embedding_dim : Optional[int]
        Embedding dimensionality. Inferred from the first embedding if omitted.
    persist : bool
        When ``False`` the cache is in-memory only (no disk writes).
    """

    INDEX_NAME = "index.json"

    def __init__(self, root="./.prefixforge", threshold=DEFAULT_THRESHOLD,
                 embedding_fn=None, embedding_dim=None, persist=True):
        # type: (str, int, Optional[EmbeddingFn], Optional[int], bool) -> None
        if threshold < 0 or threshold > 64:
            raise ValueError("threshold must be in 0..64")
        self.root = os.path.abspath(root)
        self.threshold = threshold
        self.embedding_fn = embedding_fn
        self.embedding_dim = embedding_dim
        self.persist = persist
        self._planes = None  # type: Optional[List[List[float]]]

        # key (digest) -> {"sig": int, "tokens": int, "prompt": str, "addr": str}
        self._index = {}  # type: Dict[str, dict]
        # in-memory value store when persistence is off
        self._mem_values = {}  # type: Dict[str, bytes]

        self._store = None  # type: Optional[object]
        if self.persist:
            os.makedirs(self.root, exist_ok=True)
            self._store = knotcore.PersistentKnotStore(self.root)
            self._load_index()

    # --- signature computation ------------------------------------------------
    def _signature(self, normalized):
        # type: (str) -> int
        if self.embedding_fn is None:
            return knotcore.simhash64(normalized.encode("utf-8"))
        vec = list(self.embedding_fn(normalized))
        if not vec:
            raise ValueError("embedding_fn returned an empty vector")
        if self.embedding_dim is None:
            self.embedding_dim = len(vec)
        if len(vec) != self.embedding_dim:
            raise ValueError("embedding dim changed: expected %d, got %d"
                             % (self.embedding_dim, len(vec)))
        if self._planes is None:
            self._planes = _make_planes(self.embedding_dim)
        return _project_embedding_to_simhash(vec, self._planes)

    @staticmethod
    def _digest(normalized):
        # type: (str) -> str
        d = knotcore.KnotStore.digest(normalized.encode("utf-8"))
        return d.hex() if isinstance(d, (bytes, bytearray)) else str(d)

    # --- persistence ----------------------------------------------------------
    def _index_path(self):
        # type: () -> str
        return os.path.join(self.root, self.INDEX_NAME)

    def _load_index(self):
        # type: () -> None
        path = self._index_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (ValueError, OSError):
            # Corrupt/partial index: start clean rather than crash.
            return
        self.embedding_dim = data.get("embedding_dim", self.embedding_dim)
        self._index = data.get("entries", {})

    def _save_index(self):
        # type: () -> None
        if not self.persist:
            return
        path = self._index_path()
        tmp = path + ".tmp"
        payload = {"embedding_dim": self.embedding_dim, "entries": self._index}
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, path)

    # --- value storage --------------------------------------------------------
    def _store_value(self, key, value):
        # type: (str, bytes) -> str
        if not self.persist:
            self._mem_values[key] = value
            return key
        manifest = self._store.put(value, name=key)  # type: ignore[union-attr]
        self._store.save_manifest(manifest)  # type: ignore[union-attr]
        return key

    def _load_value(self, key):
        # type: (str) -> bytes
        if not self.persist:
            return self._mem_values[key]
        manifest = self._store.load_manifest(key)  # type: ignore[union-attr]
        return self._store.get(manifest)  # type: ignore[union-attr]

    # --- public API -----------------------------------------------------------
    def put(self, prompt, value, tokens=0):
        # type: (str, bytes, int) -> str
        """Store ``value`` for ``prompt``. Returns the entry's exact key."""
        if not isinstance(value, (bytes, bytearray)):
            raise TypeError("value must be bytes")
        value = bytes(value)
        normalized = normalize(prompt)
        key = self._digest(normalized)
        sig = self._signature(normalized)
        addr = self._store_value(key, value)
        self._index[key] = {
            "sig": sig,
            "tokens": int(tokens),
            "prompt": normalized,
            "addr": addr,
        }
        self._save_index()
        return key

    def get(self, prompt):
        # type: (str) -> Result
        """Look up ``prompt``: exact hit, else nearest near hit, else miss."""
        normalized = normalize(prompt)
        key = self._digest(normalized)

        entry = self._index.get(key)
        if entry is not None:
            return Result(
                kind="exact",
                value=self._load_value(key),
                similarity=1.0,
                tokens_saved=entry["tokens"],
                prompt=entry["prompt"],
                distance=0,
            )

        # Near search: smallest Hamming distance over the signature index.
        sig = self._signature(normalized)
        best_key = None
        best_dist = None  # type: Optional[int]
        for k, e in self._index.items():
            d = knotcore.hamming(sig, e["sig"])
            if best_dist is None or d < best_dist:
                best_dist = d
                best_key = k

        if best_key is not None and best_dist is not None and best_dist <= self.threshold:
            e = self._index[best_key]
            return Result(
                kind="near",
                value=self._load_value(best_key),
                similarity=1.0 - best_dist / 64.0,
                tokens_saved=e["tokens"],
                prompt=e["prompt"],
                distance=best_dist,
            )

        return Result(kind="miss", value=None, similarity=0.0, tokens_saved=0,
                      prompt=None, distance=best_dist)

    def __len__(self):
        # type: () -> int
        return len(self._index)

    def __contains__(self, prompt):
        # type: (str) -> bool
        return self._digest(normalize(prompt)) in self._index

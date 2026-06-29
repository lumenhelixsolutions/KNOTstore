"""
Content-correlated placement signature for KnotStore.

The knot/delta coordinate in the draft is digest-derived, so it gives uniform
load balance but ZERO content locality: two chunks that differ by one byte get
unrelated placements. This module provides a SimHash-style signature (Charikar,
STOC 2002) whose Hamming distance tracks content similarity, so near-duplicate
content can be made to colocate.

`simhash64`  -> a 64-bit content fingerprint over byte-shingles.
`shard_of`   -> top-bits shard from a fingerprint (similar content -> same shard).

Stdlib only. See bench_locality.py for the measured locality comparison.
"""
from __future__ import annotations

from hashlib import blake2b
from typing import List


def _shingles(data: bytes, k: int) -> List[bytes]:
    if len(data) < k:
        return [data] if data else [b"\x00"]
    return [data[i:i + k] for i in range(len(data) - k + 1)]


def simhash64(data: bytes, k: int = 4) -> int:
    """64-bit SimHash. Near-duplicate inputs -> small Hamming distance."""
    acc = [0] * 64
    for sh in _shingles(data, k):
        hv = int.from_bytes(blake2b(sh, digest_size=8).digest(), "big")
        for b in range(64):
            acc[b] += 1 if (hv >> b) & 1 else -1
    sig = 0
    for b in range(64):
        if acc[b] > 0:
            sig |= (1 << b)
    return sig


def shard_of(sig: int, num_nodes: int) -> int:
    """Map a fingerprint to one of num_nodes shards using its top bits, so that
    fingerprints with equal top bits (i.e. similar content) colocate."""
    nbits = max(1, (num_nodes - 1).bit_length())  # ceil(log2(num_nodes))
    top = sig >> (64 - nbits)
    return top % num_nodes


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")  # 3.8-safe (int.bit_count is 3.10+)

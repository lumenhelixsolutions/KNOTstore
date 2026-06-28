"""
Measured benchmark harness for KnotStore.

Replaces the *illustrative* JSON in section 11.2 of the LENS-64S draft (whose
numbers were hand-picked, e.g. avg_pointer_bytes=96, pointer_compression_ratio
=0.375) with numbers that are actually measured from a run. Also measures shard
load balance, which is the only concrete claim the knot/delta layer can support.

Run: python3 bench.py
"""
from __future__ import annotations

import json
import os
import random
import statistics
from collections import Counter

from knotstore import KnotStore, ALGORITHM
from codec import encode_manifest, _uvarint


def human_pointer_record_bytes(ptr) -> int:
    """Serialized size of one tiny pointer (JSON, the format the draft used)."""
    return len(ptr.to_json().encode())


def full_address_record_bytes(address_bits: int) -> int:
    """A 'full address' record for honest comparison: the backend key (hex) plus
    the chunk digest needed to find/verify it. This is what a flat
    address->digest table costs per chunk."""
    addr_hex = address_bits // 4
    digest_hex = 64  # sha256 hex
    return addr_hex + digest_hex


def run(num_objects=1000, min_chunks=1, max_chunks=30,
        chunk_size=256, route_depth=10, dedupe_fraction=0.18, address_bits=64,
        seed=1234):
    rng = random.Random(seed)
    ks = KnotStore(chunk_size=chunk_size, route_depth=route_depth, address_bits=address_bits)

    # Build a corpus with a controlled fraction of duplicate chunks.
    pool = [os.urandom(chunk_size) for _ in range(64)]  # reusable chunks -> dedupe
    manifests = []
    total_chunks = 0
    total_bytes = 0
    pointer_bytes = 0
    for i in range(num_objects):
        nchunks = rng.randint(min_chunks, max_chunks)
        parts = []
        for _ in range(nchunks):
            if rng.random() < dedupe_fraction:
                parts.append(rng.choice(pool))
            else:
                parts.append(os.urandom(chunk_size))
        data = b"".join(parts)
        m = ks.put(data, f"obj_{i}")
        manifests.append((m, data))
        total_chunks += len(m.pointers)
        total_bytes += len(data)
        pointer_bytes += sum(human_pointer_record_bytes(p) for p in m.pointers)

    # Correctness over the whole corpus.
    roundtrip_ok = all(ks.get(m) == d for m, d in manifests)

    # Corruption detection: corrupt one cell, confirm at least one manifest fails.
    a_manifest, _ = manifests[0]
    victim = ks.address_for(bytes.fromhex(a_manifest.digests[0]), a_manifest.pointers[0].probe)
    saved = ks.backend[victim]
    ks.backend[victim] = saved + b"!"
    corruption_detected = not ks.verify(a_manifest)
    ks.backend[victim] = saved  # restore

    # Dedupe ratio: 1 - unique_cells / total_chunks_written.
    unique_cells = len(ks.backend)
    dedupe_ratio = 1.0 - (unique_cells / total_chunks) if total_chunks else 0.0

    # Collisions: cells reached with probe > 0.
    collisions = sum(p.probe for m, _ in manifests for p in m.pointers if p.probe > 0)

    # Real pointer compression vs a flat address->digest table.
    avg_ptr = pointer_bytes / total_chunks if total_chunks else 0.0
    avg_full = full_address_record_bytes(address_bits)
    compression_ratio = avg_ptr / avg_full if avg_full else 0.0

    # Binary tiny-pointer size (codec): the pointer SECTION only, i.e. the route
    # descriptor (1 byte + rare varint probe escape). This excludes the per-
    # manifest header and the 32-byte digest table (the integrity anchor any
    # content-addressed store needs regardless) -- the same basis as the JSON
    # pointer measurement, which also excludes the full digest.
    binary_ptr_bytes = 0
    for m, _ in manifests:
        for p in m.pointers:
            binary_ptr_bytes += 1 + (len(_uvarint(p.probe)) if p.probe >= 31 else 0)
    avg_binary_ptr = binary_ptr_bytes / total_chunks if total_chunks else 0.0

    # Shard load balance across N nodes vs an ideal-uniform baseline.
    num_nodes = 16
    knot_placement = Counter()
    baseline_placement = Counter()
    for m, _ in manifests:
        for dhex in m.digests:
            d = bytes.fromhex(dhex)
            knot_placement[ks.node_for(d, num_nodes)] += 1
            baseline_placement[d[0] % num_nodes] += 1  # plain digest-mod-N baseline

    def cv(counter):
        loads = [counter.get(n, 0) for n in range(num_nodes)]
        mean = statistics.mean(loads)
        return (statistics.pstdev(loads) / mean) if mean else 0.0

    report = {
        "objects": num_objects,
        "chunks": total_chunks,
        "unique_cells": unique_cells,
        "chunk_size": chunk_size,
        "route_depth": route_depth,
        "knot_count": 7,
        "delta_channels": 4,
        "address_bits": address_bits,
        "dedupe_ratio": round(dedupe_ratio, 4),
        "collisions": collisions,
        "avg_pointer_bytes_json": round(avg_ptr, 1),
        "avg_pointer_bytes_binary": round(avg_binary_ptr, 2),
        "full_address_record_bytes": avg_full,
        "pointer_compression_ratio_json_vs_full": round(compression_ratio, 4),
        "pointer_compression_ratio_binary_vs_json": round(
            avg_binary_ptr / avg_ptr, 4) if avg_ptr else 0.0,
        "shard_load_cv_knot": round(cv(knot_placement), 4),
        "shard_load_cv_digest_baseline": round(cv(baseline_placement), 4),
        "shard_note": (
            "knot/delta placement matches the digest baseline on load balance "
            "(both ~uniform) and provides NO content locality, because the "
            "coordinate is itself digest-derived"
        ),
        "roundtrip_pass": roundtrip_ok,
        "corruption_detection_pass": corruption_detected,
    }
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))

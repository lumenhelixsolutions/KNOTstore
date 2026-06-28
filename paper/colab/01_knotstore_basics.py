"""
Google Colab Notebook 1: KNOTstore Basics
==========================================
Run this in Google Colab or locally with Python 3.

Topics covered:
  - Content-addressed storage with O(1) address-regenerating retrieval
  - Binary tiny pointers (1 byte vs 186 bytes JSON)
  - Collision recovery with small address spaces
  - Shard balance: knot_coord vs digest_byte vs content_simhash

Usage:
  1. Upload the knotstore/ directory to your Colab session, or:
     !git clone <repo-url>
     %cd MYdev/knotstore
  2. Run each cell in order.
"""
import sys, os as _os
sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '../../knotstore'))


# ── Cell 1: Setup ──────────────────────────────────────────────────────────
import sys, os
# If running in Colab with the knotstore/ dir uploaded:
# sys.path.insert(0, "/content/knotstore")

from knotstore import KnotStore, KNOTS_V01, DELTA_CHANNELS
from codec import encode_manifest, decode_manifest, size_report
from signature import simhash64, shard_of
import os, json

print("KNOTstore modules loaded successfully")
print(f"Knot labels: {KNOTS_V01}")
print(f"Delta channels: {DELTA_CHANNELS}")


# ── Cell 2: Basic put / get / verify ──────────────────────────────────────
ks = KnotStore(chunk_size=64)
data = b"LENS-64S structural hashing demo payload." * 100

manifest = ks.put(data, "demo.bin")
retrieved = ks.get(manifest)
assert retrieved == data

print(f"Original size:  {len(data)} bytes")
print(f"Chunks:         {len(manifest.pointers)}")
print(f"Root digest:    {manifest.root_digest[:24]}...")
print(f"Round-trip:     PASS")
print(f"Integrity:      {ks.verify(manifest)}")


# ── Cell 3: The tiny pointer — JSON vs binary ─────────────────────────────
ks2 = KnotStore(chunk_size=256, placement="content")
large_data = os.urandom(256 * 100)  # 100 chunks
m = ks2.put(large_data, "large.bin")

# JSON pointer size
json_size = sum(len(p.to_json().encode()) for p in m.pointers) / len(m.pointers)

# Binary manifest
blob = encode_manifest(m)
# Subtract 32 bytes per chunk (digest table) to isolate pointer overhead
binary_per_ptr = (len(blob) - 32 * len(m.pointers)) / len(m.pointers)

print(f"\nPointer sizes ({len(m.pointers)} chunks):")
print(f"  JSON encoding:   {json_size:.1f} bytes/pointer")
print(f"  Binary encoding: {binary_per_ptr:.2f} bytes/pointer")
print(f"  Reduction:       {json_size / binary_per_ptr:.0f}×")
print()
print(size_report(m))

# Verify roundtrip through codec
back = decode_manifest(blob)
assert ks2.get(back) == large_data
print("Binary manifest round-trip: PASS")


# ── Cell 4: Collision recovery (small address space) ─────────────────────
import random
rng = random.Random(42)

ks3 = KnotStore(chunk_size=16, address_bits=12)  # 4096-cell space
blobs = [rng.randbytes(16) for _ in range(1000)]
data3 = b"".join(blobs)

m3 = ks3.put(data3, "collisions.bin")
probes = [p.probe for p in m3.pointers]
print(f"\nCollision recovery (12-bit address space, 1000 chunks):")
print(f"  Max probe:   {max(probes)}")
print(f"  Avg probe:   {sum(probes)/len(probes):.3f}")
print(f"  Chunks with probe > 0: {sum(1 for p in probes if p > 0)}")
print(f"  Round-trip:  {'PASS' if ks3.get(m3) == data3 else 'FAIL'}")


# ── Cell 5: Shard balance comparison ─────────────────────────────────────
from collections import Counter

NUM_NODES = 16
N_CHUNKS = 1000

def measure_balance(placement, chunks):
    ks_test = KnotStore(chunk_size=256, placement=placement)
    counts = Counter()
    for c in chunks:
        h = ks_test.digest(c)
        if placement == "content":
            shard = ks_test.shard_for(c, h, NUM_NODES)
        else:
            shard = ks_test.node_for(h, NUM_NODES)
        counts[shard] += 1
    loads = [counts.get(i, 0) for i in range(NUM_NODES)]
    mean = sum(loads) / NUM_NODES
    variance = sum((x - mean)**2 for x in loads) / NUM_NODES
    cv = (variance**0.5) / mean if mean > 0 else 0
    return cv, loads

test_chunks = [os.urandom(256) for _ in range(N_CHUNKS)]

cv_content, _ = measure_balance("content", test_chunks)
cv_digest, _  = measure_balance("digest", test_chunks)

print(f"\nShard balance across {NUM_NODES} nodes ({N_CHUNKS} chunks):")
print(f"  content (SimHash):  CV = {cv_content:.3f}")
print(f"  digest byte:        CV = {cv_digest:.3f}")
print(f"  (lower CV = better balance)")

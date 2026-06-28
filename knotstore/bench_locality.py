"""
Locality benchmark: does a content-correlated signature actually colocate
near-duplicate chunks better than digest-derived placement?

Method:
  - Build `clusters` groups. Each group = a random base chunk + `members`
    near-duplicates produced by flipping `edits` random bytes (so every member
    has a DISTINCT sha256 digest but is content-similar).
  - For each placement strategy, compute the co-shard probability: over all
    within-cluster pairs, the fraction that land on the same shard. Random
    placement over N nodes expects ~1/N.
  - Also report load-balance CV across nodes (lower = more even) so we can see
    whether locality costs balance.

Strategies compared:
  content_simhash   -> shard_of(simhash64(chunk))     [content-correlated]
  digest_byte       -> sha256(chunk)[0] % N           [draft-style baseline]
  knot_coord        -> KnotStore.node_for(digest, N)  [draft's knot x delta]

Run: python3 bench_locality.py
"""
from __future__ import annotations

import json
import os
import random
import statistics
from hashlib import sha256
from itertools import combinations

from knotstore import KnotStore
from signature import simhash64, shard_of, hamming


def make_clusters(n_clusters, members, chunk_size, edits, rng):
    clusters = []
    for _ in range(n_clusters):
        base = bytearray(os.urandom(chunk_size))
        group = [bytes(base)]
        seen = {sha256(bytes(base)).digest()}
        while len(group) < members:
            variant = bytearray(base)
            for _ in range(edits):
                variant[rng.randrange(chunk_size)] = rng.randrange(256)
            d = sha256(bytes(variant)).digest()
            if d not in seen:          # ensure distinct digests
                seen.add(d)
                group.append(bytes(variant))
        clusters.append(group)
    return clusters


def co_shard_probability(clusters, placement, num_nodes):
    same, total = 0, 0
    for group in clusters:
        shards = [placement(c) for c in group]
        for a, b in combinations(shards, 2):
            total += 1
            if a == b:
                same += 1
    return same / total if total else 0.0


def load_cv(clusters, placement, num_nodes):
    counts = [0] * num_nodes
    for group in clusters:
        for c in group:
            counts[placement(c)] += 1
    mean = statistics.mean(counts)
    return (statistics.pstdev(counts) / mean) if mean else 0.0


def run(n_clusters=300, members=8, chunk_size=256, edits=3, num_nodes=16, seed=7):
    rng = random.Random(seed)
    ks = KnotStore(chunk_size=chunk_size)
    clusters = make_clusters(n_clusters, members, chunk_size, edits, rng)

    # Sanity: confirm members really are near-duplicates (small simhash Hamming).
    intra = []
    for group in clusters:
        sigs = [simhash64(c) for c in group]
        intra += [hamming(a, b) for a, b in combinations(sigs, 2)]
    cross = []  # baseline: unrelated chunks
    bases = [grp[0] for grp in clusters]
    for a, b in zip(bases, bases[1:]):
        cross.append(hamming(simhash64(a), simhash64(b)))

    strategies = {
        "content_simhash": lambda c: shard_of(simhash64(c), num_nodes),
        "digest_byte":     lambda c: sha256(c).digest()[0] % num_nodes,
        "knot_coord":      lambda c: ks.node_for(sha256(c).digest(), num_nodes),
    }

    random_expectation = 1.0 / num_nodes
    report = {
        "n_clusters": n_clusters,
        "members_per_cluster": members,
        "chunk_size": chunk_size,
        "edits_per_variant": edits,
        "num_nodes": num_nodes,
        "simhash_hamming_intra_cluster_mean": round(statistics.mean(intra), 2),
        "simhash_hamming_cross_cluster_mean": round(statistics.mean(cross), 2),
        "co_shard_probability": {
            "_random_expectation": round(random_expectation, 4),
        },
        "load_balance_cv": {},
    }
    for name, fn in strategies.items():
        report["co_shard_probability"][name] = round(
            co_shard_probability(clusters, fn, num_nodes), 4)
        report["load_balance_cv"][name] = round(load_cv(clusters, fn, num_nodes), 4)

    csp = report["co_shard_probability"]
    report["verdict"] = (
        "content_simhash colocates near-duplicates "
        f"{csp['content_simhash'] / random_expectation:.1f}x better than random; "
        f"digest_byte ~{csp['digest_byte'] / random_expectation:.1f}x (no locality)"
    )
    return report


def sweep_edits(edit_levels=(1, 3, 8, 20, 64), chunk_size=256, num_nodes=16):
    """Locality should decay smoothly toward random as content diverges."""
    rows = []
    for e in edit_levels:
        r = run(edits=e, chunk_size=chunk_size, num_nodes=num_nodes)
        rows.append({
            "edits": e,
            "intra_hamming": r["simhash_hamming_intra_cluster_mean"],
            "co_shard_simhash": r["co_shard_probability"]["content_simhash"],
            "co_shard_random": r["co_shard_probability"]["_random_expectation"],
        })
    return rows


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
    print("\n# edit-sensitivity sweep (locality should decay toward random)")
    print(json.dumps(sweep_edits(), indent=2))

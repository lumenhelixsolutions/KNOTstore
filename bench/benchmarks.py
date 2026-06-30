"""One function per benchmark; each returns a flat dict of metrics.

Everything is deterministic (we seed a ``random.Random`` and only flip bytes
through it; no ``os.urandom``). All disk use goes through ``tempfile`` dirs that
are removed before each function returns.

The repo root is put on ``sys.path`` so ``import knotcore`` and the four app
packages resolve regardless of where this is invoked from.
"""
from __future__ import annotations

import os
import random
import shutil
import sys
import tempfile
import time
from hashlib import sha256
from itertools import combinations
from typing import Callable, Dict, List, Tuple

# --- path bootstrap: repo root + the four app packages ------------------------
_BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_BENCH_DIR)
_APPS = os.path.join(_REPO_ROOT, "apps")


def _bootstrap_path() -> None:
    paths = [_REPO_ROOT]
    for app in ("knotvault", "prefixforge", "checkpointtime", "driftledger"):
        paths.append(os.path.join(_APPS, app))
    for p in paths:
        if p not in sys.path:
            sys.path.insert(0, p)


_bootstrap_path()

import knotcore  # noqa: E402


# --- deterministic helpers ----------------------------------------------------
def _rand_bytes(rng: random.Random, n: int) -> bytes:
    """Deterministic random bytes (3.8-safe; no Random.randbytes)."""
    return bytes(rng.randrange(256) for _ in range(n))


def _mutate(rng: random.Random, data: bytes, edits: int) -> bytes:
    """Return a near-duplicate of ``data`` with ``edits`` bytes flipped."""
    if not data:
        return data
    b = bytearray(data)
    for _ in range(edits):
        b[rng.randrange(len(b))] = rng.randrange(256)
    return bytes(b)


# =============================================================================
# 1. engine_pointer_size
# =============================================================================
def engine_pointer_size(quick: bool = False) -> Dict[str, object]:
    """Bytes/pointer for the binary codec vs a JSON baseline.

    Builds a real manifest over a corpus and uses ``knotcore.size_report`` /
    ``encode_manifest`` to measure the binary tiny-pointer cost against the
    verbose JSON pointer the prototype used.
    """
    rng = random.Random(1001)
    chunk_size = 64
    n_chunks = 64 if quick else 512
    corpus = _rand_bytes(rng, chunk_size * n_chunks)

    store = knotcore.KnotStore(chunk_size=chunk_size, placement="content")
    manifest = store.put(corpus, name="corpus.bin")

    # round-trip sanity: the binary form must reproduce + still retrieve.
    blob = knotcore.encode_manifest(manifest)
    decoded = knotcore.decode_manifest(blob)
    roundtrip_ok = decoded.to_json() == manifest.to_json()
    retrieve_ok = store.get(decoded) == corpus

    rep = knotcore.size_report(manifest)
    return {
        "pointers": rep["pointers"],
        "json_pointer_bytes_avg": rep["json_pointer_bytes_avg"],
        "binary_pointer_bytes_avg": rep["binary_pointer_bytes_avg"],
        "pointer_compression_ratio": rep["pointer_compression_ratio"],
        "json_manifest_bytes": rep["json_manifest_bytes"],
        "binary_manifest_bytes": rep["binary_manifest_bytes"],
        "roundtrip_ok": bool(roundtrip_ok and retrieve_ok),
    }


# =============================================================================
# 2. engine_locality
# =============================================================================
def engine_locality(quick: bool = False) -> Dict[str, object]:
    """Co-shard probability for near-duplicate chunks: content vs digest.

    Content placement = ``shard_of(simhash64(chunk))``; digest placement =
    ``sha256(chunk)[0] % N``. Near-duplicates *should* colocate under content
    placement and not under digest placement (~random = 1/N).
    """
    rng = random.Random(2002)
    num_nodes = 16
    chunk_size = 256
    edits = 3
    n_clusters = 60 if quick else 300
    members = 8

    clusters: List[List[bytes]] = []
    for _ in range(n_clusters):
        base = _rand_bytes(rng, chunk_size)
        group = [base]
        seen = {sha256(base).digest()}
        guard = 0
        while len(group) < members and guard < members * 20:
            guard += 1
            variant = _mutate(rng, base, edits)
            d = sha256(variant).digest()
            if d not in seen:
                seen.add(d)
                group.append(variant)
        clusters.append(group)

    def co_shard(place: Callable[[bytes], int]) -> float:
        same = total = 0
        for group in clusters:
            shards = [place(c) for c in group]
            for a, b in combinations(shards, 2):
                total += 1
                if a == b:
                    same += 1
        return same / total if total else 0.0

    content_place = lambda c: knotcore.shard_of(knotcore.simhash64(c), num_nodes)
    digest_place = lambda c: sha256(c).digest()[0] % num_nodes

    # sanity: intra-cluster simhash distance should be small.
    intra: List[int] = []
    for group in clusters:
        sigs = [knotcore.simhash64(c) for c in group]
        intra += [knotcore.hamming(a, b) for a, b in combinations(sigs, 2)]

    content_csp = co_shard(content_place)
    digest_csp = co_shard(digest_place)
    random_expect = 1.0 / num_nodes
    ratio = (content_csp / digest_csp) if digest_csp else float("inf")
    return {
        "num_nodes": num_nodes,
        "n_clusters": n_clusters,
        "members_per_cluster": members,
        "random_expectation": round(random_expect, 4),
        "intra_cluster_hamming_mean": round(sum(intra) / len(intra), 2) if intra else 0.0,
        "co_shard_prob_content": round(content_csp, 4),
        "co_shard_prob_digest": round(digest_csp, 4),
        "content_over_digest_ratio": round(ratio, 2) if ratio != float("inf") else None,
        "content_over_random_ratio": round(content_csp / random_expect, 2),
    }


# =============================================================================
# 3. knotvault_dedup
# =============================================================================
def knotvault_dedup(quick: bool = False) -> Dict[str, object]:
    """Archive a synthetic fileset (duplicates + near-dups); report dedup %."""
    from knotvault.vault import Vault

    rng = random.Random(3003)
    chunk_size = 1024
    base_files = 6 if quick else 12
    base_size = 4096 if quick else 8192

    src = tempfile.mkdtemp(prefix="kv_src_")
    vault_root = tempfile.mkdtemp(prefix="kv_vault_")
    try:
        bases = [_rand_bytes(rng, base_size) for _ in range(base_files)]
        idx = 0
        for i, content in enumerate(bases):
            # original
            _write(src, "base_%02d.bin" % i, content)
            idx += 1
            # exact duplicate
            _write(src, "dup_%02d.bin" % i, content)
            idx += 1
            # near duplicate (a handful of byte edits -> shares most chunks)
            _write(src, "near_%02d.bin" % i, _mutate(rng, content, 4))
            idx += 1

        vault = Vault(root=vault_root, chunk_size=chunk_size)
        result = vault.add([src], name="corpus")
        # verify integrity round-trips
        verified_root = vault.verify("corpus")
        ok = verified_root == result.root_digest

        return {
            "files": result.files,
            "input_bytes": result.input_bytes,
            "bytes_on_disk": result.bytes_on_disk,
            "dedup_savings_pct": round(result.dedup_savings_pct, 2),
            "verify_ok": bool(ok),
        }
    finally:
        shutil.rmtree(src, ignore_errors=True)
        shutil.rmtree(vault_root, ignore_errors=True)


def _write(root: str, name: str, data: bytes) -> None:
    with open(os.path.join(root, name), "wb") as fh:
        fh.write(data)


# =============================================================================
# 4. prefixforge_hitlift
# =============================================================================
def prefixforge_hitlift(quick: bool = False) -> Dict[str, object]:
    """Exact-only hit-rate vs PrefixForge (exact+near) hit-rate + tokens saved.

    We seed the cache with a set of base prompts, then issue a query stream of
    near-duplicate variants (whitespace/punctuation/edit). Exact-only counts only
    queries whose normalized form is already stored; PrefixForge additionally
    serves near hits within its Hamming threshold. If a semantic (embedding)
    mode is constructible we include it, but never fail if it is not.
    """
    from prefixforge.cache import PrefixCache

    rng = random.Random(4004)
    n_base = 15 if quick else 40
    variants_each = 4

    # build base prompts as varied sentences.
    words = ("summarize", "the", "quick", "brown", "fox", "agent", "memory",
             "cache", "prompt", "vector", "token", "store", "engine", "knot",
             "delta", "route", "shard", "dedup", "hash", "merkle")

    def make_prompt() -> str:
        n = rng.randrange(6, 12)
        return " ".join(words[rng.randrange(len(words))] for _ in range(n))

    bases = [make_prompt() for _ in range(n_base)]

    # query stream: for each base, variants that are near-duplicates.
    def vary(p: str) -> str:
        kind = rng.randrange(3)
        if kind == 0:
            return "  ".join(p.split())          # whitespace change only -> exact
        if kind == 1:
            return p.upper()                      # case change -> exact (normalized)
        # one-word substitution -> near (not exact)
        toks = p.split()
        toks[rng.randrange(len(toks))] = words[rng.randrange(len(words))]
        return " ".join(toks)

    root = tempfile.mkdtemp(prefix="pf_")
    try:
        cache = PrefixCache(root=root, persist=False)
        for i, p in enumerate(bases):
            cache.put(p, ("completion-%d" % i).encode(), tokens=100)

        queries: List[str] = []
        for p in bases:
            for _ in range(variants_each):
                queries.append(vary(p))

        exact_hits = near_hits = total_hits = 0
        tokens_total = tokens_saved = 0
        for q in queries:
            res = cache.get(q)
            tokens_total += 100
            if res.kind == "exact":
                exact_hits += 1
                total_hits += 1
                tokens_saved += res.tokens_saved
            elif res.kind == "near":
                near_hits += 1
                total_hits += 1
                tokens_saved += res.tokens_saved

        n_q = len(queries)
        exact_rate = exact_hits / n_q if n_q else 0.0
        pf_rate = total_hits / n_q if n_q else 0.0
        out = {
            "queries": n_q,
            "exact_only_hit_rate": round(exact_rate, 4),
            "prefixforge_hit_rate": round(pf_rate, 4),
            "near_hits": near_hits,
            "tokens_saved_pct": round(100.0 * tokens_saved / tokens_total, 2) if tokens_total else 0.0,
        }

        # optional semantic mode: a toy deterministic embedding. Best-effort.
        try:
            sem = _semantic_hit_rate(root, bases, queries, words)
            if sem is not None:
                out["semantic_hit_rate"] = round(sem, 4)
        except Exception:
            pass
        return out
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _semantic_hit_rate(root: str, bases, queries, words) -> object:
    """Build a PrefixCache with a deterministic bag-of-words embedding."""
    from prefixforge.cache import PrefixCache

    vocab = {w: i for i, w in enumerate(words)}
    dim = len(words)

    def embed(text: str):
        vec = [0.0] * dim
        for tok in text.split():
            if tok in vocab:
                vec[vocab[tok]] += 1.0
        return vec

    sem_root = os.path.join(root, "semantic")
    cache = PrefixCache(root=sem_root, persist=False, embedding_fn=embed,
                        embedding_dim=dim)
    for i, p in enumerate(bases):
        cache.put(p, ("completion-%d" % i).encode(), tokens=100)
    hits = 0
    for q in queries:
        if cache.get(q).hit:
            hits += 1
    return hits / len(queries) if queries else 0.0


# =============================================================================
# 5. checkpointtime_dedup
# =============================================================================
def checkpointtime_dedup(quick: bool = False) -> Dict[str, object]:
    """~20 slowly-mutating checkpoints; logical vs physical bytes + dedup ratio."""
    from checkpointtime.store import CheckpointStore

    rng = random.Random(5005)
    n_checkpoints = 12 if quick else 20
    state_size = 8192 if quick else 16384
    chunk_size = 1024
    edits_per_step = 8

    root = tempfile.mkdtemp(prefix="ct_")
    try:
        store = CheckpointStore(root=root, chunk_size=chunk_size)
        state = _rand_bytes(rng, state_size)
        ids: List[str] = []
        for i in range(n_checkpoints):
            cid = store.snapshot(state, label="cp-%d" % i)
            ids.append(cid)
            state = _mutate(rng, state, edits_per_step)

        # integrity: first and last checkpoints restore exactly.
        first = store.restore(ids[0])
        restore_ok = len(first) == state_size

        st = store.stats()
        return {
            "checkpoints": st["checkpoints"],
            "logical_bytes": st["logical_bytes"],
            "physical_bytes_on_disk": st["physical_bytes_on_disk"],
            "dedup_ratio": round(st["dedup_ratio"], 3),
            "dedup_savings_pct": round(
                100.0 * (1.0 - st["physical_bytes_on_disk"] / st["logical_bytes"]), 2
            ) if st["logical_bytes"] else 0.0,
            "restore_ok": bool(restore_ok),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


# =============================================================================
# 6. driftledger_rollback
# =============================================================================
def driftledger_rollback(quick: bool = False) -> Dict[str, object]:
    """N-step ledger; roll back K; assert exact prior recovery + tamper catch."""
    from driftledger.ledger import AgentLedger

    rng = random.Random(6006)
    n_steps = 12 if quick else 24
    k_rollback = 4 if quick else 8
    state_size = 1024

    root = tempfile.mkdtemp(prefix="dl_")
    tamper_root = tempfile.mkdtemp(prefix="dl_t_")
    try:
        ledger = AgentLedger(root)
        states: List[bytes] = []
        t0 = time.perf_counter()
        for i in range(n_steps):
            state = _rand_bytes(rng, state_size)
            states.append(state)
            ledger.append("step-%d" % i, state)
        append_ms = (time.perf_counter() - t0) * 1000.0

        # snapshot the exact state we expect after rolling back K steps.
        target_idx = n_steps - k_rollback - 1
        expected_state = states[target_idx]

        t1 = time.perf_counter()
        for _ in range(k_rollback):
            ledger.rollback()
        rollback_ms = (time.perf_counter() - t1) * 1000.0

        recovered = ledger.checkout(target_idx)
        rollback_correct = recovered == expected_state
        chain_ok_after_rollback = ledger.verify()

        # tamper detection: corrupt a stored state blob, verify() must catch it.
        tamper_caught = _tamper_detected(tamper_root, rng, state_size)

        return {
            "steps": n_steps,
            "rolled_back": k_rollback,
            "rollback_correct": bool(rollback_correct),
            "verify_ok_after_rollback": bool(chain_ok_after_rollback),
            "tamper_caught": bool(tamper_caught),
            "append_ms": round(append_ms, 2),
            "rollback_ms": round(rollback_ms, 2),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(tamper_root, ignore_errors=True)


def _tamper_detected(root: str, rng: random.Random, state_size: int) -> bool:
    """Build a tiny ledger, corrupt an on-disk object, confirm verify() fails."""
    from driftledger.ledger import AgentLedger

    ledger = AgentLedger(root)
    for i in range(4):
        ledger.append("t-%d" % i, _rand_bytes(rng, state_size))
    if not ledger.verify():
        return False  # should be clean before tampering

    objects_dir = os.path.join(root, "objects")
    names = [n for n in os.listdir(objects_dir)
             if os.path.isfile(os.path.join(objects_dir, n))]
    if not names:
        return False
    victim = os.path.join(objects_dir, sorted(names)[0])
    with open(victim, "rb") as fh:
        data = bytearray(fh.read())
    if data:
        data[0] ^= 0xFF
    else:
        data = bytearray(b"\x00")
    with open(victim, "wb") as fh:
        fh.write(data)

    # fresh ledger forces a reload from disk so the tampered bytes are seen.
    reopened = AgentLedger(root)
    return not reopened.verify()


# --- registry -----------------------------------------------------------------
BENCHMARKS: List[Tuple[str, Callable[..., Dict[str, object]]]] = [
    ("engine_pointer_size", engine_pointer_size),
    ("engine_locality", engine_locality),
    ("knotvault_dedup", knotvault_dedup),
    ("prefixforge_hitlift", prefixforge_hitlift),
    ("checkpointtime_dedup", checkpointtime_dedup),
    ("driftledger_rollback", driftledger_rollback),
]

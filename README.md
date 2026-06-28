<div align="center">

```
╔═══════════════════════════════════════╗
║  ▄█▄  ▄█▄  ▄█▄  KNOTstore · LENS-64S ║
║  ╚█╝  ╚█╝  ╚█╝  v0.1.5               ║
╚═══════════════════════════════════════╝
```

**Knot-Addressed Structural Hashing and Tiny-Pointer Storage**

[![tests](https://img.shields.io/badge/tests-36%20pass-2440E6?style=flat-square&logo=pytest&logoColor=white)](knotstore/test_knotstore.py)
[![pointer](https://img.shields.io/badge/pointer%20size-1%20byte-11131A?style=flat-square)](knotstore/codec.py)
[![locality](https://img.shields.io/badge/SimHash%20locality-9.3×-2440E6?style=flat-square)](knotstore/bench_locality.py)
[![deps](https://img.shields.io/badge/dependencies-zero-5B6170?style=flat-square)](knotstore/)
[![license](https://img.shields.io/badge/license-MIT-DDDBD2?style=flat-square)]()

[Whitepaper](paper/WHITEPAPER.md) · [Colab Notebooks](paper/colab/) · [Interactive Infographic](https://lumenhelixsolutions.github.io/KNOTstore/)

</div>

---

A fully-corrected reference implementation where a **1-byte binary pointer** deterministically walks knot → δ-channel → ρ-move route → storage address. O(1) retrieval. Zero dependencies. All claims measured.

> **Three numbers:** `1 byte` per pointer · `186×` smaller than the JSON prototype · `9.3×` better near-duplicate locality than random placement.

---

## Quickstart

```bash
git clone https://github.com/lumenhelixsolutions/KNOTstore && cd KNOTstore
python3 -m pytest knotstore/test_knotstore.py -v   # 36 tests, all pass
python3 knotstore/bench.py                          # pointer size + shard balance
python3 knotstore/bench_locality.py                 # locality benchmark
```

---

## What it does

**`put(data)` → 1-byte pointer.**  
Content is hashed, a knot is chosen by its SimHash signature, a ρ-move route through a reversible 162-face MacroCube generates the storage address. The pointer stores only the 3-bit knot ID + 5-bit probe. Everything else is recomputed on retrieval.

**`get(pointer)` → original data, O(1).**  
The same knot → δ → route → address path is walked again. No scan. No index. The route *is* the address.

**`verify()` → Merkle-root tamper check.**  
The manifest carries the full digest table. Corruption is detected before data is returned.

---

## How the pointer shrinks to 1 byte

| Field | JSON prototype | Binary codec |
|---|---|---|
| `version`, `algorithm`, `depth`, `address_bits` | ~72 bytes of labels | manifest header (once, not per-chunk) |
| `delta`, `size`, `digest_prefix` | ~22 bytes | recomputed from digest |
| `knot` (3 bits) + `probe` (5 bits) | ~22 bytes verbose | **1 byte** |
| **Total per pointer** | **186 bytes** | **1 byte** |

The binary manifest is dominated by the 32-byte digest table — the Merkle anchor every content-addressed store carries regardless. The route descriptor is the 1 byte.

---

## Architecture

```
                        ┌─ content_simhash ──────────────────────┐
                        │   64-bit SimHash (Charikar 2002)        │
                        │   top 3 bits → knot ID                  │
DATA ──► BLAKE2b-256 ───┤                                         ├──► ADDRESS
         (digest)       │   digest[0] % 4 → δ-channel            │    O(1) lookup
                        │   digest bits  → ρ-move route           │
                        └─ MacroCube path ────────────────────────┘
                             27 subcubes · 162 faces
                             every move is a bijection
                             W⁻¹·W = identity (Prop 2 ✓)
```

The same path is walked by **both `put` and `get`**. The pointer carries only what can't be recomputed: the knot choice (content-driven in v0.1.2+) and the probe offset.

---

## Key results

| Claim | Measured |
|---|---|
| Binary pointer size | **1 byte** (186× smaller than JSON) |
| SimHash near-duplicate co-shard probability | **0.58** vs 0.06 random (**9.3×**) |
| knot_coord placement load CV | **0.266** — worse than a digest byte (0.065) |
| Trefoil Δ(t) | `1 − t + t²` ✓ |
| Figure-eight Δ(t) | `1 − 3t + t²` ✓ |
| Cinquefoil T(2,5) Δ(t) | `1 − t + t² − t³ + t⁴` ✓ |
| W⁻¹·W = identity | 20/20 random routes ✓ |
| 162 faces preserved after depth-50 route | bijection confirmed ✓ |
| Tests | **36 / 36 pass** |

> The draft claimed `avg_pointer_bytes = 96` with `62.5%` compression. **Measured: 186 bytes, 2.3× larger than a flat record.** Corrected in v0.1.2.

---

## Repository

| File | Purpose |
|---|---|
| `knotstore/knotstore.py` | Core store — put / get / verify / address_for |
| `knotstore/codec.py` | Binary tiny-pointer codec (1 byte) |
| `knotstore/signature.py` | 64-bit SimHash (Charikar 2002) |
| `knotstore/cube.py` | Reversible 162-face MacroCube + ρ-moves |
| `knotstore/provenance.py` | Rollback-capable ProvenanceLog |
| `knotstore/braid.py` | Alexander braid routes (B₉) |
| `knotstore/burau.py` | Reduced Burau matrices + Alexander Δ(t) ← v0.1.5 |
| `knotstore/knot_table.py` | KnotInfo-verified knot properties ← v0.1.5 |
| `knotstore/cauldron.py` | Cauldron canonical semantics + overlay |
| `knotstore/audit.py` | Phase-duality audit log (p=0 forward, p=1 dual) |
| `knotstore/bench.py` | Pointer size + shard balance benchmark |
| `knotstore/bench_locality.py` | Near-duplicate locality benchmark |
| `knotstore/test_knotstore.py` | 36 tests |
| `paper/WHITEPAPER.md` | Full white paper with proofs and tables |
| `paper/colab/` | 5 runnable Google Colab notebooks |

---

<details>
<summary><strong>What was broken in the draft (and how it was fixed)</strong></summary>

### Bug 1 — Retrieval was O(N), not O(1)

The draft's `get()` ignored the derived address and linearly scanned the backend matching on a 96-bit digest prefix. The knot / δ / route apparatus — the entire point of the paper — was never used on the read path.

**Fix:** `address_for(digest, probe)` is the single source of truth, used by both `put()` and `get()`. Test `test_retrieval_is_address_regeneration_not_scan` proves it: delete the key at the regenerated address and `get()` fails; a scan would not.

### Bug 2 — The pointer couldn't regenerate its own address

The draft stored a 64-bit seed prefix. The dormant `pointer_to_address` re-derived from `sha256(seed+knot)` — a *different* value than the stored key. The pointer lacked the information to reproduce the address.

**Fix:** The full chunk digest lives once in the manifest (the Merkle leaf, not secret). The pointer stores only the `probe` (the one value not derivable from the digest). Address regeneration is now exact.

### Bug 3 — Collision recovery was unfalsifiable

With 256-bit blake2b addresses, collisions never occur. The draft's `collisions: 3` benchmark line was unverifiable.

**Fix:** `address_bits` knob shrinks the address space. `test_collision_recovery_small_address_space` runs 4000 chunks into a 16-bit space, asserts probes fire, confirms round-trip.

</details>

<details>
<summary><strong>Knot table — KNOTS_V01 verified against KnotInfo</strong></summary>

| Knot | Invertible | Amphichiral | Alternating | det | sig | braid idx | Note |
|---|---|---|---|---|---|---|---|
| 10_34  | ✓ | ✓ | ✓ | 25 |  0 | 4 | |
| 10_125 | ✓ | ✗ | ✗ | 31 | −2 | 4 | |
| 10_85  | ✗ probable | ✗ | ✓ | 49 | +4 | 4 | → replace with **10_123** |
| 10_83  | ✗ confirmed | ✗ | ✓ | 43 | +2 | 4 | → replace with **10_99** |
| 10_61  | ✓ | ✗ | ✓ | 21 | −2 | 3 | |
| 10_20  | ✓ | ✗ | ✓ | 13 | −4 | 4 | |
| 10_136 | ✓ | ✗ | ✗ | 29 | −4 | 4 | |

**10_83 is confirmed non-invertible** (Trotter 1963, Hartley 1983). Non-invertible knots break the reversibility invariant — the forward route and its inverse land in different topological classes. See `paper/WHITEPAPER.md §8`.

</details>

<details>
<summary><strong>Near-duplicate locality — edit-sensitivity sweep</strong></summary>

| Placement | co-shard prob | vs random | load CV |
|---|---|---|---|
| `content_simhash` | **0.58** | **9.3×** | 0.097 |
| `digest_byte` | 0.059 | ~1× | 0.065 |
| `knot_coord` | 0.069 | ~1.1× | 0.266 |

The digest-derived knot/δ coordinate provides essentially no locality. SimHash locality decays smoothly as content diverges — confirming it tracks similarity, not noise:

| edits / variant | intra-cluster Hamming | co-shard prob |
|---|---|---|
| 1 | 4.6 | 0.75 |
| 3 | 8.0 | 0.55 |
| 8 | 12.7 | 0.45 |
| 20 | 19.2 | 0.25 |
| 64 | 27.9 | 0.11 |

</details>

---

## Honest scope

**Working:** deterministic content-addressed store · O(1) address-regenerating retrieval · 1-byte binary pointer · 9.3× near-duplicate locality · reversible 162-face MacroCube · rollback-capable provenance · Alexander polynomials verified against KnotInfo · 36 tests, zero dependencies.

**Not working yet:**
- Route Alexander polynomials are zero — `route_to_braid()` is an ad hoc projection, not a group homomorphism. Left for future work.
- δ-channels are `digest[0] % 4` labels — no knot-theoretic meaning.
- 10_83 and 10_85 should be replaced (non-invertible knots break reversibility).

---

## Version history

| Version | Addition |
|---|---|
| v0.1.1 | O(1) address-regenerating retrieval (was O(N) scan) |
| v0.1.2 | 1-byte binary pointer; SimHash content placement |
| v0.1.3 | Real reversible MacroCube (162 faces); rollback ProvenanceLog |
| v0.1.4 | Braid routes (B₉); Cauldron manifests; phase-duality audit log |
| **v0.1.5** | **Burau matrices; Alexander polynomials; KnotInfo verification** |

---

<div align="center">

MIT · lumenhelixsolutions · [Interactive Infographic →](https://lumenhelixsolutions.github.io/KNOTstore/)

</div>

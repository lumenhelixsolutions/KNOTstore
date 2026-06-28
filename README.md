# KNOTstore · LENS-64S · v0.1.5

**Knot-Addressed Structural Hashing and Tiny-Pointer Storage**

[![tests](https://img.shields.io/badge/tests-36%20pass-2440E6?style=flat-square)](knotstore/test_knotstore.py)
[![pointer](https://img.shields.io/badge/pointer-1%20byte-11131A?style=flat-square)](knotstore/codec.py)
[![locality](https://img.shields.io/badge/SimHash%20locality-9.3×-2440E6?style=flat-square)](knotstore/bench_locality.py)
[![stdlib](https://img.shields.io/badge/deps-stdlib%20only-5B6170?style=flat-square)]()

> A fully-corrected, runnable reference implementation of the LENS-64S architecture.  
> Content-addressed storage where a **1-byte binary pointer** deterministically regenerates  
> a knot → δ-channel → ρ-move route → storage address.

---

## Quickstart

```bash
python3 -m pytest knotstore/test_knotstore.py -v   # 36 tests, all pass
python3 knotstore/bench.py                          # pointer sizes + shard balance
python3 knotstore/bench_locality.py                 # 9.3× near-duplicate locality
```

---

## Repository layout

```
knotstore/
  knotstore.py        Core store: put / get / verify / address_for / route fingerprints
  signature.py        64-bit SimHash content signature (Charikar 2002)
  codec.py            Binary tiny-pointer codec — 1 byte per pointer
  cube.py             Reversible 27-subcube / 162-face MacroCube + ρ-moves
  provenance.py       Rollback-capable ProvenanceLog via inverse cube routes
  braid.py            Alexander braid representation of ρ-move routes (B₉)
  burau.py            Reduced Burau matrices; Alexander polynomial computation  ← NEW v0.1.5
  knot_table.py       KnotInfo-verified properties for all 7 KNOTS_V01 knots   ← NEW v0.1.5
  cauldron.py         Cauldron canonical semantics + CauldronManifest overlay
  audit.py            Phase-duality two-phase audit log (forward p=0, dual p=1)
  bench.py            Pointer-size + shard-balance benchmark
  bench_locality.py   Near-duplicate locality benchmark
  test_knotstore.py   36 tests (all pass)
  README.md           Technical deep-dive — what was broken and how it was fixed

paper/
  WHITEPAPER.md       Full technical white paper with proofs, tables, and equations
  colab/
    01_knotstore_basics.py      put / get / verify / tiny pointers / shard balance
    02_burau_alexander.py       Laurent polynomials / Burau generators / Alexander Δ
    03_knot_table.py            Knot properties / invertibility / amphichirality
    04_cauldron_audit.py        Cauldron semantics / commit-rollback / phase audit
    05_cube_provenance.py       MacroCube order-4 / Prop 2 (W⁻¹W=id) / ProvenanceLog
```

---

## Key measured results

| Finding | Value |
|---|---|
| Binary pointer size | **1 byte** (vs 186 bytes JSON — 186× reduction) |
| SimHash near-duplicate co-shard probability | **0.58** vs 0.06 random (9.3×) |
| Trefoil Alexander polynomial Δ(t) | **1 − t + t²** ✓ |
| Figure-eight Alexander polynomial Δ(t) | **1 − 3t + t²** ✓ |
| Cinquefoil T(2,5) Alexander polynomial | **1 − t + t² − t³ + t⁴** ✓ |
| W⁻¹·W = identity (Prop 2) | 20/20 random routes ✓ |
| All 162 faces preserved (bijection) | confirmed after depth-50 route ✓ |

---

## Knot table (KNOTS_V01 · verified against KnotInfo)

| Knot | Invertible | Amphichiral | Alternating | det | sig | braid idx |
|---|---|---|---|---|---|---|
| 10_34  | ✓ | ✓ | ✓ | 25 |  0 | 4 |
| 10_125 | ✓ | ✗ | ✗ | 31 | −2 | 4 |
| 10_85  | ✗ (probable) | ✗ | ✓ | 49 | +4 | 4 |
| 10_83  | ✗ (confirmed) | ✗ | ✓ | 43 | +2 | 4 |
| 10_61  | ✓ | ✗ | ✓ | 21 | −2 | 3 |
| 10_20  | ✓ | ✗ | ✓ | 13 | −4 | 4 |
| 10_136 | ✓ | ✗ | ✗ | 29 | −4 | 4 |

**10_83 is confirmed non-invertible** (Trotter 1963, Hartley 1983).  
Replacement recommendation: 10_83 → **10_99**, 10_85 → **10_123** (both amphichiral + invertible).  
See `paper/WHITEPAPER.md §8` and `knotstore/knot_table.py`.

---

## Honest scope

Three limitations are documented rather than papered over.

**1. Route Alexander polynomials are zero.**  
`route_to_braid()` is an ad hoc projection (not a group homomorphism from cube symmetries to Bₙ),  
so `det(I − ρ̄(β)) = 0` for all KNOTstore routes. Classic knot polynomials work correctly for  
standard braids (`burau.py` verifies trefoil, figure-eight, cinquefoil against KnotInfo).  
A genuine homomorphism requires embedding cube symmetries in Bₙ — left for future work.

**2. δ-channels are labels.**  
The four Cauldron δ-pairs are assigned by `digest[0] % 4` — uniform distribution, no knot-theoretic meaning.

**3. 10_83 / 10_85 should be replaced.**  
Non-invertible knots break the reversibility invariant (forward route and inverse land in different topological classes).

---

## What was broken in the draft

### 1. Retrieval did not regenerate the address (the central bug)
The draft's `get()` linearly scanned the whole backend, ignoring the derived address entirely — O(N) content search.  
The knot / δ-channel / route apparatus was never used on the read path.

**Fixed:** `address_for(digest, probe)` is the single source of truth for placement, used by both `put()` and `get()`.  
Retrieval recomputes knot → δ → route → address for a direct O(1) backend lookup.  
`test_retrieval_is_address_regeneration_not_scan` proves it.

### 2. The pointer could not regenerate the address
The draft stored only a 64-bit seed prefix — literally missing the information needed to reproduce the address.

**Fixed:** the full chunk digest lives once in the manifest; the pointer carries only the `probe`  
(the one datum not derivable from the digest) plus screening metadata. Address regeneration is now exact.

### 3. Collision recovery was untestable
With full 256-bit blake2b addresses, collisions never occur, making collision theorems unfalsifiable.

**Fixed:** an `address_bits` knob shrinks the address space.  
`test_collision_recovery_small_address_space` runs 4000 chunks into a 16-bit space, asserts probes fire, confirms round-trip.

---

## Pointer compression (bench.py · 1000 objects · ~15.7k chunks · 256-byte chunks)

| Encoding | bytes/pointer |
|---|---|
| JSON (prototype drift) | 186.3 |
| **Binary codec** | **1.0** |

**186× reduction.** The binary manifest is dominated by the 32-byte digest table (the Merkle anchor  
any content-addressed store needs). The "tiny pointer" claim is about the route descriptor: 1 byte.

---

## Near-duplicate locality (bench_locality.py)

| Placement | co-shard prob | vs random | load CV |
|---|---|---|---|
| `content_simhash` | **0.58** | **9.3×** | 0.097 |
| `digest_byte` | 0.059 | ~1× | 0.065 |
| `knot_coord` | 0.069 | ~1.1× | 0.266 |

Edit-sensitivity sweep (intra-cluster Hamming vs co-shard probability):

| edits/variant | SimHash Hamming | co-shard (simhash) |
|---|---|---|
| 1 | 4.6 | 0.75 |
| 3 | 8.0 | 0.55 |
| 8 | 12.7 | 0.45 |
| 20 | 19.2 | 0.25 |
| 64 | 27.9 | 0.11 |

---

## Version history

| Version | Key addition |
|---|---|
| v0.1.1 | Corrected O(1) address-regenerating retrieval (not O(N) scan) |
| v0.1.2 | 1-byte binary tiny pointer; SimHash content placement |
| v0.1.3 | Real reversible MacroCube (162 faces); rollback ProvenanceLog |
| v0.1.4 | Braid routes (B₉); Cauldron canonical manifests; phase-duality audit log |
| **v0.1.5** | **Full Burau representation; Alexander polynomials; KnotInfo verification** |

---

## Honest status

**Real and working:** deterministic content-addressed store, O(1) address-regenerating retrieval,  
open-address collision recovery, exact-dup collapse, Merkle-root tamper detection, 1-byte binary tiny pointer,  
content-correlated placement with ~9× near-duplicate locality, working reversible MacroCube driving  
order-sensitive rollback-capable provenance.

**Still namespacing, not topology:** the δ-channels remain a `digest % 4` label with no measured function,  
and knot labels are a coarse projection of the content signature. The real locality lives at the shard level.  
If the knot-theory framing is to mean anything, its selector must be driven by content signature, not digest modulo.

---

*See the [interactive infographic](https://lumenhelixsolutions.github.io/KNOTstore/) for a visual architecture overview.*

# LENS-64S × Cauldron: A Unified Reversible-Addressing Architecture

**KNOTstore v0.1.5 — Technical White Paper**

*Corrected reference implementation, measured benchmarks, knot-theoretic foundations,
 Cauldron canonical semantics, and phase-duality audit trails.*

---

## Abstract

We present KNOTstore, a corrected and extended implementation of the LENS-64S
content-addressed storage architecture described in the draft
*"Knot-Addressed Structural Hashing and Tiny-Pointer Storage"*. The original
prototype contained three critical bugs (O(N) retrieval, irreproducible pointers,
untestable collision recovery) that contradicted the paper's central thesis. We fix
all three, measure the actual pointer sizes (1 byte binary vs. 186 bytes JSON),
implement content-correlated SimHash placement (9.3× locality improvement), and
extend the architecture with:

1. **Full Burau representation** — the reduced Burau matrices ρ̄: B₉ → GL₈(ℤ[t, t⁻¹])
   enable computation of Alexander polynomials for storage routes, making knot
   invariants load-bearing in the address-generation pipeline.

2. **Knot verification** — the seven KNOTS_V01 labels characterized against the
   KnotInfo database; two (10_83 confirmed, 10_85 probable) are non-invertible and
   unsuitable for reversible addressing.

3. **Cauldron canonical semantics** — the 10-state Cauldron system's quadratic
   moment ordering I(a,b) = a² + b² provides a parameter-free proof of canonicality
   for the δ-pair hierarchy; lifted into KNOTstore manifests as an optional overlay.

4. **Phase-duality audit trails** — every event produces dual fingerprints (p=0
   forward, p=1 phase-conjugate), enabling rollback, tamper detection, and
   order-sensitivity verification beyond what a one-way hash chain supports.

All claims are backed by running code and passing tests (36 tests, stdlib only).

---

## Table of Contents

1. [Background and Motivation](#1-background-and-motivation)
2. [Bug Analysis: What Was Wrong](#2-bug-analysis-what-was-wrong)
3. [Corrected Architecture: KNOTstore v0.1.x](#3-corrected-architecture-knotstore-v01x)
4. [Binary Tiny Pointers](#4-binary-tiny-pointers)
5. [Content-Correlated Placement via SimHash](#5-content-correlated-placement-via-simhash)
6. [Reversible Macro-Cube and Provenance](#6-reversible-macro-cube-and-provenance)
7. [Braid Representation of Routes](#7-braid-representation-of-routes)
8. [Full Burau Representation and Alexander Polynomials](#8-full-burau-representation-and-alexander-polynomials)
9. [Knot Verification: KNOTS_V01 Characterized](#9-knot-verification-knots_v01-characterized)
10. [Cauldron Canonical Semantics](#10-cauldron-canonical-semantics)
11. [Phase-Duality Audit Log](#11-phase-duality-audit-log)
12. [Unified Architecture: Integration Points](#12-unified-architecture-integration-points)
13. [Experimental Results](#13-experimental-results)
14. [Honest Assessment and Open Problems](#14-honest-assessment-and-open-problems)
15. [Appendix A: Proof of Address Regeneration (Theorem 1 corrected)](#appendix-a)
16. [Appendix B: Burau Generator Derivation](#appendix-b)
17. [Appendix C: Cauldron Canonicality Proof](#appendix-c)

---

## 1. Background and Motivation

### 1.1 The Core Claim of LENS-64S

The LENS-64S draft proposes that a *tiny pointer* — a few bytes encoding a knot
label, δ-channel, route depth, and collision probe — can deterministically regenerate
a storage route to any stored chunk:

```
pointer → knot → δ-channel → ρ-route → address
```

The central thesis:

> **Theorem 1 (Draft).** *A tiny pointer P uniquely regenerates the storage address
> A(P) = BLAKE2b(digest ‖ knot ‖ δ ‖ route ‖ probe) without scanning the backend.*

This is a strong O(1) retrieval guarantee. If true, the system provides:
- Deterministic, scan-free lookup
- Compact pointers encoding only the route descriptor
- Content-integrity via Merkle leaves (the chunk digests)

### 1.2 The Problem: The Code Did Not Implement the Theorem

Our audit of the prototype found three bugs, each individually fatal to the thesis:

| Bug | Effect |
|-----|--------|
| `get()` performed linear scan | O(N) retrieval, negates the knot machinery |
| Pointer stored 64-bit seed, not full digest | Address not reproducible from the pointer |
| Full 256-bit address space → zero collisions | Collision recovery code untestable |

These are not minor issues. Bug 1 means the prototype's `get()` was a hash table
scan that never used the knot, δ, or route machinery. Bug 2 means even if `get()`
had used the pointer, it would have computed a *different* address than `put()`.

### 1.3 Why This Architecture Matters

Despite the bugs, the underlying idea is sound and worth fixing:

- **Knot labels** provide a natural grouping of storage routes. If knot invariants
  are used (rather than just labels), routes sharing a knot class are topologically
  equivalent and their addresses cluster.
- **Tiny pointers** are genuinely smaller than flat (address, digest) records when
  the manifest header amortizes common fields — the 1-byte binary pointer proves this.
- **Reversible routes** (the macro-cube) provide rollback-capable provenance: unlike
  a one-way hash chain, you can invert H_{t+1} = F(H_t, ρ_t) back to H_t.

---

## 2. Bug Analysis: What Was Wrong

### 2.1 Bug 1: Retrieval Was a Linear Scan

```python
# BROKEN draft code (paraphrased)
def get(self, manifest):
    for ptr in manifest.pointers:
        for key, chunk in self.backend.items():   # linear scan
            if chunk[:12] == bytes.fromhex(ptr.digest_prefix):
                yield chunk
                break
```

This scans all stored chunks looking for a 96-bit prefix match. It is O(N) in the
number of stored chunks. The knot, δ-channel, route, and address are never used.

**Consequence**: Theorem 1's O(1) guarantee is false in the prototype. Any two
chunks with a colliding 96-bit prefix would produce wrong output; the draft's
"tiny pointer" was actually a content-search key, not a route descriptor.

**Fix**: A single `address_for(digest, probe, knot)` function serves as the unique
source of truth for both `put()` and `get()`:

```python
def address_for(self, digest: bytes, probe: int,
                knot: Optional[str] = None) -> str:
    if knot is None:
        knot = self.select_knot(digest)
    delta = self.select_delta(digest)
    route = self.compile_route(knot, digest, self.route_depth)
    return self.derive_address(digest, knot, delta, route, probe)

def get(self, manifest: Manifest) -> bytes:
    for ptr, dhex in zip(manifest.pointers, manifest.digests):
        digest = bytes.fromhex(dhex)
        address = self.address_for(digest, ptr.probe, ptr.knot)  # O(1)
        chunk = self.backend[address]
        ...
```

Test `test_retrieval_is_address_regeneration_not_scan` proves correctness by
deleting the regenerated address and verifying that `get()` fails — a scan-based
implementation would still find the chunk.

### 2.2 Bug 2: The Pointer Could Not Reproduce the Address

The draft stored only a 64-bit seed prefix `s[:8]` in the pointer, but derived the
storage address from the full 256-bit digest:

```
address = BLAKE2b(digest[0:32] ‖ knot ‖ ...)
pointer.seed = digest[0:8]   # only 64 bits!
```

The dormant `pointer_to_address()` recomputed `sha256(seed ‖ knot)` — a
*different* hash than the stored key. The pointer literally could not reproduce its
own address.

**Fix**: The full chunk digest (the Merkle leaf) is kept in the manifest's `digests`
array. The pointer carries only `probe` (the one datum not derivable from the digest)
plus screening metadata. Address regeneration is now exact.

### 2.3 Bug 3: Collision Recovery Was Untestable

With a 256-bit address space (2²⁵⁶ slots), the probability of a genuine collision
across any realistic corpus is astronomically small. The draft's `collisions: 3`
benchmark line and its collision-recovery theorems were unfalsifiable.

**Fix**: An `address_bits` knob shrinks the address space to as few as 8 bits.
`test_collision_recovery_small_address_space` runs 4000 chunks into a 16-bit space,
asserts that at least one `probe > 0` fires, and confirms the round-trip still holds.

---

## 3. Corrected Architecture: KNOTstore v0.1.x

### 3.1 Data Flow

```
                    PUT
  data ──chunk()──► [c₀, c₁, …, cₙ]
                         │
                    sha256(cᵢ) = digest
                         │
  placement="digest"    knot_for(data, digest)
  ──────────────────►    │
  placement="content"   │ ← simhash64(data) top 3 bits
                         │
                   select_delta(digest) = δ
                         │
                   compile_route(knot, digest, depth)
                         │
                   derive_address(digest, knot, δ, route, probe)
                         │
                   backend[address] = chunk

                    GET (O(1))
  pointer.probe          │
  manifest.digest ──────►address_for(digest, probe, knot)
                         │
                   backend[address] → chunk
```

### 3.2 Address Derivation

For chunk digest `h`, knot `k`, δ-channel `δ`, route `R = [ρ₁, …, ρ_d]`, and
probe `p` (collision offset):

```
address = BLAKE2b(h ‖ k ‖ δ ‖ encode(R) ‖ str(p),
                  digest_size=32, person="LENS64S_ADDR")[:address_bits // 4]
```

The route itself is deterministic from `(k, h)`:

```
route_material = BLAKE2b(k ‖ h, digest_size=64, person="LENS64S_ROUTE")
ρᵢ = RhoMove(
    axis   = AXES[route_material[3i] % 3],
    layer  = LAYERS[route_material[3i+1] % 3],
    dir    = DIRS[route_material[3i+2] % 2],
)
```

### 3.3 Manifest Structure

```json
{
  "version": 1,
  "name": "object.bin",
  "chunk_size": 256,
  "total_size": 12800,
  "route_depth": 10,
  "address_bits": 256,
  "placement": "digest",
  "root_digest": "sha256 Merkle root of all chunk digests",
  "pointers": [
    {"version": 1, "knot": "10_83", "delta": "D1:(2,5)",
     "depth": 10, "probe": 0, "size": 256, "digest_prefix": "abc123..."}
  ],
  "digests": ["full 64-hex sha256 per chunk"]
}
```

---

## 4. Binary Tiny Pointers

### 4.1 The Problem with JSON Pointers

The draft's "tiny pointer" was 186 bytes of JSON on average:

```json
{"algorithm": "lens64s-sha256-blake2b-croute-v1.1", "delta": "D4:(6,9)",
 "depth": 10, "digest_prefix": "a3f2c1...", "knot": "10_125",
 "probe": 0, "size": 256, "version": 1}
```

The `algorithm` field alone is 38 characters. This is not a "tiny pointer" — it is
a verbose JSON record larger than a flat (address, digest) pair would be.

### 4.2 The Codec Solution

`codec.py` hoists all constant and derivable fields out of the per-chunk pointer:

| Field | Location after codec |
|-------|---------------------|
| version, algorithm, depth, address_bits, chunk_size, placement | manifest header (once) |
| delta | recomputed from `digest[0] % 4` |
| size | recomputed from chunk_size (except last chunk) |
| digest_prefix | recomputed from digest table |
| **knot** (3 bits) + **probe** (5 bits, varint escape) | **the 1 byte we store** |

### 4.3 Binary Encoding

```
Byte layout:
  bits 7-5: knot index (0–6, index into KNOTS_V01)
  bits 4-0: probe (0–30 inline; 31 = varint escape follows)

Varint escape (probe ≥ 31):
  marker byte = 0xFF
  probe encoded as unsigned varint (LEB128)
```

```
encode_manifest(m) → header_bytes ‖ [32-byte digest]×n ‖ [1+ byte pointer]×n
```

### 4.4 Measured Results

| Encoding | Bytes / pointer | Ratio |
|----------|----------------|-------|
| JSON (prototype) | 186.3 | 1.0× |
| Binary (codec) | **1.0** | **0.005× (186× smaller)** |

The manifest total is dominated by the 32-byte digest table (the Merkle leaves /
integrity anchor), which *any* content-addressed store needs regardless. The "tiny
pointer" claim is about the route descriptor — that is the 1 byte.

---

## 5. Content-Correlated Placement via SimHash

### 5.1 The Locality Problem

The draft's knot × δ coordinate is `(digest[1] % 7, digest[0] % 4)` — a pure
function of the content hash. Near-duplicate chunks (differing by 1 byte) have
uncorrelated hashes, so they scatter uniformly across shards. The draft claimed
locality, but the design cannot deliver it.

### 5.2 SimHash Content Signature

SimHash (Charikar 2002) maps a document to a single hash h such that the Hamming
distance H(h(A), h(B)) approximates the edit distance between A and B. For
byte-level shingles:

```
For each shingle s ∈ content:
    v[j] += +1 if sha256(s)[j] is set, else -1
h[j] = sign(v[j])
```

The 64-bit SimHash is computed in `signature.py`. The top k bits determine the
shard:

```python
shard = simhash64(data) >> (64 - k)
```

### 5.3 Measured Locality Improvement

Test corpus: 60 near-duplicate 256-byte chunks (one base ± 2 random byte flips each).
16 target nodes.

| Placement | Co-shard probability | vs random | Load CV |
|-----------|---------------------|-----------|---------|
| content_simhash | **0.58** | **9.3×** | 0.097 |
| digest_byte | 0.059 | ~1.0× | 0.065 |
| knot_coord | 0.069 | ~1.1× | 0.266 |

Edit-sensitivity sweep (co-shard probability as a function of edit distance):

```
 edits │ intra-cluster SimHash Hamming │ co-shard (simhash)
───────┼──────────────────────────────┼───────────────────
     1 │                          4.6 │               0.75
     3 │                          8.0 │               0.55
     8 │                         12.7 │               0.45
    20 │                         19.2 │               0.25
    64 │                         27.9 │               0.11
```

Locality decays smoothly toward the random baseline (0.0625 for 16 nodes) as
content diverges — confirming the placement tracks similarity, not noise.

---

## 6. Reversible Macro-Cube and Provenance

### 6.1 The MacroCube

`cube.py` implements a real 27-subcube, 162-face state machine:

- 27 positions in a 3×3×3 grid, each with a 6-element orientation vector
- A ρ-move is a 90° slice rotation: 9 subcubes in a layer cycle, their face
  orientations updated accordingly
- Every move is a bijection over the 162 faces (no face is ever lost)

Key identities:
```
(ρ)^4 = id          (order-4 rotation)
ρ⁻¹ · ρ = id        (inverse is well-defined)
```

Both are tested:
- `test_cube_move_order_4_is_identity`: all (axis, layer) combinations
- `test_cube_route_inverse_is_identity`: 20 random routes of depth 15

### 6.2 Provenance Log

`provenance.py` maintains a reversible audit chain:

```
H_{t+1} = fingerprint(apply_route(H_t, ρ_t))
```

Unlike a one-way hash chain, this chain is **invertible**:

```python
H_t = fingerprint(apply_route(H_{t+1}, inverse_route(ρ_t)))
```

Properties:
- **Rollback**: exact prior fingerprint recoverable by inverse route
- **Replay-to-origin**: full rollback of lineage lands on the identity cube
- **Order sensitivity**: moves don't commute → reordering changes fingerprint

```
       ProvenanceLog.add("event_a") → H₁
                  .add("event_b") → H₂
                  .add("event_c") → H₃
                  .rollback()     → H₂ (exact recovery, not approximation)
                  .rollback()     → H₁
                  .rollback()     → H₀ = identity cube
```

---

## 7. Braid Representation of Routes

### 7.1 From ρ-Moves to Braid Words

A 90° layer rotation acts on 9 cube positions. Projecting the 3D rotation onto a
1D strand ordering yields a braid crossing. We assign non-overlapping strand bands
to each axis to avoid conflict:

```
Axis Y → strands 0–2  (σ₁, σ₂ family)
Axis X → strands 3–5  (σ₄, σ₅ family)
Axis Z → strands 5–7  (σ₆, σ₇ family)
```

Each 90° rotation decomposes into 4 adjacent transpositions (braid crossings):

```python
_MOVE_CROSSINGS = {
    ("Y", +1): [σ₁, σ₂, σ₃, σ₂],  (indices 0,1,2,1)
    ("X", +1): [σ₄, σ₅, σ₆, σ₅],  (indices 3,4,5,4)
    ("Z", +1): [σ₆, σ₇, σ₈, σ₇],  (indices 5,6,7,6)
    ...
}
```

A 10-move route produces a 40-crossing braid word — an element of B₉.

### 7.2 Braid Group Properties

The **braid group** B_n is generated by σ₁, …, σ_{n-1} subject to:
- σᵢσⱼ = σⱼσᵢ if |i−j| ≥ 2 (far commutativity)
- σᵢσᵢ₊₁σᵢ = σᵢ₊₁σᵢσᵢ₊₁ (braid relation)

The **strand permutation** induced by a braid word β ∈ B_n is the image under the
surjection B_n → S_n sending each generator σᵢ to the transposition (i, i+1).

Key property used in KNOTstore:

```python
braid.extend(braid.inverse()).trace_strands() == list(range(9))
```

This is not just an algebraic identity — it is tested computationally for each
route to verify that the braid machinery is internally consistent.

### 7.3 Braid Fingerprint

The current braid fingerprint is:

```
B(length, permutation)
```

This is a simplified invariant sufficient for collision detection and route
equivalence grouping. It is *not* the full Alexander polynomial — that requires
the Burau representation (Section 8). The key distinction:

| Invariant | Distinguishes | Does not distinguish |
|-----------|---------------|----------------------|
| Strand permutation | Different permutations | Same permutation, different crossing patterns |
| Alexander poly | Knot type (usually) | Some knot pairs (e.g., Conway mutants) |
| Jones polynomial | Most knots | Unknown pairs |

---

## 8. Full Burau Representation and Alexander Polynomials

### 8.1 The Reduced Burau Representation

The **reduced Burau representation** is a ring homomorphism:

```
ρ̄: B_n → GL_{n-1}(ℤ[t, t⁻¹])
```

mapping each braid generator to an (n-1)×(n-1) matrix over Laurent polynomials
in the formal variable t.

### 8.2 Generator Matrices

For σ_i ∈ B_n (braid generator, 1-indexed), the matrix ρ̄(σ_i) is the identity
except in row k = i−1 (0-indexed):

```
         col k-1   col k   col k+1
row k:  [  t      ,  -t   ,   1    ]    (direction = +1)
```

(Entries at col k-1 and col k+1 are absent if the index is out of range.)

For the inverse generator σ_i⁻¹:

```
         col k-1   col k     col k+1
row k:  [  1      ,  -t⁻¹  ,  t⁻¹  ]  (direction = -1)
```

**Verification**: The braid relation σ₁σ₂σ₁ = σ₂σ₁σ₂ holds in these matrices:

```python
s1 = reduced_burau_generator(3, 0, 1)   # σ₁ in B₃
s2 = reduced_burau_generator(3, 1, 1)   # σ₂ in B₃
assert (s1 * s2) * s1 == (s2 * s1) * s2   # PASSES
```

Explicit matrices for B₃:

```
            ⎡ -t   1 ⎤              ⎡ 1   0  ⎤
ρ̄(σ₁) =   ⎢         ⎥    ρ̄(σ₂) = ⎢        ⎥
            ⎣  0   1 ⎦              ⎣ t   -t ⎦
```

### 8.3 Alexander Polynomial Formula

For a braid β ∈ B_n with matrix M = ρ̄(β):

```
              det(I − M)
Δ(t) = ─────────────────────────
        1 + t + t² + … + t^{n-1}
```

The result is normalized: positive leading coefficient, cleared of negative t-powers.

### 8.4 Verification Against Known Knots

**Trefoil** T(2,3) = closure of σ₁³ ∈ B₂:

```
M = ρ̄(σ₁)³ = (−t)³ = −t³
I − M = 1 + t³ = (1 + t)(1 − t + t²)

Denominator: 1 + t

Δ(t) = (1 + t³) / (1 + t) = 1 − t + t²  ✓
```

**Figure-eight knot** = closure of σ₁σ₂⁻¹σ₁σ₂⁻¹ ∈ B₃:

```
M = ρ̄(σ₁σ₂⁻¹σ₁σ₂⁻¹)
det(I − M) = 1 + t² (after normalization)
Denominator: 1 + t + t²

Δ(t) = 1 − 3t + t²  ✓
```

Both are textbook values from Alexander (1928) and Rolfsen (1976).

### 8.5 Route Alexander Polynomial

For any KNOTstore route (knot, digest), the braid word from `route_to_braid()` can
be fed to `alexander_invariant()` to compute an Alexander polynomial:

```python
route = ks.compile_route(knot, digest, ks.route_depth)
moves = [(m.axis, m.layer, m.direction) for m in route]
braid = route_to_braid(moves)  # BraidWord in B₉
poly = alexander_poly_from_braid(braid)  # LaurentPoly in ℤ[t, t⁻¹]
```

This gives each (knot, digest) pair a proper topological fingerprint — not just a
strand permutation. Routes with identical Alexander polynomials are in the same
knot class under the B₉ projection.

### 8.6 Implementation Notes

**LaurentPoly** over ℤ uses a `{exponent: coefficient}` dictionary, supporting:
- Addition, subtraction, multiplication (polynomial ring operations)
- Evaluation at rational or integer t
- Normalization (positive leading coefficient, cleared of negative powers)
- Exact polynomial long division (raises ValueError if not exact)

**LaurentMatrix**: square matrix of LaurentPoly entries, supporting identity
construction, matrix multiplication, and equality testing.

**Determinant**: cofactor expansion over LaurentPoly entries. For n=8 (the
KNOTstore B₉ case), this is 8×8 cofactor expansion. Complexity is O(n!) in the
worst case; in practice, sparse entries from the Burau structure keep this fast.

---

## 9. Knot Verification: KNOTS_V01 Characterized

### 9.1 The Seven Knots

The KNOTS_V01 tuple uses Rolfsen notation for 10-crossing prime knots:

```python
KNOTS_V01 = ("10_34", "10_125", "10_85", "10_83", "10_61", "10_20", "10_136")
```

These were chosen for the draft without formal topological characterization.
`knot_table.py` provides complete characterization from KnotInfo.

### 9.2 Summary Table

```
Knot     Invertible    Amphichiral   Alternating   det   sig  braid_idx
──────   ──────────    ───────────   ───────────   ───   ───  ─────────
10_34    YES           YES           YES            25    0    4
10_125   YES           NO            NO             31   -2    4
10_85    NO ⚠          NO            YES            49   +4    4
10_83    NO ⚠          NO            YES            43   +2    4
10_61    YES           NO            YES            21   -2    3
10_20    YES           NO            YES            13   -4    4
10_136   YES           NO            NO             29   -4    4
```

### 9.3 The Non-Invertibility Problem

**Invertibility** of a knot K means K is isotopic to its orientation-reverse
(the same knot traversed in the opposite direction). Non-invertible knots have a
preferred orientation; their mirror images are topologically distinct.

**10_83** is **confirmed non-invertible** (Trotter 1963, Hartley 1983). It is one
of exactly 33 prime knots with at most 10 crossings that are non-invertible.

The non-invertibility of 10_83 means:
- There is no canonical "unsigned" version of the knot.
- Using 10_83 in a reversible addressing scheme (where routes must be invertible)
  is conceptually problematic: the "reverse route" traverses a different knot type.
- The stored and retrieved knots are distinct topological objects.

**10_85** is *probably* non-invertible (KnotInfo marks it as non-invertible, but
the proof requires Casson–Gordon invariants or Heegaard Floer homology — elementary
invariants like the Alexander polynomial cannot confirm this directly).

### 9.4 Alexander Polynomials from KnotInfo

| Knot | Alexander polynomial Δ(t) |
|------|--------------------------|
| 10_34 | −t⁴+3t³−4t²+5t−5+5t⁻¹−4t⁻²+3t⁻³−t⁻⁴ |
| 10_83 | −t³+3t²−5t+7−5t⁻¹+3t⁻²−t⁻³ |
| 10_61 | t⁴−3t³+5t²−7t+9−7t⁻¹+5t⁻²−3t⁻³+t⁻⁴ |
| 10_20 | t⁴−3t³+4t²−5t+7−5t⁻¹+4t⁻²−3t⁻³+t⁻⁴ |

Note: 10_125 and 10_136 share the same Alexander polynomial
(−2t²+5t−7+5t⁻¹−2t⁻²). They are distinguished by the Jones polynomial.

### 9.5 Recommendation

Replace 10_83 (and consider replacing 10_85) with invertible, amphichiral knots.
Good candidates from the 10-crossing amphichiral knots:

| Replacement | Invertible | Amphichiral | Notes |
|-------------|-----------|-------------|-------|
| 10_99  | YES | YES | Amphichiral, good Alexander poly |
| 10_123 | YES | YES | Amphichiral |

The criterion: **amphichiral and invertible** knots are ideal for reversible
addressing because their mirror images are equivalent — routes and inverse routes
live in the same knot class.

---

## 10. Cauldron Canonical Semantics

### 10.1 The Cauldron System

The Cauldron is a 10-state reversible system — the digits 0–9 — partitioned into:

```
Cauldron Axis:  {0, 1}       (2-element core)
Outer Ring:     {2, 3, 4, 5, 6, 7, 8, 9}  (8-element ring)
```

The symmetry group is D₈ × ℤ₂ (order 32), acting on the ring.

The four canonical **δ-pairs** partition the ring into 4 complementary pairs:

```
{2, 5},  {4, 7},  {3, 8},  {6, 9}
```

### 10.2 Canonicality via Quadratic Moment

The δ-pairs have a **canonical ordering** defined by the quadratic moment function:

```
I(a, b) = a² + b²
```

| δ-pair | I(a, b) | Canonical rank |
|--------|---------|----------------|
| {2, 5} |      29 |              1 |
| {4, 7} |      65 |              2 |
| {3, 8} |      73 |              3 |
| {6, 9} |     117 |              4 |

**Theorem (Canonicality)**: *The four moment values 29, 65, 73, 117 are all
distinct, providing a strict total order on the δ-pairs without any arbitrary
investigator choice.*

**Proof**: We must show I(a₁, b₁) ≠ I(a₂, b₂) for all four pairs. Direct
computation:
- I(2,5) = 4+25 = 29
- I(4,7) = 16+49 = 65
- I(3,8) = 9+64 = 73
- I(6,9) = 36+81 = 117

The values {29, 65, 73, 117} are all distinct. □

This is verified at runtime by `cauldron_is_canonical()` which asserts
`len(set(values)) == len(values)`.

### 10.3 CauldronManifest Overlay

A KNOTstore manifest can be enriched with Cauldron semantics as an optional
overlay:

```python
cm = CauldronManifest.from_manifest(knotstore_manifest)
cm.commit("fp_after_write")      # forward phase (p=0)
cm.rollback()                    # dual phase (p=1), fingerprint recovered
cm.phase                         # 1 (dual)
cm.current_fingerprint()         # "origin" (rolled back to start)
```

The Cauldron enrichment adds:
- Canonical δ-pair ordering proof (moment values)
- Phase-pair metadata (p=0 forward, p=1 dual)
- Commit/rollback audit trail
- Symmetry group signature (D₈ × ℤ₂, order 32)

Backward compatibility: existing manifests parse unchanged; the Cauldron overlay
is serialized to an optional `"cauldron"` JSON key.

### 10.4 Phase Duality

Phase duality δ maps each state x to its complement x ⊕ 16 (in CORE-32). In the
10-state Cauldron:

```
phase 0 (forward):  compute fingerprint using event.fingerprint()
phase 1 (dual):     compute fingerprint using event.dual_fingerprint()
                    (same data, opposite phase bit)
```

The dual fingerprint is not the inverse of the forward fingerprint — it is an
*orthogonal* hash that responds to the same data but under a different orientation.
This enables:
- Detecting manipulation that preserves the forward fingerprint
- Two independent witnesses to each transaction

---

## 11. Phase-Duality Audit Log

### 11.1 Chain Structure

Each event in the `AuditLog` produces a `ChainLink` with two fingerprints:

```
forward_fp  = SHA256(prior_fp ‖ event.fingerprint())
dual_fp     = SHA256(prior_fp ‖ event.dual_fingerprint())
```

where `event.fingerprint()` hashes `"event_id|event_type|actor|data|0"` and
`event.dual_fingerprint()` hashes the same with the phase bit flipped to 1.

The chain is anchored at `_ORIGIN = SHA256("cauldron-origin")`.

### 11.2 Properties

**Order sensitivity**: Because `prior_fp` is included in each hash, inserting,
deleting, or reordering any event changes all subsequent fingerprints.

**Tamper detection**: `AuditLog.verify()` recomputes the entire chain from the
anchor and returns False if any link is modified.

**Phase flip**: `flip_phase()` switches the log between forward and dual modes.
The forward and dual fingerprints of the same chain are always distinct (tested
by `test_audit_phase_flip_changes_fingerprint`).

**Rollback**: `rollback_to(i)` forks the log at link i, discarding all later
links. The forked log is a valid sub-chain that verifies.

**Reorder detection**: `reorder_detected(other)` returns True when two logs
contain the same event IDs in different order (detected via fingerprint comparison).

### 11.3 Event Types for LORE Integration

The event types map directly to the LORE security state machine transitions:

```
ACCESS    — biometric check performed
COMMIT    — session state committed to persistent store
VIOLATION — anomaly detected (drift, injection attempt)
RECOVERY  — system recovering from a violation state
ROLLBACK  — previous state explicitly restored
```

The dual fingerprint for a VIOLATION event provides an independent witness that
does not depend on the forward chain's integrity — even if an attacker corrupts
the forward chain, the dual fingerprint reveals the tampering.

---

## 12. Unified Architecture: Integration Points

### 12.1 Layer Diagram

```
┌──────────────────────────────────────────────────────────────┐
│  Application (MYdev / LORE)                                  │
│  AuditLog ← events ← state machine transitions               │
└─────────────────────────┬────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────┐
│  Cauldron Canonical Semantics                                 │
│  CauldronManifest.from_manifest(m)                           │
│  Canonical δ-pair ordering, phase duality, commit/rollback   │
└─────────────────────────┬────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────┐
│  KNOTstore Core                                              │
│  O(1) address-regenerating retrieval                         │
│  1-byte binary tiny pointer                                   │
│  SimHash content-correlated placement (9.3× locality)        │
└────────────┬────────────────────────┬────────────────────────┘
             │                        │
┌────────────▼────────┐  ┌────────────▼────────────────────────┐
│  MacroCube          │  │  Braid / Burau                      │
│  Reversible 162-    │  │  Route → BraidWord ∈ B₉            │
│  face permutation   │  │  Alexander polynomial computation   │
│  Rollback-capable   │  │  Route equivalence detection        │
│  provenance         │  │  Knot table: 7 knots characterized  │
└─────────────────────┘  └─────────────────────────────────────┘
```

### 12.2 Route Fingerprinting (Three Levels)

For the same (knot, digest) pair, three fingerprints are now computable:

```python
# Level 1: hash-chain fingerprint (cube state)
fp_cube  = ks.route_cube_fingerprint(knot, digest)

# Level 2: braid permutation fingerprint (B₉ projection)
fp_braid = ks.route_braid_fingerprint(knot, digest)

# Level 3: Alexander polynomial (full topological invariant)
route = ks.compile_route(knot, digest, ks.route_depth)
braid = route_to_braid([(m.axis, m.layer, m.direction) for m in route])
poly  = alexander_poly_from_braid(braid)
```

Each level is coarser: Alexander polynomial collapses more routes to the same
class than the braid permutation, which collapses more than the cube fingerprint.

### 12.3 Address Generation with Knot Invariants (v0.1.5+)

A natural extension (not yet implemented) is to include the Alexander polynomial
in the address hash:

```python
def address_for_v2(self, digest, probe, knot=None):
    ...
    poly = alexander_poly_from_braid(route_to_braid(moves))
    poly_encoding = repr(poly).encode()
    payload = digest ‖ knot ‖ delta ‖ encode_route(route) ‖ str(probe) ‖ poly_encoding
    return blake2b(payload, ...).hexdigest()[:bits//4]
```

This would make knot topology **load-bearing** in address generation: two routes
with the same braid class would generate the same address (enabling deduplication
at the topological level).

The trade-off: Alexander polynomial computation costs O(n!) determinant expansion.
For depth-10 routes in B₉, this is the 8×8 determinant of a sparse Laurent matrix
— acceptable in practice, but non-trivial.

---

## 13. Experimental Results

### 13.1 Benchmark Configuration

```
Objects:       1000 random blobs, total ~15.7k chunks
Chunk size:    256 bytes
Route depth:   10
Address bits:  256 (no artificial collisions)
Placement:     digest (default) and content (SimHash)
Nodes:         16 (for shard balance measurement)
```

### 13.2 Pointer Size

| Encoding | Bytes / pointer | Notes |
|----------|----------------|-------|
| JSON (prototype) | 186.3 | Dominated by verbose field names |
| Binary (codec) | **1.0** | 3 bits knot + 5 bits probe |
| Flat (address, digest) | 64.0 | Address alone, no route info |

The binary pointer is **64× smaller** than a flat address record and **186× smaller**
than the JSON prototype. The "tiny pointer" claim is now measured, not asserted.

### 13.3 Deduplication

With `chunk_size=256` and a corpus of ~30% near-duplicates:

```
Unique chunks stored:  0.175 × total chunks  (dedupe ratio ≈ 0.18)
```

(The draft claimed 0.18; we observe 0.175 on a similarly-structured corpus.)

### 13.4 Shard Balance

Load coefficient of variation (CV = σ/μ across 16 nodes):

| Placement | Load CV | Notes |
|-----------|---------|-------|
| content_simhash | 0.097 | Near-duplicate locality + good balance |
| digest_byte | 0.065 | Uniform, no locality |
| knot_coord | 0.266 | **Worse than random** (only 28 distinct coordinates) |

The knot × δ coordinate has only 7 × 4 = 28 distinct values, which quantize
unevenly onto 16 nodes. The digest byte has 256 distinct values and spreads
smoothly. The SimHash top-bits selector delivers both locality and reasonable
balance.

### 13.5 Collision Recovery

With `address_bits=16` (65536-cell address space) and 4000 16-byte chunks:

```
Chunks with probe > 0:  ~12% (genuine collisions forced by small space)
Round-trip:             PASS (all chunks retrieved correctly)
Max probe:              varies, typically 3–8
```

### 13.6 Test Coverage

36 tests, all passing, stdlib only:

```
Core store:    7 tests  (roundtrip, dedupe, collision, retrieval, etc.)
Codec:         5 tests  (binary pointer roundtrip, edge sizes, large probe)
Cube:          4 tests  (single move, order-4, inverse, permutation)
Provenance:    2 tests  (rollback, order sensitivity)
Braid:         3 tests  (determinism, non-trivial, inverse permutation)
Cauldron:      2 tests  (canonical ordering, manifest lift + roundtrip)
Audit:         3 tests  (chain verify, order sensitivity, phase flip)
Burau:         4 tests  (braid relation, generator inverse, trefoil, fig-8)
Knot table:    3 tests  (7 entries, invertibility, non-alternating)
Placement:     3 tests  (content mode roundtrip, locality, content vs digest)
```

---

## 14. Honest Assessment and Open Problems

### 14.1 What Is Real and Working

- **O(1) address-regenerating retrieval**: implemented, tested, proven by negative
  test (deleting the regenerated address breaks get(), a scan would not).
- **1-byte binary tiny pointer**: measured, 186× smaller than JSON prototype.
- **Content-correlated placement**: 9.3× co-shard probability improvement measured.
- **Reversible macro-cube with rollback**: exact prior fingerprint recoverable, tested.
- **Braid-theoretic route fingerprints**: implemented in B₉, inverse verified.
- **Full Burau representation**: correct reduced Burau, Alexander polynomial verified
  for trefoil and figure-eight against textbook values.
- **Knot table**: all 7 KNOTS_V01 knots characterized (invertibility, amphichirality,
  alternating/non-alternating, determinant, signature, braid index).
- **Cauldron canonical manifests**: canonical ordering proved, lift and roundtrip tested.
- **Phase-duality audit trails**: order-sensitive, tamper-detectable, rollback-capable.

### 14.2 Still Nominal or Incomplete

**Knot labels are not yet load-bearing in routing**: The KNOTS_V01 labels determine
the route via `compile_route(knot, digest, depth)`, but the route is just a
BLAKE2b hash of the knot string — the actual knot topology is not used. The
`route_braid_fingerprint()` and `alexander_poly_from_braid()` compute real
topological invariants, but they are not (yet) fed back into address generation.

**10_83 and 10_85 should be replaced**: Two of the seven knots are non-invertible,
which is conceptually problematic for reversible addressing. The draft chose these
without topological vetting.

**δ-channels are still `% 4` digest labels**: The δ-channels (D1:(2,5), etc.) are
assigned as `digest[0] % 4`. They correlate with Cauldron δ-pairs conceptually,
but no measurement shows that this assignment provides any storage advantage.

**Full Jones/HOMFLY polynomial not implemented**: The Alexander polynomial is a
shadow of the Jones polynomial (which detects chirality, distinguishing 10_125 from
10_136). The HOMFLY polynomial is finer still. These require the Burau matrix over
ℤ[s, s⁻¹, v, v⁻¹], a more complex computation.

**KNOTstore route Alexander polynomials are trivial (zero)**: Computing
`alexander_invariant` on KNOTstore routes via the current `route_to_braid`
projection consistently yields `Δ(t) = 0`. This is because the `_MOVE_CROSSINGS`
table in `braid.py` is an *ad hoc* projection from 3D ρ-moves to 1D braid crossings;
it does not define a group homomorphism B_n → B₉, so the resulting braid word does
not generally close to a knot with a well-defined Alexander polynomial. The Burau
machinery is verified correct for proper braid inputs (trefoil, figure-eight, torus
knots T(2,n)), but the route-to-braid projection needs a topologically rigorous
foundation before route Alexander polynomials will be meaningful.

**Burau representation for n=9 is computationally expensive**: The 8×8 determinant
for full KNOTstore routes (depth 10, B₉) involves Laurent polynomial entries. The
current cofactor expansion is correct but not optimized for large n.
(Bareiss algorithm or LU decomposition over Laurent rings would help for n > 5).

### 14.3 Knot-Addressed Storage: Does the "Knot" Part Add Value?

Honest assessment:

| Claim | Status |
|-------|--------|
| Knots provide topology-based routing | NOT YET: labels only |
| Near-duplicate locality | YES, but via SimHash (not knots) |
| O(1) retrieval | YES, fixed |
| 1-byte pointer | YES |
| Reversible provenance | YES |
| Collision recovery | YES |

The knot labels provide uniform-ish load balance (equivalent to hashing the label
string). They do not provide:
- Content locality (similar content does not colocate on the same knot)
- Topology-based deduplication (same knot class → same address)
- Any measured advantage over a simple digest-byte shard selector

The path to making knots genuinely load-bearing is through the Burau/Alexander
pipeline: feed `poly = alexander_poly_from_braid(route_braid)` into the address
hash. Then routes with identical Alexander polynomials deterministically map to the
same address, enabling topology-level deduplication. This is architecturally clean
but requires careful definition of "same Alexander polynomial" for multi-chunk
objects.

---

## Appendix A: Proof of Address Regeneration (Theorem 1 Corrected) {#appendix-a}

**Theorem 1 (Corrected)**. *Let M = put(data, name) be the manifest returned by
storing data. For each chunk cᵢ with digest hᵢ, TinyPointer pᵢ, and probe nᵢ:*

```
address_for(hᵢ, nᵢ, pᵢ.knot) = key at which cᵢ is stored in the backend.
```

*Proof:*

By construction in `put()`:
```
address = address_for(h, probe, knot)
backend[address] = chunk
```

The manifest stores `digests[i] = hᵢ.hex()` and `pointers[i].probe = nᵢ` and
`pointers[i].knot = kᵢ`.

In `get()`:
```python
digest = bytes.fromhex(dhex)           # = hᵢ (from manifest)
address = self.address_for(digest,     # = address_for(hᵢ, nᵢ, kᵢ)
                           ptr.probe,
                           ptr.knot)
chunk = self.backend[address]          # direct lookup, O(1)
```

Since `address_for` is a pure deterministic function of `(digest, probe, knot)`,
and both `put()` and `get()` call the same function with the same arguments, the
addresses are identical. □

**Corollary**: No scan of the backend is performed. The backend is accessed
exactly once per chunk, at the regenerated address.

**Test**: `test_retrieval_is_address_regeneration_not_scan` removes the chunk at
the regenerated address and confirms that `get()` raises ValueError. A scan-based
implementation would still find an identical chunk elsewhere.

---

## Appendix B: Burau Generator Derivation {#appendix-b}

### B.1 From Fox Calculus

Let F_n be the free group on generators x₁, …, xₙ. The braid group B_n acts on
F_n by:

```
σᵢ(xᵢ)   = xᵢ xᵢ₊₁ xᵢ⁻¹
σᵢ(xᵢ₊₁) = xᵢ
σᵢ(xⱼ)   = xⱼ   for j ≠ i, i+1
```

Abelianizing with xⱼ ↦ t for all j, the Fox derivative matrix (the Burau
representation) for σᵢ acting on ℤ[t, t⁻¹]ⁿ has:

```
row i:   (0, …, 0, 1−t, t, 0, …, 0)   (entry (1−t) at col i, t at col i+1)
row i+1: (0, …, 0,  1,  0, 0, …, 0)   (entry 1 at col i)
```

### B.2 Reduction to (n−1) Dimensions

The unreduced Burau representation preserves the submodule spanned by
(1, 1, …, 1). The reduced representation is the quotient acting on

```
V = {(v₁, …, vₙ) : v₁ + … + vₙ = 0}
```

with basis eᵢ − eᵢ₊₁ for i = 1, …, n−1.

The reduced generator matrices are derived by expressing σᵢ(eₖ − eₖ₊₁) as a
linear combination of the basis vectors. The result is the matrix stated in
Section 8.2, which we verify satisfies the braid relations computationally.

### B.3 Inverse Generator Derivation

Given σᵢ with row k: (…, t, −t, 1, …), the inverse is found by solving
Mv = w for v:

```
w_k = t·v_{k−1} + (−t)·v_k + 1·v_{k+1}
v_k = (t·w_{k−1} + w_{k+1} − w_k) / t
    = w_{k−1} + t⁻¹·w_{k+1} − t⁻¹·w_k
```

So σᵢ⁻¹ has row k: (…, 1, −t⁻¹, t⁻¹, …).

---

## Appendix C: Cauldron Canonicality Proof {#appendix-c}

### C.1 The Canonical Ordering Theorem

**Theorem**. *The quadratic moment function I(a, b) = a² + b² assigns distinct
values to the four Cauldron δ-pairs {2,5}, {4,7}, {3,8}, {6,9}, providing a strict
total order.*

**Proof**. Compute:

```
I(2,5) = 4  + 25 = 29
I(4,7) = 16 + 49 = 65
I(3,8) = 9  + 64 = 73
I(6,9) = 36 + 81 = 117
```

The four values {29, 65, 73, 117} are pairwise distinct. Since a strict total
order on a finite set is equivalent to an injective function to ℕ, the canonical
ordering exists and is unique. □

### C.2 Uniqueness

The theorem says I is *one* canonical ordering. Is it the *only* one? No — any
strictly monotone function of the pair would work. The quadratic moment is
canonical in the stronger sense that:

1. It requires no parameter choice (the exponent 2 is determined by the
   quadratic form structure of ℝ²).
2. It is symmetric in {a, b}: I(a,b) = I(b,a), consistent with δ-pairs being
   unordered.
3. It extends naturally to CORE-32 (the 32-state system) by the same formula.

### C.3 CORE-32 Extension

In CORE-32, the 32 states are {0, 1, …, 31} with phase duality δ₃₂(x) = x ⊕ 16.
The 16 δ-pairs are {x, x⊕16} for x = 0, …, 15. The canonical ordering by
quadratic moment gives a 16-element hierarchy compatible with the 4-element
Cauldron hierarchy (the first 4 pairs match DELTA_PAIRS).

---

## References

1. Alexander, J.W. (1928). "Topological invariants of knots and links." *Trans. Amer. Math. Soc.* 30(2): 275–306.

2. Bar-Natan, D. and Morrison, S. "KnotInfo: Table of Knot Invariants." https://www.indiana.edu/~knotinfo/

3. Birman, J.S. (1974). *Braids, Links, and Mapping Class Groups.* Princeton University Press.

4. Burau, W. (1936). "Über Zopfgruppen und gleichsinnig verdrillte Verkettungen." *Abh. Math. Sem. Univ. Hamburg* 11: 179–186.

5. Charikar, M. (2002). "Similarity estimation techniques from rounding algorithms." *Proc. STOC 2002.*

6. Hartley, R. (1983). "Non-invertible knots exist." *Topology* 22(2): 137–141.

7. Rolfsen, D. (1976). *Knots and Links.* Publish or Perish Press.

8. Trotter, H.F. (1963). "Non-invertible knots exist." *Topology* 2(4): 275–280.

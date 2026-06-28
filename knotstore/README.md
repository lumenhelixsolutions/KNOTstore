# KnotStore v0.1.1 — corrected reference implementation

A runnable, corrected rewrite of the prototype in the LENS-64S draft
(*"Knot-Addressed Structural Hashing and Tiny-Pointer Storage"*). The goal of
this directory is to make the paper's central thesis — *tiny pointers
deterministically regenerate storage routes* — actually true in code, and to
replace the draft's illustrative numbers with measured ones.

Stdlib only. `python3 knotstore.py`, `python3 test_knotstore.py`, `python3 bench.py`.

## What was broken in the draft, and what changed

### 1. Retrieval did not regenerate the address (the central bug)
The draft's `get()` ignored the derived address entirely and **linearly scanned
the whole backend**, matching chunks by a 96-bit digest prefix. That is O(N)
content search, and the knot / δ-channel / route apparatus — the entire point of
the paper — was never used on the read path. `Theorem 1`'s proof described an
address-regeneration algorithm that the code did not implement.

**Fixed:** a single `address_for(digest, probe)` is the source of truth for
placement, used by **both** `put()` and `get()`. Retrieval recomputes
knot → δ → route → address and does a direct **O(1)** backend lookup. Test
`test_retrieval_is_address_regeneration_not_scan` proves the chunk is reached
via the regenerated key (deleting that key makes `get` fail; a scan would not).

### 2. The pointer could not regenerate the address
The draft derived the address from the full 256-bit digest but stored only a
64-bit seed prefix in the pointer — so the pointer literally lacked the
information to reproduce the address, and the dormant `pointer_to_address`
re-derived from `sha256(seed+knot)`, a *different* value than the stored key.

**Fixed:** the full chunk digest (the Merkle leaf, not secret) lives once in the
manifest; the pointer carries only the `probe` (the one datum not derivable from
the digest) plus screening metadata. Address regeneration is now exact.

### 3. Collision recovery was untestable
With full 256-bit blake2b addresses, collisions never occur, so the draft's
collision theorems and `collisions: 3` benchmark line were unfalsifiable.

**Fixed:** an `address_bits` knob shrinks the address space.
`test_collision_recovery_small_address_space` runs 4000 chunks into a 16-bit
space, asserts probes actually fire, and confirms round-trip still holds.

## Measured findings (these contradict the draft)

From `bench.py` (1000 objects, ~15.7k chunks, 256-byte chunks):

| Claim in draft | Draft value | **Measured** |
|---|---|---|
| `avg_pointer_bytes` | 96 | **186** |
| `pointer_compression_ratio` | 0.375 (62.5% saving) | **2.33 (≈2.3× *larger*)** |
| dedupe ratio | 0.18 | 0.175 (corpus was built to ~0.18) |
| roundtrip / corruption detect | pass | pass |

Two honest conclusions:

1. **The JSON "tiny pointer" was larger than a flat address→digest record**, not
   smaller — the verbose JSON (38-char `algorithm` string, labels like
   `"D4:(6,9)"`) dominated. **Fixed in v0.1.2 by `codec.py`** (see next section):
   the binary pointer is **1 byte**.

2. **The knot×δ coordinate shards *worse* than a one-byte baseline**
   (load CV ≈ 0.28 vs 0.11 across 16 nodes). There are only 7×4 = 28 distinct
   coordinates, which quantize unevenly onto 16 nodes; a single digest byte (256
   values) spreads smoothly. And because the coordinate is itself digest-derived,
   it provides **uniform-ish balance but zero content locality** — similar
   content does not colocate. "Knot-indexed storage" as defined adds no
   placement value over hashing the digest.

## Content-correlated signature (does the knot layer *ever* buy locality?)

The draft's knot/δ coordinate is digest-derived, so it cannot colocate similar
content. `signature.py` + `bench_locality.py` test whether a content-correlated
placement key fixes that. The signature is a 64-bit SimHash (Charikar) over byte
shingles; shards are taken from its top bits, so similar content shares a shard.

Test corpus: clusters of near-duplicate chunks (one base + variants with a few
flipped bytes, every variant a distinct sha256). Co-shard probability = fraction
of within-cluster pairs landing on the same of 16 nodes (random ≈ 0.0625):

| placement | co-shard prob | vs random | load CV |
|---|---|---|---|
| `content_simhash` | **0.58** | **9.3×** | 0.097 |
| `digest_byte` (draft-style) | 0.059 | ~1.0× (none) | 0.065 |
| `knot_coord` (draft knot×δ) | 0.069 | ~1.1× (none) | 0.266 |

Edit-sensitivity sweep — locality decays smoothly toward random as content
diverges (confirms it tracks similarity, not noise):

| edits/variant | intra-cluster SimHash Hamming | co-shard (simhash) |
|---|---|---|
| 1 | 4.6 | 0.75 |
| 3 | 8.0 | 0.55 |
| 8 | 12.7 | 0.45 |
| 20 | 19.2 | 0.25 |
| 64 | 27.9 | 0.11 |

**Conclusion:** a content-correlated key delivers ~9× better near-duplicate
locality at a small balance cost (and balances *better* than the draft's knot
coordinate). The digest-derived knot/δ coordinate provides none. If the knot
layer is to mean anything, its selector must be driven by a signature like this,
not by `digest[1] % 7`.

## v0.1.2 — content placement wired into the store, and a real binary pointer

Two follow-ups from the findings above, now implemented.

### Content placement (`KnotStore(placement="content")`)
The SimHash selector is wired into the store's knot choice, so placement is
content-correlated end to end:
- `knot_for(data, digest)` picks the knot from the content SimHash (top 3 bits);
  near-duplicate chunks share a knot. The chosen knot is stored in the pointer,
  so **retrieval still never needs the chunk** to reconstruct the address —
  round-trip stays exact (`test_content_placement_roundtrip`).
- `shard_for(data, digest, num_nodes)` shards by SimHash top bits in content
  mode (the locality win above), or by a digest byte in `"digest"` mode.
- Default remains `placement="digest"` for backward compatibility.

### Binary tiny pointer (`codec.py`) — the original intent, restored
The draft meant *binary* pointers; the prototype had drifted to JSON. The codec
hoists everything constant or derivable out of the per-chunk pointer:

| field | where it lives now |
|---|---|
| version, algorithm, depth, address_bits, chunk_size, placement | manifest header (once) |
| delta | recomputed from the digest |
| size | recomputed (chunk_size, or remainder for the last chunk) |
| digest_prefix | recomputed from the digest table |
| **knot** (3 bits) + **probe** (5 bits, varint escape) | **the 1 byte we store per pointer** |

Measured (`bench.py`, codec round-trips verified in `test_knotstore.py`):

| pointer encoding | bytes/pointer | vs JSON |
|---|---|---|
| JSON (drifted prototype) | 186.3 | 1.0× |
| **binary (codec)** | **1.0** | **0.005× (≈186× smaller)** |

`decode_manifest(encode_manifest(m))` reproduces the manifest exactly and the
decoded manifest still retrieves the data; edge sizes (empty, 1-byte, ragged
last chunk) and the large-probe varint escape are covered by tests.

> Note on the *manifest* total: the binary manifest is dominated by the 32-byte
> digest table (the Merkle leaves / integrity anchor), which any content-
> addressed store needs regardless. The "tiny pointer" claim is about the route
> descriptor — that is the 1 byte.

## v0.1.3 — the reversible macro-cube actually does something

Previously the ρ-moves were never applied to anything: `compile_route` produced
move objects only to stringify them into hash input, so the "reversible
manifold" was notational. `cube.py` makes it a real **27-subcube / 162-face**
state that moves permute, and `provenance.py` puts the reversibility to use.

- `cube.py` — `MacroCube` with `apply_move` / `apply_route` / `inverse_route`.
  A 90° slice turn rotates the 9 subcubes in a layer, updating positions *and*
  face orientations; every move is a bijection over the 162 faces. Verified by
  tests: a single move is non-identity, any move applied 4× returns to solved,
  `W⁻¹·W = id` for random routes (the draft's Prop 2, now a *tested fact* rather
  than an assertion), and no face is ever lost (multiset of faces preserved).
  The store's own routes are real cube paths too (`route_cube_fingerprint`).
- `provenance.py` — `ProvenanceLog` advances a cube state per lineage event
  (`H_{t+1} = F(H_t, ρ_t)`, the draft's §12.4). Because moves are invertible it
  has a property a **one-way hash chain does not**:
  - **rollback** — recover the exact prior fingerprint by applying the inverse
    route (a hash chain cannot invert `H_{t+1}` back to `H_t`);
  - **replay-to-origin** — rolling the whole lineage back lands on the identity
    cube, so a claimed lineage verifies in both directions;
  - **order sensitivity** — moves don't commute, so reordering events changes
    the fingerprint (detectable).

  Honest scope: the cube makes provenance *reversible and order-sensitive*; it is
  not itself a security primitive — tamper resistance still rests on the hash used
  for route derivation and fingerprints. The value over a plain hash chain is
  invertibility, not cryptographic strength (a one-way baseline is included in
  `provenance.py` for contrast).

## v0.1.4 — three Cauldron integrations: braid routes, canonical manifests, phase audit

Parallel integration of three synergies with the Cauldron / CORE-32 architecture.

### Braid representation (`braid.py`)
The ρ-moves are now translatable to **Alexander braids** (elements of B₉, the braid
group on 9 strands). Each 90° layer rotation induces 4 transpositions; a 10-move
route becomes a 40-crossing braid word. Two routes with the same `braid_fingerprint`
are topologically equivalent under the B₉ projection, enabling:
- **Route equivalence detection** — collapse equivalent routes to a single canonical form
- **Collision analysis** — routes that reach the same address may share a braid class
- **Knot labels made computable** — `route_braid_fingerprint(knot, digest)` on `KnotStore`
  produces a measured invariant tied to the knot label, addressing the v0.1.3 TODO

The invariant is `B(length, permutation)` — not the full Alexander polynomial (which
requires the Burau representation), but sufficient for grouping and collision detection.
Full polynomial computation is the next step.

### Cauldron canonical semantics (`cauldron.py`)
The **Cauldron** (CORE-32's 10-state system, digits 0–9) has a canonical ordering
provably free of arbitrary choices: the quadratic moment function I(a,b) = a² + b²
assigns distinct values to the four δ-pairs {2,5}, {4,7}, {3,8}, {6,9}, fixing their
order without investigator input. `cauldron_is_canonical()` tests this at runtime.

`CauldronManifest.from_manifest(m)` lifts any KNOTstore manifest into a Cauldron-
enriched form with:
- Canonical δ-pair ordering proof (moment values 29, 65, 73, 117)
- Phase-pair metadata (p=0 forward, p=1 dual)
- Commit/rollback audit trail
- Symmetry group signature (D₈ × ℤ₂, order 32)

Backward-compatible: existing manifests parse through the codec unchanged; Cauldron
enrichment is an optional overlay serialised to a `"cauldron"` JSON key.

### Phase-duality audit log (`audit.py`)
A stand-alone **two-phase audit chain** using Cauldron's phase duality concept:
every event produces a *forward* fingerprint (p=0) and a *dual* fingerprint (p=1).
Properties measured by tests:
- **Order sensitivity** — reordering events changes the fingerprint (detectable)
- **Tamper detection** — `verify()` recomputes the whole chain
- **Phase flip** — `flip_phase()` switches to the dual fingerprint without altering data
- **Rollback** — `rollback_to(i)` forks the chain at link *i*

Integration point: LORE security in MYdev. Event types map directly to biometric
state-machine transitions (ACCESS, COMMIT, VIOLATION, RECOVERY).

## v0.1.5 — full Burau representation and knot verification

### Reduced Burau representation and Alexander polynomials (`burau.py`)
The knot labels now have a computable topological invariant. `burau.py` implements:
- **`LaurentPoly`** — Laurent polynomials over ℤ with full arithmetic and normalization
- **`reduced_burau_generator(n, i, ε)`** — the (n−1)×(n−1) reduced Burau matrix for σᵢ^ε
- **`braid_to_burau_matrix`** — product representation for arbitrary braid words in Bₙ
- **`alexander_invariant`** — det(I − ρ̄(β)) / (1+t+…+t^{n-1})

Verified against KnotInfo:

| Knot | Braid word | Computed Δ(t) | Expected | Match |
|---|---|---|---|---|
| Trefoil 3_1 | σ₁³ in B₂ | 1 − t + t² | 1 − t + t² | ✓ |
| Figure-eight 4_1 | σ₁σ₂⁻¹σ₁σ₂⁻¹ in B₃ | 1 − 3t + t² | 1 − 3t + t² | ✓ |
| Cinquefoil T(2,5) | σ₁⁵ in B₂ | 1 − t + t² − t³ + t⁴ | 1 − t + t² − t³ + t⁴ | ✓ |

Known limitation: KNOTstore routes in B₉ produce `det(I − M) = 0` because
`route_to_braid()` is an ad hoc projection, not a group homomorphism. Documented
honestly; a genuine embedding of cube symmetries in Bₙ is future work.

### Knot table verification (`knot_table.py`)
All seven KNOTS_V01 knots verified against KnotInfo:

| Knot | Invertible | Amphichiral | Alternating | det | sig |
|---|---|---|---|---|---|
| 10_34  | ✓ | ✓ | ✓ | 25 |  0 |
| 10_125 | ✓ | ✗ | ✗ | 31 | −2 |
| 10_85  | ✗ probable | ✗ | ✓ | 49 | +4 |
| 10_83  | ✗ confirmed | ✗ | ✓ | 43 | +2 |
| 10_61  | ✓ | ✗ | ✓ | 21 | −2 |
| 10_20  | ✓ | ✗ | ✓ | 13 | −4 |
| 10_136 | ✓ | ✗ | ✗ | 29 | −4 |

**10_83 confirmed non-invertible** (Trotter 1963, Hartley 1983). Recommendation:
replace 10_83 → 10_99 and 10_85 → 10_123 (both amphichiral + invertible).

## Honest status of the architecture

- **Real and working:** deterministic content-addressed store, O(1)
  address-regenerating retrieval, open-address collision recovery, exact-dup
  collapse, Merkle-root tamper detection; a **1-byte binary tiny pointer**;
  content-correlated placement with measured ~9× near-duplicate locality;
  working reversible macro-cube with rollback-capable provenance;
  braid-theoretic route fingerprints; Cauldron canonical manifests;
  phase-duality audit trails; **full Burau representation with verified
  Alexander polynomials** (trefoil, figure-eight, cinquefoil against KnotInfo).
- **Route Alexander polynomials are zero:** the ρ-move→braid projection is ad hoc;
  `det(I−ρ̄(β)) = 0` for all KNOTstore routes. Documented, not papered over.
- **δ-channels are labels:** assigned by `digest[0] % 4`; no knot-theoretic meaning.
- **10_83/10_85 should be replaced:** see above.

## Files
- `knotstore.py` — the corrected store (put / get / verify / address_for /
  knot_for / shard_for / node_for / route_cube_fingerprint / route_braid_fingerprint).
- `signature.py` — 64-bit SimHash content signature + top-bits shard mapping.
- `codec.py` — binary tiny-pointer manifest codec (encode / decode / size_report).
- `cube.py` — working reversible 162-face macro-cube (apply/inverse routes).
- `provenance.py` — reversible, rollback-capable provenance accumulator + demo.
- `braid.py` — Alexander braid representation of ρ-move routes; B₉ group algebra.
- `burau.py` — **new v0.1.5**: reduced Burau matrices; Alexander polynomial computation.
- `knot_table.py` — **new v0.1.5**: KnotInfo-verified knot properties for all KNOTS_V01.
- `cauldron.py` — Cauldron canonical semantics + CauldronManifest overlay.
- `audit.py` — phase-duality two-phase audit log; order-sensitive tamper detection.
- `bench.py` — measured benchmark (pointer sizes JSON vs binary, dedupe, shard balance).
- `bench_locality.py` — co-shard locality benchmark + edit-sensitivity sweep.
- `test_knotstore.py` — **36 tests** (all pass).

Run: `python3 test_knotstore.py`, `python3 bench.py`, `python3 bench_locality.py`,
`python3 burau.py`, `python3 braid.py`, `python3 cauldron.py`, `python3 audit.py`,
`python3 provenance.py`, `python3 cube.py`.

"""
KnotStore v0.1.1 — corrected reference implementation.

This is a corrected rewrite of the prototype in the LENS-64S draft. The two
substantive fixes relative to that draft:

  1. RETRIEVAL ACTUALLY REGENERATES THE ADDRESS.
     In the draft, `get()` ignored the derived address entirely and performed a
     linear scan over the whole backend, matching on a digest prefix. That is
     O(N) content search, and it contradicts the paper's central thesis that a
     tiny pointer regenerates a storage route. Here, `get()` recomputes
     knot -> delta -> route -> address from the pointer (+ the chunk digest held
     in the manifest, which is the Merkle leaf anyway) and does a direct O(1)
     backend lookup. The knot/route machinery is now load-bearing.

  2. THE ADDRESS CAN ACTUALLY BE REGENERATED FROM WHAT IS STORED.
     The draft pointer stored only a 64-bit seed prefix, but the address was
     derived from the full 256-bit digest -- so the pointer literally did not
     contain enough information to reproduce the address. The full chunk digest
     is the integrity anchor and is not secret, so we keep it in the manifest
     (it is the Merkle leaf) and regenerate from it.

It also adds an `address_bits` knob so the address space can be shrunk to
*actually exercise and measure* collision recovery (with full 256-bit blake2b
addresses, collisions never occur, so the draft's collision claims were
untestable), and a `node_for()` shard function so placement load-balance can be
measured against a baseline (see bench.py).

Honest scope note: the knots and delta-channels here are deterministic functions
of the digest, so they provide uniform load balance but NOT content locality
(similar content does not colocate). That limitation is documented and measured
rather than papered over. Stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from hashlib import sha256, blake2b
from typing import Dict, List, Optional
import json

from signature import simhash64, shard_of

AXES = ("X", "Y", "Z")
LAYERS = (-1, 0, 1)
DIRS = (-1, 1)

KNOTS_V01 = (
    "10_34", "10_125", "10_85", "10_83", "10_61", "10_20", "10_136",
)

DELTA_CHANNELS = (
    "D1:(2,5)", "D2:(4,7)", "D3:(3,8)", "D4:(6,9)",
)

ALGORITHM = "lens64s-sha256-blake2b-croute-v1.1"


@dataclass(frozen=True)
class RhoMove:
    axis: str
    layer: int
    direction: int

    def inverse(self) -> "RhoMove":
        return RhoMove(self.axis, self.layer, -self.direction)

    def encode(self) -> str:
        return f"{self.axis}{self.layer:+d}{self.direction:+d}"


@dataclass(frozen=True)
class TinyPointer:
    """Compact route descriptor. Note: it does NOT carry the full digest --
    that lives once in the manifest as the Merkle leaf. The pointer carries the
    probe (the only datum not derivable from the digest) plus screening/size
    metadata."""
    version: int
    algorithm: str
    knot: str
    delta: str
    depth: int
    probe: int
    size: int
    digest_prefix: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


@dataclass
class Manifest:
    version: int
    name: str
    chunk_size: int
    total_size: int
    route_depth: int
    address_bits: int
    placement: str
    root_digest: str
    pointers: List[TinyPointer]
    digests: List[str] = field(default_factory=list)  # full chunk digests (Merkle leaves)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)


class KnotStore:
    def __init__(
        self,
        chunk_size: int = 4096,
        route_depth: int = 10,
        address_bits: int = 256,
        placement: str = "digest",
    ):
        if address_bits % 4 != 0 or not (8 <= address_bits <= 256):
            raise ValueError("address_bits must be a multiple of 4 in [8, 256]")
        if placement not in ("digest", "content"):
            raise ValueError("placement must be 'digest' or 'content'")
        self.chunk_size = chunk_size
        self.route_depth = route_depth
        self.address_bits = address_bits
        self.placement = placement
        self.backend: Dict[str, bytes] = {}

    # ---- digests -----------------------------------------------------------
    @staticmethod
    def digest(data: bytes) -> bytes:
        return sha256(data).digest()

    @staticmethod
    def merkle_root(hex_digests: List[str]) -> str:
        if not hex_digests:
            return sha256(b"").hexdigest()
        layer = [bytes.fromhex(h) for h in hex_digests]
        while len(layer) > 1:
            nxt = []
            for i in range(0, len(layer), 2):
                left = layer[i]
                right = layer[i + 1] if i + 1 < len(layer) else left
                nxt.append(sha256(left + right).digest())
            layer = nxt
        return layer[0].hex()

    # ---- chunking ----------------------------------------------------------
    def chunk(self, data: bytes) -> List[bytes]:
        if not data:
            return [b""]
        return [data[i:i + self.chunk_size] for i in range(0, len(data), self.chunk_size)]

    # ---- coordinate selection ----------------------------------------------
    def select_knot(self, digest: bytes) -> str:
        """Digest-derived knot (uniform, no content locality)."""
        return KNOTS_V01[digest[1] % len(KNOTS_V01)]

    def knot_for(self, data: bytes, digest: bytes) -> str:
        """Knot used at write time. In 'content' mode it is driven by the
        content SimHash, so near-duplicate chunks share a knot (locality). The
        chosen knot is stored in the pointer, so retrieval never needs the
        chunk to reconstruct it."""
        if self.placement == "content":
            return KNOTS_V01[(simhash64(data) >> (64 - 3)) % len(KNOTS_V01)]
        return self.select_knot(digest)

    def select_delta(self, digest: bytes) -> str:
        return DELTA_CHANNELS[digest[0] % len(DELTA_CHANNELS)]

    def shard_for(self, data: bytes, digest: bytes, num_nodes: int) -> int:
        """Operational shard. 'content' mode shards by SimHash top bits (gives
        near-duplicate locality at good balance); 'digest' mode shards by a
        digest byte (uniform, no locality)."""
        if self.placement == "content":
            return shard_of(simhash64(data), num_nodes)
        return digest[0] % num_nodes

    def compile_route(self, knot: str, digest: bytes, depth: int) -> List[RhoMove]:
        material = blake2b(
            knot.encode() + digest, digest_size=64, person=b"LENS64S_ROUTE"
        ).digest()
        route: List[RhoMove] = []
        for i in range(depth):
            b0 = material[(3 * i) % len(material)]
            b1 = material[(3 * i + 1) % len(material)]
            b2 = material[(3 * i + 2) % len(material)]
            route.append(RhoMove(AXES[b0 % 3], LAYERS[b1 % 3], DIRS[b2 % 2]))
        return route

    @staticmethod
    def encode_route(route: List[RhoMove]) -> str:
        return "|".join(m.encode() for m in route)

    def route_cube_fingerprint(self, knot: str, digest: bytes) -> str:
        """Apply the compiled route to a real reversible macro-cube and return
        the resulting state fingerprint. Demonstrates that the store's routes are
        genuine, invertible cube paths (see cube.py / provenance.py) rather than
        strings fed to a hash."""
        from cube import MacroCube, RhoMove as CubeMove
        route = self.compile_route(knot, digest, self.route_depth)
        cube = MacroCube()
        cube.apply_route([CubeMove(m.axis, m.layer, m.direction) for m in route])
        return cube.fingerprint()

    def route_braid_fingerprint(self, knot: str, digest: bytes) -> str:
        """Braid-theoretic fingerprint of the route for this knot+digest pair.

        Translates the ρ-move sequence to a braid word (element of B₉) and
        returns its invariant (permutation + length). Routes with identical
        fingerprints are topologically equivalent braids, enabling collision
        analysis and route compression. See braid.py."""
        from braid import route_to_braid, braid_fingerprint
        route = self.compile_route(knot, digest, self.route_depth)
        moves = [(m.axis, m.layer, m.direction) for m in route]
        return braid_fingerprint(route_to_braid(moves))

    def derive_address(
        self, digest: bytes, knot: str, delta: str, route: List[RhoMove], probe: int
    ) -> str:
        payload = b"|".join([
            digest, knot.encode(), delta.encode(),
            self.encode_route(route).encode(), str(probe).encode(),
        ])
        full = blake2b(payload, digest_size=32, person=b"LENS64S_ADDR").hexdigest()
        return full[: self.address_bits // 4]

    def address_for(self, digest: bytes, probe: int, knot: Optional[str] = None) -> str:
        """The single source of truth for placement. Used by BOTH put and get,
        so retrieval is genuinely a regeneration of the same address. `knot` is
        passed explicitly from the pointer at read time (required in 'content'
        mode, where it is not derivable from the digest); when omitted it falls
        back to the digest-derived knot ('digest' mode)."""
        if knot is None:
            knot = self.select_knot(digest)
        delta = self.select_delta(digest)
        route = self.compile_route(knot, digest, self.route_depth)
        return self.derive_address(digest, knot, delta, route, probe)

    # ---- sharding (measurable; see bench.py) -------------------------------
    def node_for(self, digest: bytes, num_nodes: int) -> int:
        """Deterministic shard placement from the knot x delta coordinate.
        Provides uniform load balance; provides NO content locality because the
        coordinate is digest-derived (this is measured, not assumed)."""
        ki = KNOTS_V01.index(self.select_knot(digest))
        di = DELTA_CHANNELS.index(self.select_delta(digest))
        return (ki * len(DELTA_CHANNELS) + di) % num_nodes

    # ---- store / retrieve / verify -----------------------------------------
    def put(self, data: bytes, name: str = "object") -> Manifest:
        chunks = self.chunk(data)
        pointers: List[TinyPointer] = []
        chunk_digests: List[str] = []
        for c in chunks:
            h = self.digest(c)
            h_hex = h.hex()
            knot = self.knot_for(c, h)
            probe = 0
            while True:
                address = self.address_for(h, probe, knot)
                current = self.backend.get(address)
                if current is None:
                    self.backend[address] = c
                    break
                if self.digest(current) == h:  # exact-duplicate collapse
                    break
                probe += 1  # genuine collision: open-address probe
            pointers.append(TinyPointer(
                version=1, algorithm=ALGORITHM,
                knot=knot, delta=self.select_delta(h),
                depth=self.route_depth, probe=probe, size=len(c),
                digest_prefix=h_hex[:24],
            ))
            chunk_digests.append(h_hex)
        return Manifest(
            version=1, name=name, chunk_size=self.chunk_size,
            total_size=len(data), route_depth=self.route_depth,
            address_bits=self.address_bits, placement=self.placement,
            root_digest=self.merkle_root(chunk_digests),
            pointers=pointers, digests=chunk_digests,
        )

    def get(self, manifest: Manifest) -> bytes:
        if len(manifest.pointers) != len(manifest.digests):
            raise ValueError("malformed manifest: pointer/digest length mismatch")
        output = bytearray()
        seen: List[str] = []
        for ptr, dhex in zip(manifest.pointers, manifest.digests):
            digest = bytes.fromhex(dhex)
            address = self.address_for(digest, ptr.probe, ptr.knot)  # O(1) regeneration
            chunk = self.backend.get(address)
            if chunk is None:
                raise ValueError(f"missing chunk at regenerated address {address}")
            if self.digest(chunk) != digest:
                raise ValueError("digest mismatch at regenerated address (tamper/corruption)")
            if len(chunk) != ptr.size:
                raise ValueError("chunk size mismatch")
            output.extend(chunk)
            seen.append(dhex)
        if self.merkle_root(seen) != manifest.root_digest:
            raise ValueError("manifest root mismatch")
        restored = bytes(output)
        if len(restored) != manifest.total_size:
            raise ValueError("total size mismatch")
        return restored

    def verify(self, manifest: Manifest) -> bool:
        try:
            self.get(manifest)
            return True
        except Exception:
            return False


if __name__ == "__main__":
    ks = KnotStore(chunk_size=32, route_depth=10)
    data = b"LENS-64S structural hashing test payload." * 8
    manifest = ks.put(data, name="demo.bin")
    assert ks.get(manifest) == data
    assert ks.verify(manifest)
    print(manifest.to_json())
    print("PASS")

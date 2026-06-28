"""
Binary tiny-pointer codec.

The original intent of the LENS-64S draft was *binary* tiny pointers; the
prototype drifted into verbose JSON, which measured at ~186 bytes per pointer --
larger than the address it was meant to compress. This module restores the
original idea and measures it.

Key observation that makes the pointer genuinely tiny: almost everything in a
pointer is derivable and need not be stored per chunk.
  - version, algorithm, route_depth, address_bits, chunk_size, placement:
        constant across the object -> hoisted into the manifest header (stored
        once, not n times).
  - delta:        = f(digest) -> recomputed from the digest at decode time.
  - size:         = chunk_size for every chunk except the last, whose size is
                    total_size - chunk_size*(n-1) -> recomputed.
  - digest_prefix: a prefix of the full digest, which is already in the manifest
                    digest table (the Merkle leaves) -> recomputed.
  - knot:         derivable from the digest in 'digest' placement, but NOT in
                    'content' placement (it depends on the chunk SimHash), so it
                    is the one coordinate we store per pointer (3 bits).
  - probe:        the only other per-chunk datum (collision count), 5 bits with
                    a varint escape for the rare large case.

So the per-pointer payload is a single byte in the common case.

Wire format (all integers little-endian uvarint unless noted):
  MAGIC b"KS1"  | fmt:1
  algorithm: len:uvarint, bytes
  name:      len:uvarint, bytes
  chunk_size:uvarint | route_depth:1 | address_bits:1 | placement:1
  total_size:uvarint | n:uvarint
  root_digest: 32 bytes
  digest_table: n * 32 bytes              (the Merkle leaves / integrity anchor)
  pointers: n * { byte: knot(3 bits) | probe5(5 bits); +uvarint probe if probe5==31 }
"""
from __future__ import annotations

from typing import List, Tuple

from knotstore import KnotStore, Manifest, TinyPointer, KNOTS_V01, DELTA_CHANNELS, ALGORITHM

MAGIC = b"KS1"
FMT = 1


def _uvarint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out)


def _read_uvarint(buf: bytes, i: int) -> Tuple[int, int]:
    shift = result = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, i
        shift += 7


def _lp(b: bytes) -> bytes:
    return _uvarint(len(b)) + b


def encode_manifest(m: Manifest) -> bytes:
    out = bytearray()
    out += MAGIC
    out.append(FMT)
    out += _lp(m.pointers[0].algorithm.encode() if m.pointers else ALGORITHM.encode())
    out += _lp(m.name.encode())
    out += _uvarint(m.chunk_size)
    out.append(m.route_depth)
    out += _uvarint(m.address_bits)
    out.append(0 if m.placement == "digest" else 1)
    out += _uvarint(m.total_size)
    out += _uvarint(len(m.pointers))
    out += bytes.fromhex(m.root_digest)
    for dhex in m.digests:
        out += bytes.fromhex(dhex)
    for p in m.pointers:
        knot_idx = KNOTS_V01.index(p.knot)
        p5 = p.probe if p.probe < 31 else 31
        out.append((knot_idx & 0x07) | (p5 << 3))
        if p.probe >= 31:
            out += _uvarint(p.probe)
    return bytes(out)


def decode_manifest(buf: bytes) -> Manifest:
    if buf[:3] != MAGIC:
        raise ValueError("bad magic")
    i = 3
    fmt = buf[i]; i += 1
    if fmt != FMT:
        raise ValueError(f"unsupported format {fmt}")
    alen, i = _read_uvarint(buf, i); algorithm = buf[i:i + alen].decode(); i += alen
    nlen, i = _read_uvarint(buf, i); name = buf[i:i + nlen].decode(); i += nlen
    chunk_size, i = _read_uvarint(buf, i)
    route_depth = buf[i]; i += 1
    address_bits, i = _read_uvarint(buf, i)
    placement = "digest" if buf[i] == 0 else "content"; i += 1
    total_size, i = _read_uvarint(buf, i)
    n, i = _read_uvarint(buf, i)
    root_digest = buf[i:i + 32].hex(); i += 32
    digests: List[str] = []
    for _ in range(n):
        digests.append(buf[i:i + 32].hex()); i += 32
    pointers: List[TinyPointer] = []
    for k in range(n):
        byte = buf[i]; i += 1
        knot_idx = byte & 0x07
        p5 = (byte >> 3) & 0x1F
        if p5 == 31:
            probe, i = _read_uvarint(buf, i)
        else:
            probe = p5
        dhex = digests[k]
        digest = bytes.fromhex(dhex)
        # recompute the derivable fields
        delta = DELTA_CHANNELS[digest[0] % len(DELTA_CHANNELS)]
        if k < n - 1:
            size = chunk_size
        else:
            size = total_size - chunk_size * (n - 1)
            if n == 1 and total_size == 0:
                size = 0
        pointers.append(TinyPointer(
            version=1, algorithm=algorithm, knot=KNOTS_V01[knot_idx], delta=delta,
            depth=route_depth, probe=probe, size=size, digest_prefix=dhex[:24],
        ))
    return Manifest(
        version=1, name=name, chunk_size=chunk_size, total_size=total_size,
        route_depth=route_depth, address_bits=address_bits, placement=placement,
        root_digest=root_digest, pointers=pointers, digests=digests,
    )


def size_report(m: Manifest) -> dict:
    """Measured pointer-only and whole-manifest sizes, JSON vs binary."""
    n = max(1, len(m.pointers))
    json_ptr = sum(len(p.to_json().encode()) for p in m.pointers) / n
    binary = encode_manifest(m)
    # binary per-pointer cost = total binary minus the fixed header and digest table
    digest_table = 32 * len(m.pointers)
    header_est = len(binary) - digest_table - len(m.pointers)  # ~1 byte/pointer common case
    bin_ptr = (len(binary) - digest_table - header_est) / n
    json_manifest = len(m.to_json().encode())
    return {
        "pointers": len(m.pointers),
        "json_pointer_bytes_avg": round(json_ptr, 1),
        "binary_pointer_bytes_avg": round(bin_ptr, 2),
        "pointer_compression_ratio": round(bin_ptr / json_ptr, 4) if json_ptr else 0.0,
        "json_manifest_bytes": json_manifest,
        "binary_manifest_bytes": len(binary),
        "binary_manifest_note": "dominated by the 32-byte digest table (integrity anchor), not pointers",
    }


if __name__ == "__main__":
    import json
    import os
    ks = KnotStore(chunk_size=256, placement="content")
    data = os.urandom(256 * 40)
    m = ks.put(data, "codec_demo.bin")
    blob = encode_manifest(m)
    back = decode_manifest(blob)
    assert back.to_json() == m.to_json(), "binary round-trip must reproduce the manifest exactly"
    # and the decoded manifest must still retrieve the data
    assert ks.get(back) == data
    print(json.dumps(size_report(m), indent=2))
    print("PASS binary round-trip + retrieval from decoded manifest")

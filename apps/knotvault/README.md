# KnotVault

**KnotVault is zip plus a cryptographic integrity receipt.** Drag files or
folders in and they are content-addressed and deduplicated (exact-duplicate
chunks collapse automatically), and you get back a single Merkle root that
fingerprints the whole archive. Later you can *prove* nothing changed — or, if
something did, KnotVault points at exactly which file (and chunk) was tampered
with or corrupted.

## What makes it different

- **Content-addressed storage** — every chunk is stored under the hash of its
  bytes, so identical content is stored once no matter how many files share it.
- **Merkle tamper-evidence** — each file carries a Merkle root over its chunks,
  and each archive carries a Merkle root over its files. Flipping a single byte
  anywhere changes the root, and `verify` catches it.
- **Automatic dedup** — back up the same report three times and you pay for it
  once on disk; `add` shows you the savings.

## Install

```bash
# from the repo root
pipx install ./apps/knotvault
# or, without installing, run it in place:
PYTHONPATH=apps/knotvault python -m knotvault --help
```

KnotVault depends only on the Python standard library (3.8+) and the bundled
KNOTstore engine — no third-party packages.

## Quickstart

```bash
# Archive a folder (and/or files). Prints dedup savings + Merkle root.
knotvault add ./my-folder file1.txt --name backup

# Prove integrity later — re-hashes every chunk.
knotvault verify backup
#   OK  backup  root=<64-hex Merkle root>

# Restore it anywhere (verified on the way out, structure preserved).
knotvault extract backup ./restored

# See what's in the vault.
knotvault list

# Zero-config end-to-end proof (dedup + a deliberately corrupted object).
knotvault demo
```

The vault lives in `./.knotvault` by default; pass `--vault DIR` to use another
location.

## How it works

Each archived file is chunked and stored in a deduplicating, content-addressed
object store. A binary *manifest* records the chunk pointers and Merkle leaves
needed to rebuild that file. A small `index.json` maps each archive name to its
files (`relpath`, manifest, size, root digest). The archive's overall root is a
Merkle root over the per-file roots, so one 64-hex string vouches for the whole
set.

## Limitations (honest)

- **Metadata is not archived.** File contents and relative paths are preserved;
  permissions, ownership, timestamps, symlinks, and empty directories are not.
- **Not encryption.** KnotVault proves *integrity*, not *confidentiality* —
  object bytes are stored as-is. Anyone with the vault can read the data.
- **The vault must be trusted/whole.** Tamper-evidence assumes the manifest and
  index themselves are intact; if an attacker rewrites both a chunk and its
  manifest consistently, detection relies on you holding the expected root out
  of band. The index is not itself signed.
- **No incremental/append-to-archive.** Archive names are immutable once added;
  re-add under a new name to make a new version (dedup means shared bytes are
  still free).
- **Single-process, no locking.** Concurrent writers to one vault are not
  coordinated.

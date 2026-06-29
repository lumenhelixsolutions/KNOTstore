# CheckpointTime

**A reversible, deduplicated checkpoint store for long-running jobs** — model
training, multi-day agent runs, simulations.

Snapshots of slowly-changing state are **content-addressed and chunk-level
deduplicated**, so N near-identical checkpoints cost roughly *one full copy plus
the deltas*. You can **rewind** HEAD to any earlier checkpoint or **branch** a
new named timeline — without ever losing data.

## Why

Naively, saving a checkpoint every step of a long run costs `N × full_size` on
disk. But consecutive checkpoints of a training/agent run are *almost* identical.
CheckpointTime stores each chunk once: identical chunks across checkpoints
collapse to a single copy, so physical bytes on disk stay close to one full copy
plus the small parts that actually changed.

## Install

No third-party dependencies (stdlib only, Python 3.8+). It ships inside the
KNOTstore repo and bootstraps the `knotcore` engine via `sys.path`, so it works
straight from a checkout:

```bash
cd apps/checkpointtime
pip install -e .          # installs the `checkpointtime` console script
```

Or run without installing:

```bash
python -m checkpointtime.cli demo
```

## Quickstart

```bash
checkpointtime demo                              # the proof (zero config)
checkpointtime snapshot ./run/state.bin --label step-42
checkpointtime timeline
checkpointtime stats
checkpointtime restore <id> ./restored_state.bin
```

Library:

```python
from checkpointtime import CheckpointStore

store = CheckpointStore("./.checkpointtime")
cid = store.snapshot(state_bytes, label="step-42")
data = store.restore(cid)            # exact round-trip
store.rewind(cid)                    # move HEAD back (reversible)
store.branch(cid, "experiment")      # fork a new timeline
print(store.stats())                 # logical vs physical bytes, dedup ratio
```

## The demo's dedup-savings table

`checkpointtime demo` takes 20 checkpoints of a ~72 KB blob that mutates only
slightly each step, then prints:

```
         LOGICAL        PHYSICAL ON DISK
totals   1.41 MB        239.30 KB

dedup ratio (logical / physical) : 6.02x
space saved by dedup             : 83.4%
```

- **logical bytes** = sum of all checkpoint sizes (what 20 naive copies cost).
- **physical bytes on disk** = what CheckpointTime actually stored.
- **dedup ratio** = logical / physical — here ~6x fewer bytes on disk.

The demo then rewinds HEAD to checkpoint `step-05`, restores it, verifies the
bytes match the original **exactly**, branches a new `experiment` timeline, and
confirms the reversible provenance chain verifies. Clear PASS/FAIL at the end.

## When to use it

- **Model training** — checkpoint every epoch/step cheaply; rewind to before
  divergence; branch to try a different schedule from a known-good point.
- **Long agent runs** — snapshot agent state across a multi-day run; rewind to
  retry from a checkpoint; branch alternate strategies.
- **Simulations** — keep many timesteps without paying for many full copies.

## How it works

- The underlying `PersistentKnotStore` (from `knotcore`) splits each blob into
  fixed-size chunks, content-addresses them, and stores each unique chunk once.
- A `ProvenanceLog` records the ordered, reversible timeline; its chain can be
  verified and rolled back, which is what makes rewind trustworthy.
- Checkpoint metadata (id, label, time, size, fingerprint, branch, parent) and
  HEAD/branch state are persisted to `meta.json` and reloaded faithfully.

## Limitations (honest)

- **Chunk-level dedup, not semantic diff.** Savings come from byte-identical
  chunks. State whose serialization shifts byte offsets on every step (so chunk
  boundaries never realign) will dedup poorly. Best results when changes are
  localized within a stable layout. Tune `chunk_size` smaller to catch smaller
  deltas (at some bookkeeping cost).
- **Single-machine, local store.** It's a local on-disk store — no built-in
  replication, remote backend, or concurrent multi-writer locking.
- **Branches are lightweight tips,** not a full DAG merge system. You can fork
  named timelines from any checkpoint, but there's no merge operation.
- **No encryption/compression layer** beyond what the engine provides; pair with
  your own at-rest encryption if needed.
```

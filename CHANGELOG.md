# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/); this project
uses [Semantic Versioning](https://semver.org/).

## [0.2.0] — 2026-06-30

### Added
- **Four downloadable applications** built on the engine, each a self-contained,
  stdlib-only package with a zero-config `demo`, CLI, tests, and `pyproject.toml`:
  - **KnotVault** — tamper-evident, deduplicating archiver (Merkle integrity receipts).
  - **PrefixForge** — content-addressed LLM prefix cache with near-duplicate locality;
    syntactic + zero-dependency semantic mode and an `embedding_fn` hook for real models.
  - **DriftLedger** — time-travel, tamper-evident agent memory (reversible rollback, HMAC-signable audit).
  - **CheckpointTime** — reversible, deduplicated checkpoints for long runs.
- **`knot` meta-CLI** — one command dispatching to all four apps (`knot vault|forge|ledger|checkpoint`,
  `knot demo --all`, `knot list`).
- **`knotcore`** — unified engine entry point plus `PersistentKnotStore` (disk-backed, write-through;
  objects + compact binary manifests survive process restarts).
- **Benchmark suite** (`bench/`) — reproducible headline metrics → `results.json` + `RESULTS.md`.
- **`install.sh` / `Makefile`** — one-shot install of the suite as console commands; common dev tasks.
- CI now runs engine + core + apps + bench suites and a packaging smoke test across Python 3.8/3.10/3.12.

## [0.1.5] — 2026-06-29

### Added
- Reduced Burau representation and Alexander polynomial computation; KnotInfo-verified knot table.
- MIT `LICENSE`; GitHub Actions CI; tamper-evident, content-addressed reference engine
  (1-byte tiny pointers, SimHash content placement, reversible MacroCube provenance).

[0.2.0]: https://github.com/lumenhelixsolutions/KNOTstore/releases/tag/v0.2.0
[0.1.5]: https://github.com/lumenhelixsolutions/KNOTstore/releases/tag/v0.1.5

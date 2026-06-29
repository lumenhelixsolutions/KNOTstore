# Applications — built on the KNOTstore engine

Four downloadable, plug-n-play tools that turn the engine's primitives
(content-addressing, near-duplicate locality, Merkle tamper-evidence, and
reversible/rollback provenance) into "it just works" products. Each is a
self-contained Python package with a zero-config `demo`, a CLI, tests, and a
`pyproject.toml` (so `pip install -e .` gives you a console command).

All four import the shared engine entry point [`knotcore`](../knotcore.py) —
stdlib-only, Python 3.8+.

| App | One-liner | Primitive it leans on | Proven by `demo` |
|---|---|---|---|
| [**KnotVault**](knotvault/) | Tamper-evident deduplicating archiver — "zip + integrity receipt" | Content-addressing + Merkle | ~57% dedup, corruption caught |
| [**PrefixForge**](prefixforge/) | LLM prompt/prefix cache that also hits on *near*-duplicates | SimHash locality | +22.5 pts hit-rate over exact-only |
| [**DriftLedger**](driftledger/) | Time-travel + tamper-evident memory for AI agents | Reversible provenance + HMAC | rollback exact, tamper caught |
| [**CheckpointTime**](checkpointtime/) | Reversible, deduplicated checkpoints for long runs | Dedup + reversible timeline | ~6× space saving, exact rewind |

## Quickstart (any app)

```bash
# From the repo root — run a product's zero-config proof:
PYTHONPATH=apps/knotvault       python -m knotvault       demo
PYTHONPATH=apps/prefixforge     python -m prefixforge     demo
PYTHONPATH=apps/driftledger     python -m driftledger     demo
PYTHONPATH=apps/checkpointtime  python -m checkpointtime  demo

# Or install one as a real command:
pip install -e apps/knotvault   # then: knotvault --help
```

## Run all the tests

```bash
python -m pytest apps knotstore/test_knotstore.py -q
```

Each app's own `README.md` has its full pitch, CLI reference, and an honest
limitations section.

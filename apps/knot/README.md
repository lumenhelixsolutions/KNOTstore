# knot — one CLI for the whole KNOTstore suite

`knot` is a thin dispatcher over the four KNOTstore apps, so you install once and
drive everything from a single command.

| Command | App | What it does |
|---|---|---|
| `knot vault …` | KnotVault | tamper-evident, deduplicating archiver |
| `knot forge …` | PrefixForge | LLM prefix cache with near-duplicate locality |
| `knot ledger …` | DriftLedger | time-travel, tamper-evident agent memory |
| `knot checkpoint …` | CheckpointTime | reversible, deduplicated checkpoints |

```bash
pipx install ./apps/knot          # or run in-place: PYTHONPATH=apps/knot python -m knot
knot list                         # the apps + status
knot demo --all                   # run every app's zero-config demo
knot vault add ./folder --name backup
knot forge query "summarize this contract"
```

Dispatch is by subprocess (`python -m <app>`), so `knot` stays decoupled from each
app's internals and works from a cloned repo or an installed console script.
Everything after the app name is forwarded verbatim, so `knot vault --help` shows
KnotVault's own help. Stdlib only, Python 3.8+.

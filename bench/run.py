"""
bench.run — reproducible benchmark harness for the KNOTstore engine + apps.

Runs every benchmark in :mod:`bench.benchmarks`, writes a machine-readable
``results.json`` and a human-readable ``RESULTS.md`` table, and prints a summary.

    python -m bench.run             # full
    python -m bench.run --quick     # smaller sizes (CI-friendly, <~20s)
    python -m bench.run --out bench/results.json --md bench/RESULTS.md

Deterministic: every benchmark seeds its own RNG.  Stdlib only, Python 3.8+.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from typing import Dict, List

from . import benchmarks as B

# (key, human label, units-hint) in display order
BENCHMARKS = [
    ("engine_pointer_size", "Engine — tiny-pointer size", "bytes/pointer"),
    ("engine_locality", "Engine — SimHash locality", "co-shard prob"),
    ("knotvault_dedup", "KnotVault — dedup savings", "% saved"),
    ("prefixforge_hitlift", "PrefixForge — cache hit-rate lift", "hit-rate"),
    ("checkpointtime_dedup", "CheckpointTime — checkpoint dedup", "x ratio"),
    ("driftledger_rollback", "DriftLedger — rollback + tamper", "correctness"),
]

# the one headline number to surface per benchmark, for the summary column
HEADLINE = {
    "engine_pointer_size": ("binary_pointer_bytes_avg", "B/ptr"),
    "engine_locality": ("co_shard_prob_content", "content co-shard"),
    "knotvault_dedup": ("dedup_savings_pct", "% saved"),
    "prefixforge_hitlift": ("prefixforge_hit_rate", "hit-rate"),
    "checkpointtime_dedup": ("dedup_ratio", "x"),
    "driftledger_rollback": ("rollback_correct", "rollback ok"),
}


def run_all(quick: bool = False) -> Dict[str, object]:
    results: Dict[str, object] = {}
    for key, _label, _units in BENCHMARKS:
        fn = getattr(B, key)
        t0 = time.perf_counter()
        try:
            metrics = fn(quick=quick)
            metrics["_ok"] = True
        except Exception as exc:  # a broken bench must not sink the whole run
            metrics = {"_ok": False, "_error": "{}: {}".format(type(exc).__name__, exc)}
        metrics["_seconds"] = round(time.perf_counter() - t0, 3)
        results[key] = metrics
    return {
        "schema": 1,
        "quick": quick,
        "generated_unix": int(time.time()),
        "benchmarks": results,
    }


def _fmt_headline(key: str, metrics: Dict[str, object]) -> str:
    field, _unit = HEADLINE.get(key, (None, ""))
    if not metrics.get("_ok"):
        return "ERROR"
    val = metrics.get(field)
    if isinstance(val, bool):
        return "yes" if val else "NO"
    if isinstance(val, float):
        return "{:.3f}".format(val)
    return str(val)


def to_markdown(payload: Dict[str, object]) -> str:
    lines: List[str] = []
    lines.append("# KNOTstore benchmark results")
    lines.append("")
    mode = "quick" if payload.get("quick") else "full"
    lines.append("_Reproduce: `python -m bench.run{}`_  ".format(" --quick" if payload.get("quick") else ""))
    lines.append("_Mode: {}_".format(mode))
    lines.append("")
    lines.append("| Benchmark | Headline | Units | Time (s) | OK |")
    lines.append("|---|---|---|---|---|")
    bm = payload["benchmarks"]  # type: ignore[index]
    for key, label, units in BENCHMARKS:
        m = bm.get(key, {})
        ok = "✅" if m.get("_ok") else "❌"
        lines.append("| {} | **{}** | {} | {} | {} |".format(
            label, _fmt_headline(key, m), units, m.get("_seconds", "?"), ok))
    lines.append("")
    lines.append("<details><summary>Full metrics (JSON)</summary>")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(bm, indent=2, sort_keys=True))
    lines.append("```")
    lines.append("</details>")
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(prog="bench.run", description="Run the KNOTstore benchmark suite.")
    ap.add_argument("--quick", action="store_true", help="smaller sizes for a fast CI-friendly run")
    ap.add_argument("--out", default=os.path.join(here, "results.json"), help="JSON output path")
    ap.add_argument("--md", default=os.path.join(here, "RESULTS.md"), help="markdown output path")
    args = ap.parse_args(argv)

    payload = run_all(quick=args.quick)

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    md = to_markdown(payload)
    with open(args.md, "w", encoding="utf-8") as fh:
        fh.write(md)

    # console summary
    print("KNOTstore benchmarks ({} mode)".format("quick" if args.quick else "full"))
    print("-" * 56)
    n_ok = 0
    for key, label, units in BENCHMARKS:
        m = payload["benchmarks"][key]  # type: ignore[index]
        n_ok += 1 if m.get("_ok") else 0
        print("  {:<34} {:>12}  {}".format(label, _fmt_headline(key, m), units))
    print("-" * 56)
    print("  {}/{} benchmarks OK   →  {}  |  {}".format(
        n_ok, len(BENCHMARKS), os.path.relpath(args.out), os.path.relpath(args.md)))
    return 0 if n_ok == len(BENCHMARKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())

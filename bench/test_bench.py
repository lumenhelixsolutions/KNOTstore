"""Smoke + sanity tests for the benchmark suite (runs in --quick mode)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bench.run import run_all, to_markdown, BENCHMARKS  # noqa: E402


def test_all_benchmarks_run_quick():
    payload = run_all(quick=True)
    bm = payload["benchmarks"]
    # every declared benchmark produced a result and did not error
    for key, _label, _units in BENCHMARKS:
        assert key in bm, "missing benchmark {}".format(key)
        assert bm[key].get("_ok") is True, "benchmark {} errored: {}".format(
            key, bm[key].get("_error"))


def test_sanity_invariants():
    bm = run_all(quick=True)["benchmarks"]

    # tiny pointer really is small and round-trips
    eng = bm["engine_pointer_size"]
    assert eng["binary_pointer_bytes_avg"] <= eng["json_pointer_bytes_avg"]
    assert eng["roundtrip_ok"] is True

    # content placement co-locates near-dups better than random
    loc = bm["engine_locality"]
    assert loc["co_shard_prob_content"] >= loc["random_expectation"]

    # dedup actually saves space
    assert bm["knotvault_dedup"]["dedup_savings_pct"] > 0
    assert bm["checkpointtime_dedup"]["dedup_ratio"] >= 1.0

    # near-aware cache never hits less than exact-only
    pf = bm["prefixforge_hitlift"]
    assert pf["prefixforge_hit_rate"] >= pf["exact_only_hit_rate"]

    # reversible ledger rolls back and catches tampering
    dl = bm["driftledger_rollback"]
    assert dl["rollback_correct"] is True
    assert dl["tamper_caught"] is True


def test_markdown_renders():
    md = to_markdown(run_all(quick=True))
    assert "KNOTstore benchmark results" in md
    assert "| Benchmark |" in md

"""Deterministic demo: exact-cache vs PrefixForge (exact+near) hit-rate.

We simulate a realistic prompt stream where the *same* small set of base prompts
recurs with surface variations (whitespace, punctuation, trailing suffixes,
small edits) — exactly the traffic an exact cache fails to dedup. We replay the
stream through two caches and compare hit-rate, tokens saved and cost reduction.
"""
from __future__ import annotations

import random
from typing import Dict, List, Tuple

from .cache import PrefixCache, normalize

BASE_PROMPTS = [
    "Summarize the following quarterly earnings report for shareholders",
    "Translate the user's message from English into French",
    "Write a polite reply declining the meeting invitation",
    "Explain the difference between TCP and UDP to a junior engineer",
    "Generate a SQL query that returns the top 10 customers by revenue",
    "Classify the sentiment of this product review as positive or negative",
]

_SUFFIXES = [
    "", ".", " .", "  ", " please", " - thanks", "!", " Please be concise.",
    "  please respond quickly", " (urgent)",
]


def _perturb(base, rng):
    # type: (str, random.Random) -> str
    """Produce a near-duplicate of ``base`` via realistic surface edits."""
    s = base
    # Whitespace jitter.
    if rng.random() < 0.5:
        s = s.replace(" ", "  ", rng.randint(1, 3))
    # Punctuation / casing jitter.
    if rng.random() < 0.5:
        s = s.upper() if rng.random() < 0.5 else s.capitalize()
    # Trailing suffix.
    s = s + rng.choice(_SUFFIXES)
    # Occasional minor word edit (drop a single short word).
    if rng.random() < 0.3:
        words = s.split()
        if len(words) > 6:
            i = rng.randrange(len(words))
            if len(words[i]) <= 3:
                del words[i]
                s = " ".join(words)
    return s


def build_stream(n=200, seed=42):
    # type: (int, int) -> List[Tuple[str, int]]
    """Return a list of (prompt, tokens) — a mix of fresh + near-duplicate traffic."""
    rng = random.Random(seed)
    stream = []  # type: List[Tuple[str, int]]
    for _ in range(n):
        base = rng.choice(BASE_PROMPTS)
        tokens = 400 + rng.randrange(0, 400)  # prompt+completion tokens for this call
        if rng.random() < 0.8:
            # 80% of traffic is a near-duplicate of a base prompt.
            stream.append((_perturb(base, rng), tokens))
        else:
            stream.append((base, tokens))
    return stream


def run(n=200, seed=42, threshold=8):
    # type: (int, int, int) -> Dict[str, object]
    """Replay the stream through exact-only and PrefixForge caches.

    Returns a metrics dict (also usable from tests).
    """
    stream = build_stream(n=n, seed=seed)

    exact = PrefixCache(persist=False, threshold=threshold)
    forge = PrefixCache(persist=False, threshold=threshold)

    exact_hits = 0
    forge_exact_hits = 0
    forge_near_hits = 0
    exact_tokens_saved = 0
    forge_tokens_saved = 0
    total_tokens = 0

    for prompt, tokens in stream:
        total_tokens += tokens

        # Exact-only cache: hit only on a byte-identical normalized prompt.
        # We emulate that by checking exact membership (PrefixForge's exact tier).
        if prompt in exact:
            exact_hits += 1
            exact_tokens_saved += tokens
        else:
            exact.put(prompt, b"x", tokens=tokens)

        # PrefixForge: exact OR near.
        r = forge.get(prompt)
        if r.kind == "exact":
            forge_exact_hits += 1
            forge_tokens_saved += r.tokens_saved
        elif r.kind == "near":
            forge_near_hits += 1
            forge_tokens_saved += r.tokens_saved
        else:
            forge.put(prompt, b"x", tokens=tokens)

    forge_hits = forge_exact_hits + forge_near_hits
    return {
        "n": n,
        "threshold": threshold,
        "total_tokens": total_tokens,
        "exact_hits": exact_hits,
        "exact_hit_rate": exact_hits / n,
        "exact_tokens_saved": exact_tokens_saved,
        "forge_exact_hits": forge_exact_hits,
        "forge_near_hits": forge_near_hits,
        "forge_hits": forge_hits,
        "forge_hit_rate": forge_hits / n,
        "forge_tokens_saved": forge_tokens_saved,
        "exact_cost_reduction": exact_tokens_saved / total_tokens,
        "forge_cost_reduction": forge_tokens_saved / total_tokens,
    }


def format_report(m):
    # type: (Dict[str, object]) -> str
    """Render the metrics dict as a clean, explained table."""
    lines = []
    lines.append("PrefixForge demo — exact cache vs exact+near (PrefixForge)")
    lines.append("=" * 62)
    lines.append("Stream: %d prompts, ~80%% near-duplicates of %d base prompts"
                 % (m["n"], len(BASE_PROMPTS)))
    lines.append("Near threshold: Hamming <= %d on 64-bit SimHash" % m["threshold"])
    lines.append("")
    header = "%-22s %12s %12s" % ("metric", "exact-only", "PrefixForge")
    lines.append(header)
    lines.append("-" * len(header))
    lines.append("%-22s %12d %12d" % ("cache hits", m["exact_hits"], m["forge_hits"]))
    lines.append("%-22s %11.1f%% %11.1f%%"
                 % ("hit rate", m["exact_hit_rate"] * 100, m["forge_hit_rate"] * 100))
    lines.append("%-22s %12d %12d"
                 % ("tokens saved", m["exact_tokens_saved"], m["forge_tokens_saved"]))
    lines.append("%-22s %11.1f%% %11.1f%%"
                 % ("cost reduction",
                    m["exact_cost_reduction"] * 100, m["forge_cost_reduction"] * 100))
    lines.append("-" * len(header))
    lines.append("  (of PrefixForge hits: %d exact + %d near)"
                 % (m["forge_exact_hits"], m["forge_near_hits"]))
    lines.append("")
    lift = (m["forge_hit_rate"] - m["exact_hit_rate"]) * 100
    extra = m["forge_tokens_saved"] - m["exact_tokens_saved"]
    lines.append("LIFT: +%.1f pts hit-rate, +%d tokens saved over exact-only."
                 % (lift, extra))
    lines.append("")
    lines.append("Why: 80% of traffic is a surface variant (whitespace, punctuation,")
    lines.append("trailing suffixes, minor edits) of a base prompt. An exact cache only")
    lines.append("fires on byte-identical repeats, so it misses all those variants. The")
    lines.append("near tier recognizes them via SimHash locality and reuses the cached")
    lines.append("result, converting near-misses into hits and into real token savings.")
    return "\n".join(lines)

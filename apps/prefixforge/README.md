# PrefixForge

**A content-addressed LLM prompt cache that also hits on near-duplicates.**

Exact-match prompt caches (vLLM prefix caching, provider prompt caching) only
fire when a new prompt is *byte-identical* to a cached one. But real traffic is
full of near-misses: the same request with different whitespace, punctuation, a
trailing "please", or a one-word edit. Exact caches drop every one of those —
and that's exactly where token-cost savings hide.

PrefixForge keeps the exact tier **and** adds a near tier: on an exact miss it
returns the closest cached prompt within a SimHash Hamming-distance threshold,
turning near-misses into cache hits.

## Install

Zero runtime dependencies (stdlib only, Python 3.8+). From the repo root:

```bash
pip install -e apps/prefixforge
```

Or run straight from source without installing:

```bash
PYTHONPATH=apps/prefixforge python -m prefixforge.cli demo
```

`knotcore` does not need to be pip-installed — PrefixForge bootstraps it onto
`sys.path` automatically.

## Quickstart

```python
from prefixforge import PrefixCache

cache = PrefixCache(root="./.prefixforge")          # persisted to disk
cache.put("Summarize this earnings report", b"...completion blob...", tokens=500)

r = cache.get("SUMMARIZE this earnings report  please!")
print(r.kind, r.similarity, r.tokens_saved)         # near 0.95 500
```

`Result` fields: `.kind` in `{"exact","near","miss"}`, `.value` (bytes or
`None`), `.similarity` (1.0 exact; `1 - hamming/64` near; 0.0 miss),
`.tokens_saved`, plus `.prompt` and `.distance` for the matched entry.

## The demo (the money shot)

```bash
prefixforge demo          # or: prefixforge   (bare command runs the demo)
```

```
PrefixForge demo — exact cache vs exact+near (PrefixForge)
==============================================================
Stream: 200 prompts, ~80% near-duplicates of 6 base prompts
Near threshold: Hamming <= 8 on 64-bit SimHash

metric                   exact-only  PrefixForge
------------------------------------------------
cache hits                      132          177
hit rate                      66.0%        88.5%
tokens saved                  80685       113123
cost reduction                66.0%        92.6%
------------------------------------------------
  (of PrefixForge hits: 59 exact + 118 near)

LIFT: +22.5 pts hit-rate, +32438 tokens saved over exact-only.
```

The stream is seeded and deterministic. ~80% of prompts are surface variants of
6 base prompts. The exact cache only re-fires on byte-identical repeats (66%);
PrefixForge recognizes the variants via SimHash locality and lifts the hit rate
to 88.5% — a **+22.5 point** lift and **~32k extra tokens saved** in a 200-call
stream. Cost reduction here is `tokens_saved / total_tokens`: every cached hit
is a call you don't pay the model for.

## CLI

```bash
# store a cached completion for a prompt (value comes from a file)
prefixforge put "Explain TCP vs UDP" --value-file ./answer.bin --tokens 300

# look up a prompt; prints kind / similarity / tokens_saved / distance
prefixforge query "explain TCP vs udp!"
```

Both use an on-disk cache at `./.prefixforge` by default (`--root` to change).
`prefixforge --help` and `prefixforge <cmd> --help` document every flag.

## How it works

1. **Normalize** — lowercase, collapse whitespace. Trivial variants collide into
   one key before any hashing.
2. **Exact index** — content digest of the normalized prompt (via
   `knotcore.KnotStore.digest`). Identical normalized prompts hit here at
   similarity 1.0.
3. **Near index** — a 64-bit SimHash signature of the normalized prompt. On an
   exact miss, PrefixForge scans for the smallest Hamming distance; if it is
   `<= threshold` it's a near hit.
4. **Persistence** — values are stored content-addressed in
   `knotcore.PersistentKnotStore` (identical completions dedup); the signature
   index is mirrored to `index.json`. The cache survives restarts.

### Why threshold = 8?

On a 64-bit SimHash, unrelated text sits ~32 bits apart (half the bits). Genuine
edit/whitespace/punctuation variants land in the ~0–8 range, while unrelated
prompts stay above ~12. Eight is a conservative middle ground — tight enough to
reject unrelated prompts, loose enough to catch realistic near-duplicates. Tune
it with the `threshold` constructor argument or `--threshold`.

## Semantic mode (plug in an embedding model)

The default hasher is **byte-SimHash** over the text — zero deps, *syntactic*
locality. For *semantic* locality, pass an `embedding_fn`:

```python
from prefixforge import PrefixCache

def embed(text):
    return my_model.encode(text)   # returns Sequence[float]

cache = PrefixCache(root="./.prefixforge", embedding_fn=embed)
```

The embedding is projected onto 64 fixed random hyperplanes; the sign of each
projection is one SimHash bit. Semantically close prompts then land at small
Hamming distance even when their surface text differs. The hyperplanes are
generated deterministically (seeded), so signatures are stable across processes.

## Honest limitations

- **Byte-SimHash is syntactic, not semantic.** It catches surface variants
  (whitespace, punctuation, suffixes, small edits). Two prompts that *mean* the
  same thing but share few characters won't match in the default mode — use
  `embedding_fn` for that, and bring your own model.
- **It's a cache, not an LLM.** PrefixForge returns *a previously stored value*
  for a similar prompt. Whether reusing a near-duplicate's completion is correct
  for your use case is a product decision — set the threshold accordingly. For
  high-stakes prompts, keep the threshold tight or exact-only.
- **Linear near-search.** The near tier scans the signature index; fine for
  caches up to tens of thousands of entries. Larger deployments would want an
  ANN / banded-LSH index (not included).
- **Demo numbers are illustrative.** They come from a synthetic, near-duplicate-
  heavy stream to show the mechanism. Your real lift depends on how repetitive
  your traffic is.
```

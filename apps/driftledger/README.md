# DriftLedger

**Tamper-evident, time-travel memory for AI agents.**

Every memory write an agent makes becomes a *reversible, content-addressed step*.
With DriftLedger you can roll an agent's entire memory back to step N, replay it
forward, branch an alternate timeline, **detect tampering**, and emit a
**signed audit trail** — the kind of provenance SOC 2 and the EU AI Act expect
from autonomous systems.

```
boot ─ observe ─ plan ─ tool ─ decide ─ observe ─ tool ─ act
                          ▲
                          └── checkout(3) / rollback() / branch(3)
```

---

## Why this is different from a hash chain

A conventional audit log is a one-way hash chain: `H_{t+1} = hash(H_t, event)`.
It can prove *that* something changed but it **cannot undo** anything — there is
no inverse of a hash. DriftLedger builds on KNOTstore's `ProvenanceLog`, a
reversible state machine over a `MacroCube`: each event advances the cube along a
path that depends on the event *and* the current state, and **every move has an
inverse route**. That buys three things a hash chain cannot give you:

- **Rollback** — apply the inverse route to recover the *exact* prior state, and
  it *raises* if the prior fingerprint can't be reproduced (tamper signal).
- **Replay-to-origin** — the whole lineage rewinds to the identity cube, so a
  claimed history verifies end-to-end in either direction.
- **Order sensitivity** — cube moves don't commute, so reordering events changes
  the final fingerprint. Silent reordering is detectable.

On top of the reversible chain DriftLedger adds the cryptographic layer:

- Each event string is **bound to the SHA-256 of the resulting state**
  (`event@<digest>`), so the provenance fingerprint commits to the real bytes.
- States are stored **content-addressed** (dedup, survives restarts) and
  `verify()` re-hashes every blob — a single flipped byte on disk is caught.
- `audit()` emits a **Merkle root** over the state digests and an optional
  **HMAC-SHA256 signature** over the canonical audit body.

Honest framing: the cube provides *reversibility and order-sensitivity*; the
*cryptographic* tamper-resistance comes from SHA-256 + HMAC. The two are
complementary.

---

## Install

Stdlib-only runtime, Python 3.8+. No third-party dependencies.

```bash
cd apps/driftledger
pip install -e .        # exposes the `driftledger` console command
```

You can also run it without installing (from this directory):

```bash
python -m driftledger.cli demo
```

> DriftLedger bootstraps `sys.path` to find the bundled `knotcore` engine; you do
> **not** need `knotcore` pip-installed.

---

## Quickstart (library)

```python
from driftledger import AgentLedger

led = AgentLedger("./.driftledger", secret_key=b"soc2-key")

led.append("observe", b"user asks to book a flight")     # -> step 0
led.append("plan",    b"search flights LON->NYC")        # -> step 1
led.append("act",     b"seat 14A reserved")              # -> step 2

led.checkout(1)            # b"search flights LON->NYC"  (exact state at step 1)
led.rollback()             # undo step 2, return (event, restored_prior_state)
alt = led.branch(0)        # fork an independent timeline from step 0
led.verify()               # True on a clean ledger, False if tampered
led.audit()                # signed, Merkle-rooted summary dict
```

Everything persists under the ledger directory and reloads faithfully.

---

## Quickstart (CLI)

```bash
driftledger demo                         # the full proof (zero config)
driftledger log      ./.driftledger      # timeline + fingerprints
driftledger verify   ./.driftledger      # PASS / FAIL integrity check
driftledger rollback ./.driftledger      # undo the last step
driftledger audit    ./.driftledger --key mysecret   # signed JSON audit
```

---

## The `demo`, explained

`driftledger demo` runs end-to-end with no arguments and prints a clear
PASS/FAIL. It:

1. **Builds** ~8 steps of evolving agent memory and prints the timeline with
   per-step fingerprints.
2. **Rolls back 3 steps** using inverse routes and shows the *exact* prior state
   is recovered (byte-for-byte).
3. **Branches** an alternate timeline from the rewound head and shows it is
   independent (divergent fingerprint, extra step) from the original.
4. **Verifies** the clean ledger — PASS.
5. **Tampers** a stored state blob on disk (appends bytes to a content object),
   reopens the ledger, and shows `verify()` now **FAILs — tamper caught**.
6. Prints the **signed audit trail** (Merkle root + HMAC signature).

---

## How it's structured

| Layer | Responsibility |
|-------|----------------|
| `knotcore.PersistentKnotStore` | content-addressed, deduplicated state blobs on disk |
| `knotcore.ProvenanceLog` (`MacroCube`) | reversible, order-sensitive provenance chain |
| `driftledger.ledger.AgentLedger` | binds event↔state digest, persistence, verify, audit |
| `driftledger.cli` | zero-config CLI + the proof demo |

---

## Limitations (honest)

- **Not a substitute for a real secrets/HSM setup.** The HMAC key is whatever you
  pass in; key management is your responsibility. Without a key the audit is
  Merkle-rooted but unsigned.
- **Append-and-detect, not prevent.** DriftLedger makes tampering *detectable*
  (via re-hash + fingerprint + signature). It does not stop an attacker with
  write access from deleting the whole ledger directory; pair it with immutable
  or append-only storage and off-box signature storage for real assurance.
- **The cube is not a cryptographic primitive.** Its value is invertibility and
  order-sensitivity. All cryptographic strength rests on SHA-256 and HMAC.
- **State is stored whole per step.** Identical states dedup via content
  addressing, but large, mostly-distinct states cost roughly their full size per
  step. There is no diff/delta encoding yet.
- **Branches are materialized by replay.** `branch(n)` re-appends the first `n+1`
  states into a fresh ledger rather than sharing storage; convenient and
  independent, but not space-optimal.
- **Single-process, no concurrency control.** Concurrent writers to the same
  ledger directory are not coordinated.
```
```

---

MIT licensed. Part of the KNOTstore app suite.

## Audit & attestation

Export a portable, tamper-evident audit file and hand it to a third party who
can verify it **offline** — without your ledger's private store:

```bash
echo -n "shared-secret" > key.txt
driftledger audit export ./.driftledger --out audit.json --key-file key.txt
driftledger audit verify audit.json --key-file key.txt      # OK / FAIL (+ findings), exit 0/1
```

The file carries the ordered chain `(step, event, state_digest, fingerprint_after)`,
a Merkle root over the state digests, and an HMAC-SHA256 signature. `verify_audit`
recomputes the Merkle root, checks the chain links, and validates the signature.
Altering any field flips it to FAIL with a precise finding.

**Honest limits:** HMAC is a *shared-secret* (symmetric) signature — anyone with the
key can both sign and verify. Asymmetric (public-key) attestation would need a crypto
dependency, which is out of scope for this stdlib-only build.

"""AgentLedger — reversible, content-addressed, tamper-evident agent memory.

Design (clean separation of concerns):

  * STATE STORE      — ``knotcore.PersistentKnotStore`` holds each resulting
                       memory/state blob content-addressed (dedup + survives
                       restarts).
  * PROVENANCE       — ``knotcore.ProvenanceLog`` is a *reversible* state machine
                       over a lineage of event strings. Its inverse routes let us
                       recover the EXACT prior state (rollback), not just a hash.
  * LEDGER (here)    — binds the two: the event string fed to the provenance log
                       embeds the state's digest, so the provenance fingerprint
                       commits to the actual state. Tampering a stored state file
                       is therefore detectable two independent ways.

Why bind event<->state digest?
    The ProvenanceLog only sees event *strings*. If we logged a bare event like
    ``"step3"`` the chain would say nothing about what the agent actually
    remembered. By logging ``"step3|<sha256-of-state>"`` the chain's fingerprint
    cryptographically commits to the state bytes. Combined with verifying every
    stored blob against its recorded digest, a single corrupted byte on disk is
    caught.

Stdlib only. Python 3.8+ compatible.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
import knotcore  # noqa: E402


def _state_digest(state: bytes) -> str:
    """Hex sha256 of a state blob (the address we commit to)."""
    return hashlib.sha256(state).hexdigest()


def _bound_event(event: str, digest: str) -> str:
    """The string actually fed to the ProvenanceLog: event bound to state digest.

    Binding makes the reversible provenance fingerprint commit to the exact
    state bytes, so the chain detects state tampering, not just event reordering.
    """
    return event + "@" + digest


class AgentLedger:
    """A reversible, tamper-evident log of an agent's memory states.

    Parameters
    ----------
    root:
        Directory the ledger persists to. Created if missing.
    secret_key:
        Optional bytes/str HMAC key. When supplied, :meth:`audit` returns a
        cryptographic signature over the audit body so the trail is verifiably
        authentic and tamper-evident.
    route_depth:
        Forwarded to ``ProvenanceLog`` (depth of each reversible route).
    """

    META_NAME = "ledger.json"

    def __init__(self, root: str, secret_key: Optional[bytes] = None, route_depth: int = 8):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        if isinstance(secret_key, str):
            secret_key = secret_key.encode("utf-8")
        self.secret_key = secret_key
        self.route_depth = route_depth

        self.store = knotcore.PersistentKnotStore(self.root, placement="content")
        self.log = knotcore.ProvenanceLog(route_depth=route_depth)
        # Parallel to self.log.steps: per-step (raw_event, state_digest).
        self._events: List[str] = []
        self._digests: List[str] = []

        self._load()

    # ------------------------------------------------------------------ paths
    @property
    def _meta_path(self) -> str:
        return os.path.join(self.root, self.META_NAME)

    # ----------------------------------------------------------------- public
    def append(self, event: str, state: bytes) -> int:
        """Record *event* and store the resulting *state* blob.

        The provenance log advances by an event bound to ``sha256(state)`` so the
        fingerprint commits to the bytes. Returns the new step index.
        """
        if not isinstance(state, (bytes, bytearray)):
            raise TypeError("state must be bytes")
        state = bytes(state)
        digest = _state_digest(state)

        # Content-addressed store, keyed by the digest so identical states dedup.
        manifest = self.store.put(state, name=digest)
        self.store.save_manifest(manifest, name=digest)

        self.log.add(_bound_event(event, digest))
        self._events.append(event)
        self._digests.append(digest)

        idx = len(self._digests) - 1
        self._save()
        return idx

    def checkout(self, n: int) -> bytes:
        """Return the exact state bytes recorded at step *n*."""
        self._check_index(n)
        digest = self._digests[n]
        return self._load_state(digest)

    def rollback(self) -> Tuple[str, bytes]:
        """Undo the last step and return ``(restored_event, restored_state)``.

        Uses :meth:`ProvenanceLog.rollback`, which applies the inverse route and
        *raises* if the prior fingerprint cannot be reproduced (tamper). After
        rewinding we return the now-current state (the state of the prior step),
        or the empty bytes if the ledger is rewound to before any step.
        """
        if not self._digests:
            raise IndexError("nothing to roll back")

        self.log.rollback()  # raises ValueError on tamper
        undone_event = self._events.pop()
        self._digests.pop()
        self._save()

        if self._digests:
            restored_state = self._load_state(self._digests[-1])
        else:
            restored_state = b""
        return undone_event, restored_state

    def branch(self, n: int) -> "AgentLedger":
        """Fork a new, independent ledger containing steps ``0..n`` (inclusive).

        The branch lives in ``<root>-branch-<n>-<k>`` and replays the first
        ``n+1`` events into a fresh provenance chain + state store, giving a true
        alternate timeline you can extend without touching the original.
        """
        self._check_index(n)
        base = "%s-branch-%d" % (self.root, n)
        target = base
        k = 0
        while os.path.exists(target):
            k += 1
            target = "%s-%d" % (base, k)

        child = AgentLedger(target, secret_key=self.secret_key, route_depth=self.route_depth)
        for i in range(n + 1):
            child.append(self._events[i], self._load_state(self._digests[i]))
        return child

    def verify(self) -> bool:
        """Full integrity check.

        Returns True only if BOTH hold:
          1. ``ProvenanceLog.verify_chain()`` — the reversible chain replays from
             identity and every recorded fingerprint matches.
          2. Every stored state blob still hashes to its recorded digest AND the
             store's own manifest verification passes (catches on-disk tampering).
        """
        try:
            if not self.log.verify_chain():
                return False
        except Exception:
            return False

        for digest in self._digests:
            try:
                manifest = self.store.load_manifest(digest)
                if not self.store.verify(manifest):
                    return False
                blob = self.store.get(manifest)
            except Exception:
                return False
            if _state_digest(blob) != digest:
                return False
        return True

    def audit(self) -> Dict[str, object]:
        """Return a signed, tamper-evident audit summary.

        Includes the ordered ``(step, event, state_digest, fingerprint_after)``
        rows, a Merkle root over the state digests, the chain origin/head, and
        — when constructed with a secret key — an HMAC-SHA256 ``signature`` over
        a canonical serialization of the body.
        """
        rows = []
        for i, step in enumerate(self.log.steps):
            rows.append({
                "step": i,
                "event": self._events[i],
                "state_digest": self._digests[i],
                "fingerprint_after": step.fingerprint_after,
            })

        merkle_root = knotcore.KnotStore.merkle_root(list(self._digests))
        body = {
            "ledger": os.path.basename(self.root),
            "steps": rows,
            "count": len(rows),
            "origin": self.log.origin(),
            "head": self.log.fingerprint(),
            "merkle_root": merkle_root,
            "chain_verified": self.verify(),
        }

        canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signed = self.secret_key is not None
        if signed:
            signature = hmac.new(self.secret_key, canonical, hashlib.sha256).hexdigest()
        else:
            signature = None

        body["signed"] = signed
        body["signature"] = signature
        return body

    # ---------------------------------------------------------------- helpers
    def __len__(self) -> int:
        return len(self._digests)

    @property
    def events(self) -> List[str]:
        return list(self._events)

    @property
    def digests(self) -> List[str]:
        return list(self._digests)

    def _check_index(self, n: int) -> None:
        if not isinstance(n, int):
            raise TypeError("step index must be an int")
        if n < 0 or n >= len(self._digests):
            raise IndexError(
                "step %r out of range (ledger has %d steps)" % (n, len(self._digests))
            )

    def _load_state(self, digest: str) -> bytes:
        manifest = self.store.load_manifest(digest)
        return self.store.get(manifest)

    # ----------------------------------------------------------- persistence
    def _save(self) -> None:
        """Persist events + route data so the chain reloads faithfully.

        State blobs already live in the content-addressed store; here we persist
        the provenance routes (so the reversible machine can be rebuilt without
        recomputing) and the event/digest lists.
        """
        # Routes are NOT persisted: they are derived deterministically from
        # (bound_event, prior fingerprint), so we rebuild them by replay on load
        # and cross-check the persisted fingerprints. We persist the fingerprints
        # purely as an integrity anchor for that replay.
        steps = []
        for step in self.log.steps:
            steps.append({
                "fingerprint_before": step.fingerprint_before,
                "fingerprint_after": step.fingerprint_after,
            })
        meta = {
            "version": 1,
            "route_depth": self.route_depth,
            "events": self._events,
            "digests": self._digests,
            "steps": steps,
        }
        tmp = self._meta_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(meta, fh)
        os.replace(tmp, self._meta_path)

    def _load(self) -> None:
        """Rebuild from disk if a saved ledger exists.

        We rebuild the live ProvenanceLog by re-adding each bound event; because
        routes are derived deterministically from (event, prior fingerprint), the
        replay reproduces the persisted routes/fingerprints exactly. We then
        assert agreement so a corrupted meta file is caught at load time.
        """
        if not os.path.exists(self._meta_path):
            return
        with open(self._meta_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)

        self.route_depth = meta.get("route_depth", self.route_depth)
        self.log = knotcore.ProvenanceLog(route_depth=self.route_depth)
        self._events = []
        self._digests = []

        saved_steps = meta.get("steps", [])
        for event, digest, saved in zip(meta["events"], meta["digests"], saved_steps):
            step = self.log.add(_bound_event(event, digest))
            self._events.append(event)
            self._digests.append(digest)
            # Cross-check persisted fingerprints against the deterministic replay.
            if step.fingerprint_after != saved.get("fingerprint_after"):
                raise ValueError(
                    "persisted provenance does not match replay (corrupt ledger meta)"
                )

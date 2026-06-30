"""
Portable, offline-verifiable audit attestations for a DriftLedger.

``export_audit`` writes a self-contained JSON file capturing the ordered chain
(step, event, state_digest, fingerprint_after), a Merkle root over the state
digests, and — when a key is supplied — an HMAC-SHA256 signature.

``verify_audit`` re-checks that file **standalone** — without the original
ledger's private store — so a third party you hand the file to can confirm it is
internally consistent and (with the shared key) authentic.

Stdlib only, Python 3.8+.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from typing import List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
import knotcore  # noqa: E402

AUDIT_SCHEMA = 1
ALGORITHM = "HMAC-SHA256 / merkle-sha256"

# The exact keys ``AgentLedger.audit`` signs over, in the body it builds *before*
# appending the signed/signature fields. verify must reconstruct precisely this.
_SIGNED_BODY_KEYS = (
    "ledger", "steps", "count", "origin", "head", "merkle_root", "chain_verified",
)


def _as_key(key) -> Optional[bytes]:
    if key is None:
        return None
    return key.encode("utf-8") if isinstance(key, str) else bytes(key)


def _canonical(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


class AuditResult:
    """Outcome of :func:`verify_audit`."""

    def __init__(self, ok: bool, findings: List[str], signed: bool, signature_verified):
        self.ok = ok
        self.findings = findings
        self.signed = signed
        self.signature_verified = signature_verified  # True / False / None (no key)

    def __bool__(self):
        return self.ok

    def __repr__(self):
        return "AuditResult(ok=%r, signed=%r, signature_verified=%r, findings=%r)" % (
            self.ok, self.signed, self.signature_verified, self.findings)


def export_audit(ledger, path: str, key=None) -> dict:
    """Write a portable audit file for *ledger* to *path*.

    If *key* is given it signs with that key (overriding the ledger's own key for
    this export); otherwise the ledger's configured key (if any) is used.
    Returns the written document.
    """
    key = _as_key(key)
    if key is not None:
        prev = ledger.secret_key
        ledger.secret_key = key
        try:
            doc = dict(ledger.audit())
        finally:
            ledger.secret_key = prev
    else:
        doc = dict(ledger.audit())

    doc["_audit_schema"] = AUDIT_SCHEMA
    doc["_algorithm"] = ALGORITHM

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)
    return doc


def verify_audit(path: str, key=None) -> AuditResult:
    """Verify a portable audit file standalone (no ledger store needed)."""
    key = _as_key(key)
    findings: List[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)

    # 1. structural fields present
    missing = [k for k in _SIGNED_BODY_KEYS if k not in doc]
    if missing:
        return AuditResult(False, ["missing fields: %s" % ", ".join(missing)], False, None)

    steps = doc["steps"]
    ok = True

    # 2. count matches
    if doc["count"] != len(steps):
        ok = False
        findings.append("count (%s) != number of rows (%d)" % (doc["count"], len(steps)))

    # 3. Merkle root recomputes from the listed state digests
    digests = [row.get("state_digest", "") for row in steps]
    recomputed = knotcore.KnotStore.merkle_root(digests)
    if recomputed != doc["merkle_root"]:
        ok = False
        findings.append("merkle_root mismatch: a state_digest or the root was altered")

    # 4. head commits to the last recorded fingerprint
    if steps and doc["head"] != steps[-1].get("fingerprint_after"):
        ok = False
        findings.append("head fingerprint does not match the final step")

    # 5. signature
    signed = bool(doc.get("signed"))
    signature_verified = None
    if signed:
        body = {k: doc[k] for k in _SIGNED_BODY_KEYS}
        if key is None:
            findings.append("document is signed but no key supplied; signature NOT checked")
            signature_verified = None
        else:
            expected = hmac.new(key, _canonical(body), hashlib.sha256).hexdigest()
            signature_verified = hmac.compare_digest(expected, doc.get("signature") or "")
            if not signature_verified:
                ok = False
                findings.append("HMAC signature mismatch (wrong key or tampered content)")
    else:
        if key is not None:
            findings.append("key supplied but document is unsigned")

    if ok and not findings:
        findings.append("internally consistent" + (" and signature valid" if signature_verified else ""))
    return AuditResult(ok, findings, signed, signature_verified)

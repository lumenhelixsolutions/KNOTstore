"""driftledger CLI — zero-config, plug-n-play.

Commands:
    driftledger demo                          the proof (rollback + tamper-catch)
    driftledger log      <ledger>             show timeline + fingerprints
    driftledger verify   <ledger>             full integrity check
    driftledger rollback <ledger>             undo the last step
    driftledger audit    <ledger> [--key K]   signed audit trail (JSON)

Default ledger dir: ./.driftledger
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from driftledger.ledger import AgentLedger  # noqa: E402

DEFAULT_DIR = "./.driftledger"


# --------------------------------------------------------------------- helpers
def _short(fp: str, n: int = 16) -> str:
    return fp[:n]


def _print_timeline(ledger: AgentLedger) -> None:
    print("  step  fingerprint        event")
    print("  ----  -----------------  ----------------------------------")
    for i, step in enumerate(ledger.log.steps):
        print("  %4d  %-17s  %s" % (i, _short(step.fingerprint_after), ledger.events[i]))


# -------------------------------------------------------------------- commands
def cmd_log(args) -> int:
    ledger = AgentLedger(args.ledger)
    if len(ledger) == 0:
        print("ledger '%s' is empty" % args.ledger)
        return 0
    print("Ledger: %s   (%d steps)" % (ledger.root, len(ledger)))
    _print_timeline(ledger)
    print("  head fingerprint: %s" % ledger.log.fingerprint())
    return 0


def cmd_verify(args) -> int:
    ledger = AgentLedger(args.ledger)
    ok = ledger.verify()
    print("verify(%s): %s" % (args.ledger, "PASS" if ok else "FAIL (tamper detected)"))
    return 0 if ok else 1


def cmd_rollback(args) -> int:
    ledger = AgentLedger(args.ledger)
    if len(ledger) == 0:
        print("nothing to roll back")
        return 1
    event, state = ledger.rollback()
    print("rolled back step '%s'; ledger now has %d steps" % (event, len(ledger)))
    print("restored state (%d bytes): %r" % (len(state), state[:80]))
    return 0


def _read_key(path):
    if not path:
        return None
    with open(path, "rb") as fh:
        return fh.read().strip()


def cmd_audit(args) -> int:
    sub = getattr(args, "audit_cmd", None)
    if sub == "export":
        from .audit import export_audit
        ledger = AgentLedger(args.ledger)
        doc = export_audit(ledger, args.out, key=_read_key(getattr(args, "key_file", None)))
        print("wrote audit -> %s  (%d steps, signed=%s)" % (
            args.out, doc.get("count", 0), doc.get("signed")))
        return 0
    if sub == "verify":
        from .audit import verify_audit
        res = verify_audit(args.auditfile, key=_read_key(getattr(args, "key_file", None)))
        print("verify_audit(%s): %s" % (args.auditfile, "OK" if res.ok else "FAIL"))
        for f in res.findings:
            print("  - " + f)
        return 0 if res.ok else 1
    # default / "show": print the in-memory signed audit
    key = _read_key(getattr(args, "key_file", None)) or getattr(args, "key", None)
    ledger = AgentLedger(getattr(args, "ledger", DEFAULT_DIR), secret_key=key)
    print(json.dumps(ledger.audit(), indent=2, sort_keys=True))
    return 0


def cmd_demo(args) -> int:
    return run_demo()


# ------------------------------------------------------------------------ demo
def run_demo() -> int:
    """Build an agent memory, time-travel it, tamper it, and prove detection."""
    workdir = tempfile.mkdtemp(prefix="driftledger-demo-")
    root = os.path.join(workdir, "agent")
    passed = True
    try:
        print("=" * 70)
        print("DriftLedger DEMO — tamper-evident, time-travel memory for AI agents")
        print("=" * 70)

        key = b"soc2-audit-key"
        ledger = AgentLedger(root, secret_key=key)

        # 1. Build ~8 steps of evolving agent memory.
        memories = [
            "boot: empty working memory",
            "observe: user asks to book a flight",
            "plan: search flights LON->NYC",
            "tool: flights api returned 3 options",
            "decide: pick 09:00 nonstop",
            "observe: user prefers window seat",
            "tool: seat map fetched",
            "act: seat 14A reserved, booking held",
        ]
        print("\n[1] Building agent memory (%d steps)..." % len(memories))
        for i, mem in enumerate(memories):
            ledger.append("step%d" % i, mem.encode("utf-8"))
        _print_timeline(ledger)
        print("    head fingerprint:", _short(ledger.log.fingerprint()))

        # 2. Roll back 3 steps; prove exact prior state recovered.
        print("\n[2] Rolling back 3 steps (reversible inverse routes)...")
        target = len(ledger) - 4  # state we expect to land on
        expected_state = ledger.checkout(target)
        for _ in range(3):
            event, _ = ledger.rollback()
            print("    - undid %s -> head %s" % (event, _short(ledger.log.fingerprint())))
        recovered = ledger.checkout(len(ledger) - 1)
        exact = recovered == expected_state
        passed = passed and exact
        print("    exact prior state recovered: %s" % ("YES" if exact else "NO"))
        print("    state @ step %d: %r" % (len(ledger) - 1, recovered.decode("utf-8")))

        # 3. Branch an alternate timeline from the current head.
        print("\n[3] Branching an alternate timeline from step %d..." % (len(ledger) - 1))
        branch = ledger.branch(len(ledger) - 1)
        branch.append("alt", b"decide: pick cheaper 22:00 redeye instead")
        print("    original head: %s (%d steps)" % (_short(ledger.log.fingerprint()), len(ledger)))
        print("    branch   head: %s (%d steps)" % (_short(branch.log.fingerprint()), len(branch)))
        independent = (
            ledger.log.fingerprint() != branch.log.fingerprint()
            and len(branch) == len(ledger) + 1
        )
        passed = passed and independent
        print("    branch is an independent timeline: %s" % ("YES" if independent else "NO"))

        # 4. Clean verify should PASS.
        print("\n[4] Verifying clean ledger...")
        clean_ok = ledger.verify()
        passed = passed and clean_ok
        print("    verify() on clean ledger: %s" % ("PASS" if clean_ok else "FAIL"))

        # 5. Tamper a stored state file on disk; verify() must CATCH it.
        print("\n[5] Tampering a stored state blob on disk...")
        objects_dir = os.path.join(root, "objects")
        victim = None
        for name in sorted(os.listdir(objects_dir)):
            p = os.path.join(objects_dir, name)
            if os.path.isfile(p):
                victim = p
                break
        with open(victim, "ab") as fh:
            fh.write(b"\x00EVIL")
        print("    corrupted: %s" % os.path.basename(victim))
        # Fresh handle so we read tampered bytes from disk, not cache.
        reopened = AgentLedger(root, secret_key=key)
        tamper_caught = not reopened.verify()
        passed = passed and tamper_caught
        print("    verify() after tamper: %s" %
              ("FAIL -> tamper CAUGHT (correct)" if tamper_caught else "PASS -> MISSED (bug!)"))

        # 6. Signed audit trail (over the still-clean branch).
        print("\n[6] Signed audit trail (HMAC-SHA256) of the branch...")
        audit = branch.audit()
        print("    steps        :", audit["count"])
        print("    merkle_root  :", _short(str(audit["merkle_root"]), 24))
        print("    head         :", _short(str(audit["head"])))
        print("    signed       :", audit["signed"])
        print("    signature    :", _short(str(audit["signature"]), 24), "...")
        signed_ok = bool(audit["signed"]) and audit["signature"] is not None
        passed = passed and signed_ok

        print("\n" + "=" * 70)
        print("RESULT: %s" % ("PASS — rollback + tamper-detection proven" if passed
                              else "FAIL — see above"))
        print("=" * 70)
        return 0 if passed else 1
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ------------------------------------------------------------------------ main
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="driftledger",
        description="Tamper-evident, time-travel memory for AI agents.",
    )
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("demo", help="run the end-to-end proof (zero args)")
    sp.set_defaults(func=cmd_demo)

    sp = sub.add_parser("log", help="show the timeline + fingerprints")
    sp.add_argument("ledger", nargs="?", default=DEFAULT_DIR)
    sp.set_defaults(func=cmd_log)

    sp = sub.add_parser("verify", help="full integrity / tamper check")
    sp.add_argument("ledger", nargs="?", default=DEFAULT_DIR)
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser("rollback", help="undo the last step")
    sp.add_argument("ledger", nargs="?", default=DEFAULT_DIR)
    sp.set_defaults(func=cmd_rollback)

    sp = sub.add_parser("audit", help="emit / export / verify a signed audit trail")
    sp.set_defaults(func=cmd_audit)
    asub = sp.add_subparsers(dest="audit_cmd")
    ash = asub.add_parser("show", help="print the in-memory signed audit (default)")
    ash.add_argument("ledger", nargs="?", default=DEFAULT_DIR)
    ash.add_argument("--key", default=None, help="HMAC secret key for signing (inline)")
    ash.add_argument("--key-file", default=None, help="file holding the HMAC key")
    ash.set_defaults(func=cmd_audit)
    ax = asub.add_parser("export", help="write a portable, offline-verifiable audit file")
    ax.add_argument("ledger", nargs="?", default=DEFAULT_DIR)
    ax.add_argument("--out", required=True, help="audit JSON output path")
    ax.add_argument("--key-file", default=None, help="file holding the HMAC key")
    ax.set_defaults(func=cmd_audit)
    av = asub.add_parser("verify", help="verify a portable audit file standalone")
    av.add_argument("auditfile", help="path to an exported audit JSON")
    av.add_argument("--key-file", default=None, help="file holding the HMAC key")
    av.set_defaults(func=cmd_audit)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        # Zero-config default: run the proof.
        return run_demo()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

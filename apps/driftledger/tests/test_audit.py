from __future__ import annotations
import os, sys, json, shutil, tempfile
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from driftledger.ledger import AgentLedger
from driftledger.audit import export_audit, verify_audit

def _ledger(d, key=None):
    lg = AgentLedger(d, secret_key=key)
    for i in range(6):
        lg.append("step-%d" % i, ("state %d payload" % i).encode())
    return lg

def test_export_then_verify_roundtrip():
    d = tempfile.mkdtemp()
    try:
        lg = _ledger(d, key=b"s3cret")
        path = os.path.join(d, "audit.json")
        export_audit(lg, path, key=b"s3cret")
        res = verify_audit(path, key=b"s3cret")
        assert res.ok and res.signature_verified is True
    finally:
        shutil.rmtree(d)

def test_verify_is_portable_without_store():
    # copy ONLY the audit file to a fresh dir -> still verifies (standalone)
    d = tempfile.mkdtemp(); e = tempfile.mkdtemp()
    try:
        lg = _ledger(d, key=b"k")
        src = os.path.join(d, "a.json"); export_audit(lg, src, key=b"k")
        dst = os.path.join(e, "a.json"); shutil.copyfile(src, dst)
        assert verify_audit(dst, key=b"k").ok
    finally:
        shutil.rmtree(d); shutil.rmtree(e)

def test_tamper_is_caught():
    d = tempfile.mkdtemp()
    try:
        lg = _ledger(d, key=b"k")
        path = os.path.join(d, "a.json"); export_audit(lg, path, key=b"k")
        doc = json.load(open(path))
        doc["steps"][2]["state_digest"] = "0" * 64          # flip a digest
        json.dump(doc, open(path, "w"))
        res = verify_audit(path, key=b"k")
        assert not res.ok
    finally:
        shutil.rmtree(d)

def test_wrong_key_fails_right_key_passes():
    d = tempfile.mkdtemp()
    try:
        lg = _ledger(d, key=b"right")
        path = os.path.join(d, "a.json"); export_audit(lg, path, key=b"right")
        assert verify_audit(path, key=b"wrong").ok is False
        assert verify_audit(path, key=b"right").ok is True
    finally:
        shutil.rmtree(d)

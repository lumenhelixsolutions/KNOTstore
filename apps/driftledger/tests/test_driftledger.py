"""Tests for DriftLedger. Run from repo root:

    python -m pytest apps/driftledger -q
"""
from __future__ import annotations

import os
import sys

import pytest

# Make the driftledger package importable regardless of cwd.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from driftledger import AgentLedger  # noqa: E402


def _build(root, n=5):
    led = AgentLedger(root)
    for i in range(n):
        led.append("ev%d" % i, ("state-%d" % i).encode("utf-8"))
    return led


def test_append_checkout_roundtrip(tmp_path):
    led = _build(str(tmp_path / "l"), n=6)
    assert len(led) == 6
    for i in range(6):
        assert led.checkout(i) == ("state-%d" % i).encode("utf-8")
    with pytest.raises(IndexError):
        led.checkout(6)


def test_rollback_recovers_exact_prior_state(tmp_path):
    led = _build(str(tmp_path / "l"), n=4)
    prior = led.checkout(2)  # state we should land back on
    event, restored = led.rollback()
    assert event == "ev3"
    assert restored == prior
    assert len(led) == 3
    # Chain still verifies after rewind.
    assert led.verify()


def test_branch_is_independent_timeline(tmp_path):
    led = _build(str(tmp_path / "l"), n=4)
    branch = led.branch(2)  # steps 0..2
    assert len(branch) == 3
    branch.append("alt", b"alternate-state")
    # Original untouched.
    assert len(led) == 4
    # Divergent heads.
    assert branch.log.fingerprint() != led.log.fingerprint()
    # Both verify independently.
    assert led.verify()
    assert branch.verify()
    # Shared-prefix states match.
    assert branch.checkout(1) == led.checkout(1)


def test_verify_passes_clean_and_persists(tmp_path):
    root = str(tmp_path / "l")
    led = _build(root, n=5)
    assert led.verify()
    # Reload from disk and re-verify (survives restart).
    reloaded = AgentLedger(root)
    assert len(reloaded) == 5
    assert reloaded.checkout(3) == b"state-3"
    assert reloaded.verify()


def test_verify_fails_on_corrupted_state_file(tmp_path):
    root = str(tmp_path / "l")
    led = _build(root, n=5)
    assert led.verify()

    objects_dir = os.path.join(root, "objects")
    names = [n for n in sorted(os.listdir(objects_dir))
             if os.path.isfile(os.path.join(objects_dir, n))]
    assert names, "expected stored state objects on disk"
    victim = os.path.join(objects_dir, names[0])
    with open(victim, "ab") as fh:
        fh.write(b"TAMPER")

    reopened = AgentLedger(root)
    assert reopened.verify() is False


def test_audit_hmac_changes_when_content_changes(tmp_path):
    root_a = str(tmp_path / "a")
    led_a = _build(root_a, n=4)
    sig_a = AgentLedger(root_a, secret_key=b"k").audit()["signature"]

    # Same content, same key -> identical signature (deterministic).
    sig_a2 = AgentLedger(root_a, secret_key=b"k").audit()["signature"]
    assert sig_a == sig_a2 is not None

    # Different content -> different signature.
    root_b = str(tmp_path / "b")
    led_b = _build(root_b, n=4)
    led_b.append("extra", b"extra-state")
    sig_b = AgentLedger(root_b, secret_key=b"k").audit()["signature"]
    assert sig_b != sig_a

    # No key -> unsigned.
    assert AgentLedger(root_a).audit()["signature"] is None
    assert AgentLedger(root_a).audit()["signed"] is False

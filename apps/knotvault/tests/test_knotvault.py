"""Tests for KnotVault: add/verify/extract round-trip, dedup, tamper detection."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from knotvault import Vault, VaultError, TamperError  # noqa: E402


def _write(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))


def test_add_verify_extract_roundtrip(tmp_path):
    src = tmp_path / "src"
    _write(str(src / "a.txt"), b"alpha" * 1000)
    _write(str(src / "sub" / "b.txt"), b"beta" * 1000)

    vault = Vault(str(tmp_path / "vault"))
    res = vault.add([str(src)], name="proj")
    assert res.files == 2
    assert len(res.root_digest) == 64

    assert vault.verify("proj") == res.root_digest

    dest = tmp_path / "out"
    written = vault.extract("proj", str(dest))
    assert len(written) == 2
    # Structure preserved (top dir "src" retained).
    with open(str(dest / "src" / "a.txt"), "rb") as fh:
        assert fh.read() == b"alpha" * 1000
    with open(str(dest / "src" / "sub" / "b.txt"), "rb") as fh:
        assert fh.read() == b"beta" * 1000


def test_dedup_reduces_on_disk_bytes(tmp_path):
    src = tmp_path / "src"
    body = b"shared payload block. " * 2000
    _write(str(src / "one.txt"), body)
    _write(str(src / "two.txt"), body)   # exact duplicate
    _write(str(src / "three.txt"), body)  # exact duplicate

    vault = Vault(str(tmp_path / "vault"))
    res = vault.add([str(src)], name="dups")
    # Three identical files: on-disk must be far below input.
    assert res.bytes_on_disk < res.input_bytes
    assert res.dedup_savings_pct > 50.0


def test_tamper_detection(tmp_path):
    src = tmp_path / "src"
    _write(str(src / "secret.txt"), b"do-not-change " * 500)
    vault_dir = tmp_path / "vault"
    vault = Vault(str(vault_dir))
    vault.add([str(src)], name="arc")
    assert vault.verify("arc")  # clean

    # Corrupt one object on disk.
    objects = str(vault_dir / "objects")
    victim = os.path.join(objects, sorted(os.listdir(objects))[0])
    with open(victim, "r+b") as fh:
        data = fh.read()
        fh.seek(0)
        fh.write(bytes((b ^ 0xFF) for b in data))

    with pytest.raises(TamperError):
        vault.verify("arc")


def test_missing_path_errors(tmp_path):
    vault = Vault(str(tmp_path / "vault"))
    with pytest.raises(VaultError):
        vault.add([str(tmp_path / "nope")], name="x")


def test_duplicate_archive_name_rejected(tmp_path):
    f = tmp_path / "f.txt"
    _write(str(f), b"hi")
    vault = Vault(str(tmp_path / "vault"))
    vault.add([str(f)], name="dup")
    with pytest.raises(VaultError):
        vault.add([str(f)], name="dup")


def test_verify_unknown_archive(tmp_path):
    vault = Vault(str(tmp_path / "vault"))
    with pytest.raises(VaultError):
        vault.verify("ghost")


def test_index_persists_across_instances(tmp_path):
    f = tmp_path / "f.txt"
    _write(str(f), b"persist me")
    vault_dir = str(tmp_path / "vault")
    Vault(vault_dir).add([str(f)], name="keep")
    # Fresh instance reads the index from disk.
    vault2 = Vault(vault_dir)
    assert "keep" in vault2.archives()
    assert vault2.verify("keep")

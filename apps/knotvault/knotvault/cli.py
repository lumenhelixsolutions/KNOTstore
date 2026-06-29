"""Command-line interface for KnotVault.

Zero-config: the vault defaults to ``./.knotvault``. Override with ``--vault``.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from typing import List, Optional

from .vault import Vault, VaultError, TamperError

PROG = "knotvault"


def _short(digest: str, width: int = 16) -> str:
    return digest[:width] + "…" if len(digest) > width else digest


# ----------------------------------------------------------------- commands
def cmd_add(args: argparse.Namespace) -> int:
    vault = Vault(args.vault)
    res = vault.add(args.paths, name=args.name)
    print("archive : {}".format(res.name))
    print("files   : {}".format(res.files))
    print("input   : {:,} bytes".format(res.input_bytes))
    print("on disk : {:,} bytes".format(res.bytes_on_disk))
    print("dedup   : {:.1f}% saved".format(res.dedup_savings_pct))
    print("root    : {}".format(res.root_digest))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    vault = Vault(args.vault)
    root = vault.verify(args.name)
    print("OK  {}  root={}".format(args.name, root))
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    vault = Vault(args.vault)
    written = vault.extract(args.name, args.dest)
    print("extracted {} file(s) from {!r} to {}".format(
        len(written), args.name, os.path.abspath(args.dest)))
    for p in written:
        print("  {}".format(p))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    vault = Vault(args.vault)
    names = vault.archives()
    if not names:
        print("(no archives in {})".format(vault.root))
        return 0
    for name in names:
        entries = vault.entries(name)
        total = sum(e.size for e in entries)
        root = vault.archive_root(name)
        print("{name}  files={n}  bytes={b:,}  root={r}".format(
            name=name, n=len(entries), b=total, r=_short(root, 24)))
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Zero-config end-to-end proof of dedup + tamper-evidence."""
    workdir = tempfile.mkdtemp(prefix="knotvault-demo-")
    vault_dir = os.path.join(workdir, "vault")
    src = os.path.join(workdir, "src")
    os.makedirs(src)
    ok = True
    try:
        # --- synthetic data: duplicates + near-duplicates --------------------
        body = ("KnotVault demo payload. " * 400).encode("utf-8")
        files = {
            "report.txt": body,
            "report_copy.txt": body,                       # exact duplicate
            "report_v2.txt": body + b"  (revised footer)",  # near-duplicate
            "notes/today.md": b"# notes\n" + b"line\n" * 500,
            "notes/today_again.md": b"# notes\n" + b"line\n" * 500,  # exact dup
        }
        for rel, data in files.items():
            fp = os.path.join(src, rel)
            os.makedirs(os.path.dirname(fp) or src, exist_ok=True)
            with open(fp, "wb") as fh:
                fh.write(data)

        print("== KnotVault demo ==")
        print("workdir: {}".format(workdir))
        print()

        vault = Vault(vault_dir)
        res = vault.add([src], name="demo")
        print("[1] added archive 'demo'")
        print("    files={} input={:,}B on-disk={:,}B dedup={:.1f}%".format(
            res.files, res.input_bytes, res.bytes_on_disk, res.dedup_savings_pct))
        print("    root={}".format(res.root_digest))
        dedup_ok = res.dedup_savings_pct > 0
        print("    dedup savings > 0 ? {}".format("PASS" if dedup_ok else "FAIL"))
        ok = ok and dedup_ok
        print()

        # --- clean verify should pass ----------------------------------------
        try:
            root = vault.verify("demo")
            print("[2] verify (clean): OK  root={}".format(root))
            print("    PASS")
        except VaultError as exc:
            print("[2] verify (clean) unexpectedly FAILED: {}".format(exc))
            ok = False
        print()

        # --- extract round-trips ---------------------------------------------
        out = os.path.join(workdir, "out")
        written = vault.extract("demo", out)
        roundtrip_ok = True
        src_parent = os.path.dirname(src)
        for p in written:
            # relpath includes the top "src" dir; resolve back to original.
            rel = os.path.relpath(p, out)
            orig = os.path.join(src_parent, rel)
            with open(p, "rb") as a, open(orig, "rb") as b:
                if a.read() != b.read():
                    roundtrip_ok = False
        print("[3] extract round-trip ({} files): {}".format(
            len(written), "PASS" if roundtrip_ok else "FAIL"))
        ok = ok and roundtrip_ok
        print()

        # --- deliberately corrupt one object on disk -------------------------
        objects_dir = os.path.join(vault_dir, "objects")
        obj_names = sorted(os.listdir(objects_dir))
        victim = os.path.join(objects_dir, obj_names[0])
        with open(victim, "r+b") as fh:
            original = fh.read()
            fh.seek(0)
            # Flip every byte so the chunk no longer hashes to its address.
            fh.write(bytes((b ^ 0xFF) for b in original))
        print("[4] corrupted object on disk: {}".format(obj_names[0]))

        caught = False
        try:
            vault.verify("demo")
        except TamperError as exc:
            caught = True
            print("    verify CAUGHT it -> {}".format(exc))
        except VaultError as exc:
            caught = True
            print("    verify reported failure -> {}".format(exc))
        if not caught:
            print("    verify FAILED to catch corruption!")
        print("    tamper detected ? {}".format("PASS" if caught else "FAIL"))
        ok = ok and caught
        print()

        print("== SUMMARY: {} ==".format("PASS" if ok else "FAIL"))
        return 0 if ok else 1
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="KnotVault — a tamper-evident, deduplicating file/folder "
                    "archiver. zip + a cryptographic integrity receipt.",
    )
    parser.add_argument(
        "--vault", default="./.knotvault", metavar="DIR",
        help="vault directory (default: ./.knotvault)",
    )
    sub = parser.add_subparsers(dest="command")

    p_add = sub.add_parser("add", help="archive files/dirs into the vault")
    p_add.add_argument("paths", nargs="+", help="files or directories to archive")
    p_add.add_argument("--name", default=None,
                       help="archive name (default: derived from first path)")
    p_add.set_defaults(func=cmd_add)

    p_verify = sub.add_parser("verify", help="re-check every chunk of an archive")
    p_verify.add_argument("name", help="archive name to verify")
    p_verify.set_defaults(func=cmd_verify)

    p_extract = sub.add_parser("extract", help="restore an archive (verifies on the way out)")
    p_extract.add_argument("name", help="archive name to extract")
    p_extract.add_argument("dest", help="destination directory")
    p_extract.set_defaults(func=cmd_extract)

    p_list = sub.add_parser("list", help="list archives in the vault")
    p_list.set_defaults(func=cmd_list)

    p_demo = sub.add_parser("demo", help="zero-config end-to-end tamper-evidence proof")
    p_demo.set_defaults(func=cmd_demo)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except TamperError as exc:
        print("TAMPER: {}".format(exc), file=sys.stderr)
        return 2
    except VaultError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

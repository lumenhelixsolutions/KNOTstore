"""
knot — one command to drive the whole KNOTstore application suite.

    knot vault   ...    →  KnotVault       (tamper-evident dedup archiver)
    knot forge   ...    →  PrefixForge     (LLM prefix cache w/ near-dup locality)
    knot ledger  ...    →  DriftLedger     (time-travel, tamper-evident agent memory)
    knot checkpoint ... →  CheckpointTime  (reversible deduped checkpoints)

    knot demo [--all]   →  run one or every app's zero-config demo
    knot list           →  list the apps and their status
    knot --version

Dispatch is by subprocess (``python -m <app>``) so the meta-CLI is decoupled
from each app's internal API and works whether you run from a cloned repo or
from an installed console script. Stdlib only, Python 3.8+.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

__version__ = "0.2.0"

# alias -> (package module, friendly name, one-line pitch)
APPS = {
    "vault": ("knotvault", "KnotVault", "tamper-evident, deduplicating archiver"),
    "forge": ("prefixforge", "PrefixForge", "LLM prefix cache with near-duplicate locality"),
    "ledger": ("driftledger", "DriftLedger", "time-travel, tamper-evident agent memory"),
    "checkpoint": ("checkpointtime", "CheckpointTime", "reversible, deduped checkpoints"),
}
# accept the package name as an alias too (knot knotvault ... == knot vault ...)
ALIASES = {pkg: alias for alias, (pkg, _n, _p) in APPS.items()}


def _repo_root() -> str:
    # apps/knot/knot/cli.py  ->  repo root is three levels up
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _app_dir(pkg: str) -> str:
    return os.path.join(_repo_root(), "apps", _app_alias_to_pkg(pkg))


def _app_alias_to_pkg(name: str) -> str:
    if name in APPS:
        return APPS[name][0]
    if name in ALIASES:  # already a package name
        return name
    raise KeyError(name)


def _run_app(name: str, args, capture: bool = False):
    """Invoke ``python -m <pkg> <args>`` with the app package importable."""
    pkg = _app_alias_to_pkg(name)
    app_dir = os.path.join(_repo_root(), "apps", pkg)
    env = dict(os.environ)
    # make the app package importable in-place; keep repo root for `import knotcore`
    extra = os.pathsep.join([app_dir, _repo_root()])
    env["PYTHONPATH"] = extra + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    cmd = [sys.executable, "-m", pkg] + list(args)
    if capture:
        return subprocess.run(cmd, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True)
    return subprocess.run(cmd, env=env)


def _cmd_list(_args) -> int:
    print("KNOTstore suite — {} apps\n".format(len(APPS)))
    for alias, (pkg, friendly, pitch) in APPS.items():
        present = os.path.isdir(os.path.join(_repo_root(), "apps", pkg, pkg))
        mark = "ok " if present else "?? "
        print("  [{}] knot {:<11} {:<15} {}".format(mark, alias, friendly, pitch))
    print("\nRun a tool:   knot <app> --help")
    print("Try it all:   knot demo --all")
    return 0


def _cmd_demo(args) -> int:
    targets = list(APPS) if args.all or not args.app else [args.app]
    failures = []
    for alias in targets:
        friendly = APPS[alias][1]
        print("\n" + "=" * 64)
        print("  DEMO: {}  (knot {})".format(friendly, alias))
        print("=" * 64)
        rc = _run_app(alias, ["demo"]).returncode
        if rc != 0:
            failures.append(friendly)
    print("\n" + "-" * 64)
    if failures:
        print("  DEMOS FAILED: {}".format(", ".join(failures)))
        return 1
    print("  ALL DEMOS PASSED ({}).".format(", ".join(APPS[a][1] for a in targets)))
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="knot",
        description="One command for the KNOTstore application suite.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="apps:  " + "  ".join(APPS) + "\nexample:  knot vault add ./folder --name backup",
    )
    parser.add_argument("--version", action="version", version="knot {}".format(__version__))
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("list", help="list the apps and their status")
    d = sub.add_parser("demo", help="run an app's demo (or every app's with --all)")
    d.add_argument("app", nargs="?", choices=list(APPS), help="which app to demo")
    d.add_argument("--all", action="store_true", help="run every app's demo")

    # one passthrough subcommand per app: `knot vault <args...>`
    for alias, (_pkg, friendly, pitch) in APPS.items():
        sp = sub.add_parser(alias, help=pitch, add_help=False)
        sp.add_argument("rest", nargs=argparse.REMAINDER)

    # allow `knot <pkgname> ...` too
    if argv and argv[0] in ALIASES:
        argv[0] = ALIASES[argv[0]]

    if not argv:
        parser.print_help()
        return 0

    args, _ = parser.parse_known_args(argv)
    if args.command == "list":
        return _cmd_list(args)
    if args.command == "demo":
        return _cmd_demo(args)
    if args.command in APPS:
        # everything after the app name is forwarded verbatim
        rest = argv[1:]
        return _run_app(args.command, rest).returncode

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

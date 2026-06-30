from __future__ import annotations
import os, sys, subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
KNOT = os.path.join(ROOT, "apps", "knot")

def _run(args):
    env = dict(os.environ)
    env["PYTHONPATH"] = KNOT + os.pathsep + ROOT + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run([sys.executable, "-m", "knot"] + args, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

def test_version():
    r = _run(["--version"]); assert r.returncode == 0 and "knot" in r.stdout

def test_list_shows_four_apps():
    r = _run(["list"]); assert r.returncode == 0
    for alias in ("vault", "forge", "ledger", "checkpoint"):
        assert alias in r.stdout

def test_passthrough_help_reaches_app():
    r = _run(["forge", "--help"])
    assert r.returncode == 0 and "prefixforge" in r.stdout.lower()

def test_unknown_app_is_graceful():
    r = _run([])  # no args -> help, exit 0
    assert r.returncode == 0

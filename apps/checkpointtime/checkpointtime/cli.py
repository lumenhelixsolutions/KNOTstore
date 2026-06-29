"""Command-line interface for CheckpointTime."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time

from .store import CheckpointStore, DEFAULT_DIR, CheckpointError


def _fmt_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(n)
    for u in units:
        if f < 1024.0 or u == units[-1]:
            return ("%.0f %s" % (f, u)) if u == "B" else ("%.2f %s" % (f, u))
        f /= 1024.0
    return "%d B" % n


# ----------------------------------------------------------------- subcommands
def cmd_snapshot(args) -> int:
    store = CheckpointStore(args.dir)
    cid = store.snapshot_path(args.path, label=args.label or "")
    s = store.stats()
    print("snapshot %s  (label=%r)" % (cid, args.label or os.path.basename(args.path)))
    print("  logical=%s  physical=%s  dedup=%.2fx"
          % (_fmt_bytes(s["logical_bytes"]), _fmt_bytes(s["physical_bytes_on_disk"]),
             s["dedup_ratio"]))
    return 0


def cmd_restore(args) -> int:
    store = CheckpointStore(args.dir)
    try:
        store.restore_path(args.id, args.dest)
    except CheckpointError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    print("restored %s -> %s" % (args.id, args.dest))
    return 0


def cmd_timeline(args) -> int:
    store = CheckpointStore(args.dir)
    rows = store.timeline()
    if not rows:
        print("(no checkpoints yet)")
        return 0
    print("%-14s %-10s %-12s %-19s %s" % ("ID", "SIZE", "BRANCH", "TIME", "LABEL"))
    for r in rows:
        head = " <-HEAD" if r["id"] == store.head else ""
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["time"]))
        print("%-14s %-10s %-12s %-19s %s%s"
              % (r["id"], _fmt_bytes(r["size"]), r["branch"], ts, r["label"], head))
    return 0


def cmd_stats(args) -> int:
    store = CheckpointStore(args.dir)
    s = store.stats()
    print("checkpoints : %d" % s["checkpoints"])
    print("logical     : %s (%d bytes)" % (_fmt_bytes(s["logical_bytes"]), s["logical_bytes"]))
    print("physical    : %s (%d bytes)" % (_fmt_bytes(s["physical_bytes_on_disk"]),
                                           s["physical_bytes_on_disk"]))
    print("dedup ratio : %.2fx" % s["dedup_ratio"])
    return 0


def cmd_demo(args) -> int:
    """Simulate a long run: ~20 checkpoints of a large, slowly-mutating blob."""
    workdir = tempfile.mkdtemp(prefix="checkpointtime-demo-")
    store_dir = os.path.join(workdir, "store")
    store = CheckpointStore(store_dir, chunk_size=1024)

    n_steps = 20
    base = bytearray((b"MODEL-STATE-BLOCK-" * 4096))  # ~80 KB of stable state
    print("CheckpointTime demo: %d checkpoints of a ~%s blob that mutates "
          "slightly each step\n" % (n_steps, _fmt_bytes(len(base))))

    ids = []
    for step in range(n_steps):
        # mutate only a tiny region each step (like a training step nudging weights)
        for k in range(64):
            pos = (step * 997 + k * 131) % len(base)
            base[pos] = (base[pos] + step + k) % 256
        cid = store.snapshot(bytes(base), label="step-%02d" % step)
        ids.append(cid)

    s = store.stats()
    print("%-8s %-14s %-14s" % ("", "LOGICAL", "PHYSICAL ON DISK"))
    print("%-8s %-14s %-14s" % ("totals", _fmt_bytes(s["logical_bytes"]),
                                _fmt_bytes(s["physical_bytes_on_disk"])))
    print("\nlogical bytes (sum of all %d checkpoints): %d" % (n_steps, s["logical_bytes"]))
    print("physical bytes actually on disk          : %d" % s["physical_bytes_on_disk"])
    print("dedup ratio (logical / physical)         : %.2fx" % s["dedup_ratio"])
    savings = 1.0 - (s["physical_bytes_on_disk"] / float(s["logical_bytes"]))
    print("space saved by dedup                     : %.1f%%" % (savings * 100.0))

    dedup_ok = s["physical_bytes_on_disk"] < s["logical_bytes"] / 2.0

    # rewind + restore + exact-match verification
    target = ids[5]
    print("\nrewinding HEAD to checkpoint %s (step-05)..." % target)
    store.rewind(target)
    restored = store.restore(target)

    # recompute exactly what step-05 looked like to compare byte-for-byte
    ref = bytearray((b"MODEL-STATE-BLOCK-" * 4096))
    for step in range(6):
        for k in range(64):
            pos = (step * 997 + k * 131) % len(ref)
            ref[pos] = (ref[pos] + step + k) % 256
    restore_ok = restored == bytes(ref)
    print("restored bytes match the original step-05 state exactly: %s" % restore_ok)
    print("HEAD is now: %s" % store.head)

    # branch a new timeline
    bname = "experiment"
    store.branch(target, bname)
    branch_ok = store.branch_name == bname and store.head == target
    print("branched new timeline %r from %s: %s" % (bname, target, branch_ok))

    chain_ok = store._log.verify_chain()
    print("provenance chain verifies (reversible timeline): %s" % chain_ok)

    ok = dedup_ok and restore_ok and branch_ok and chain_ok
    print("\n%s" % ("PASS: dedup saves space, rewind+restore exact, branch works"
                    if ok else "FAIL: see above"))
    print("(demo store: %s)" % store_dir)
    return 0 if ok else 1


# --------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="checkpointtime",
        description="Reversible, deduplicated checkpoint store for long-running jobs.",
    )
    p.add_argument("--dir", default=DEFAULT_DIR,
                   help="store directory (default: %s)" % DEFAULT_DIR)
    sub = p.add_subparsers(dest="command")

    d = sub.add_parser("demo", help="run the zero-config dedup + rewind proof")
    d.set_defaults(func=cmd_demo)

    sn = sub.add_parser("snapshot", help="snapshot a file or directory")
    sn.add_argument("path", help="file or directory to snapshot")
    sn.add_argument("--label", default="", help="human-friendly label")
    sn.set_defaults(func=cmd_snapshot)

    rs = sub.add_parser("restore", help="restore a checkpoint to a destination path")
    rs.add_argument("id", help="checkpoint id")
    rs.add_argument("dest", help="destination file or directory")
    rs.set_defaults(func=cmd_restore)

    tl = sub.add_parser("timeline", help="list checkpoints in order")
    tl.set_defaults(func=cmd_timeline)

    st = sub.add_parser("stats", help="show logical vs physical bytes and dedup ratio")
    st.set_defaults(func=cmd_stats)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

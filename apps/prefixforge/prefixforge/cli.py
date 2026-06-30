"""prefixforge command-line interface.

Subcommands
-----------
demo            Replay a near-duplicate prompt stream and print the hit-rate lift.
put             Store a cached value for a prompt in an on-disk cache.
query           Look up a prompt and print kind / similarity / tokens_saved.
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from . import __version__
from .cache import PrefixCache
from . import demo as demo_mod


def _cmd_demo(args):
    # type: (argparse.Namespace) -> int
    metrics = demo_mod.run(n=args.n, seed=args.seed, threshold=args.threshold)
    print(demo_mod.format_report(metrics))
    return 0


def _cmd_put(args):
    # type: (argparse.Namespace) -> int
    try:
        with open(args.value_file, "rb") as fh:
            value = fh.read()
    except OSError as exc:
        print("error: cannot read --value-file: %s" % exc, file=sys.stderr)
        return 2
    cache = PrefixCache(root=args.root, threshold=args.threshold)
    key = cache.put(args.prompt, value, tokens=args.tokens)
    print("stored: key=%s tokens=%d bytes=%d" % (key, args.tokens, len(value)))
    return 0


def _cmd_query(args):
    # type: (argparse.Namespace) -> int
    cache = PrefixCache(root=args.root, threshold=args.threshold)
    r = cache.get(args.prompt)
    print("kind:         %s" % r.kind)
    print("similarity:   %.4f" % r.similarity)
    print("tokens_saved: %d" % r.tokens_saved)
    if r.distance is not None:
        print("distance:     %d" % r.distance)
    if r.prompt is not None:
        print("matched:      %s" % r.prompt)
    if args.show_value and r.value is not None:
        sys.stdout.buffer.write(r.value)
        sys.stdout.buffer.write(b"\n")
    return 0 if r.hit else 1


def build_parser():
    # type: () -> argparse.ArgumentParser
    p = argparse.ArgumentParser(
        prog="prefixforge",
        description="Content-addressed LLM prompt cache with near-duplicate locality.",
    )
    p.add_argument("--version", action="version",
                   version="prefixforge %s" % __version__)
    sub = p.add_subparsers(dest="command")

    d = sub.add_parser("demo", help="show exact vs exact+near hit-rate lift")
    d.add_argument("-n", type=int, default=200, help="number of prompts (default 200)")
    d.add_argument("--seed", type=int, default=42, help="RNG seed (default 42)")
    d.add_argument("--threshold", type=int, default=8,
                   help="near-hit Hamming threshold (default 8)")
    d.set_defaults(func=_cmd_demo)

    pu = sub.add_parser("put", help="store a cached value for a prompt")
    pu.add_argument("prompt")
    pu.add_argument("--value-file", required=True, help="file with the cached blob")
    pu.add_argument("--tokens", type=int, default=0, help="tokens this entry saves")
    pu.add_argument("--root", default="./.prefixforge", help="cache directory")
    pu.add_argument("--threshold", type=int, default=8)
    pu.set_defaults(func=_cmd_put)

    q = sub.add_parser("query", help="look up a prompt against an on-disk cache")
    q.add_argument("prompt")
    q.add_argument("--root", default="./.prefixforge", help="cache directory")
    q.add_argument("--threshold", type=int, default=8)
    q.add_argument("--show-value", action="store_true", help="also write the blob to stdout")
    q.set_defaults(func=_cmd_query)

    sv = sub.add_parser("serve", help="run the HTTP sidecar (stdlib http.server)")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8771)
    sv.add_argument("--root", default="./.prefixforge", help="cache directory")
    sv.add_argument("--threshold", type=int, default=8)
    sv.add_argument("--mode", default="syntactic", choices=["syntactic", "semantic"])
    sv.set_defaults(func=_cmd_serve)

    pg = sub.add_parser("ping", help="health-check a running sidecar")
    pg.add_argument("--url", default="http://127.0.0.1:8771")
    pg.set_defaults(func=_cmd_ping)

    return p


def _cmd_serve(args):
    from .server import serve
    return serve(host=args.host, port=args.port, root=args.root,
                 threshold=args.threshold, mode=args.mode)


def _cmd_ping(args):
    from .server import PrefixClient
    try:
        ok = PrefixClient(args.url).healthz().get("ok") is True
    except Exception as exc:
        print("ping %s: DOWN (%s)" % (args.url, exc))
        return 1
    print("ping %s: %s" % (args.url, "OK" if ok else "BAD"))
    return 0 if ok else 1


def main(argv=None):
    # type: (Optional[List[str]]) -> int
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        # Zero-config: bare `prefixforge` runs the money-shot demo.
        return _cmd_demo(parser.parse_args(["demo"]))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

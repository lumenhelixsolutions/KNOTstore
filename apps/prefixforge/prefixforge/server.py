"""
A tiny stdlib HTTP sidecar for PrefixForge, so any process/language can use the
near-duplicate prompt cache over HTTP.

    prefixforge serve --port 8771 --root ./.prefixforge

Endpoints
---------
GET  /healthz                         -> {"ok": true}
GET  /cache?prompt=...                -> {"kind","similarity","tokens_saved","value"}
POST /cache  {"prompt","value"(b64),"tokens"}  -> {"stored": true}

``value`` is base64 so arbitrary KV-cache/completion blobs travel safely in JSON.
Stdlib only (``http.server`` + ``urllib``), Python 3.8+.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from prefixforge.cache import PrefixCache  # noqa: E402


def make_handler(cache: "PrefixCache"):
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "PrefixForge/0.2"

        def _send(self, code, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):  # quiet by default; log to stderr
            sys.stderr.write("[prefixforge] " + (fmt % args) + "\n")

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/healthz":
                return self._send(200, {"ok": True})
            if parsed.path == "/cache":
                qs = parse_qs(parsed.query)
                prompt = (qs.get("prompt") or [""])[0]
                if not prompt:
                    return self._send(400, {"error": "missing prompt"})
                with lock:
                    res = cache.get(prompt)
                return self._send(200, {
                    "kind": res.kind,
                    "similarity": res.similarity,
                    "tokens_saved": res.tokens_saved,
                    "value": base64.b64encode(res.value).decode() if res.value else None,
                })
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            if urlparse(self.path).path != "/cache":
                return self._send(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length) or b"{}")
                prompt = data["prompt"]
                value = base64.b64decode(data.get("value", "")) if data.get("value") else b""
                tokens = int(data.get("tokens", 0))
            except Exception as exc:  # malformed request
                return self._send(400, {"error": "bad request: %s" % exc})
            with lock:
                cache.put(prompt, value, tokens=tokens)
            return self._send(200, {"stored": True})

    return Handler


def serve(host="127.0.0.1", port=8771, root="./.prefixforge", threshold=8, mode="syntactic"):
    cache = PrefixCache(root=root, threshold=threshold, mode=mode, persist=True)
    httpd = ThreadingHTTPServer((host, port), make_handler(cache))
    sys.stderr.write("PrefixForge sidecar on http://%s:%d  (root=%s, mode=%s)\n"
                     % (host, port, os.path.abspath(root), mode))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\nshutting down\n")
    finally:
        httpd.server_close()
    return 0


class PrefixClient:
    """Minimal stdlib client for the sidecar."""

    def __init__(self, base_url="http://127.0.0.1:8771"):
        self.base = base_url.rstrip("/")

    def _req(self, method, path, body=None):
        import urllib.request
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    def healthz(self):
        return self._req("GET", "/healthz")

    def put(self, prompt, value: bytes, tokens=0):
        return self._req("POST", "/cache", {
            "prompt": prompt, "value": base64.b64encode(value).decode(), "tokens": tokens})

    def get(self, prompt):
        from urllib.parse import quote
        return self._req("GET", "/cache?prompt=" + quote(prompt))

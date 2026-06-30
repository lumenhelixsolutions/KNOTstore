from __future__ import annotations
import os, sys, socket, tempfile, shutil, threading, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from http.server import ThreadingHTTPServer
from prefixforge.cache import PrefixCache
from prefixforge.server import make_handler, PrefixClient

def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def _serve(cache):
    port = _free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(cache))
    t = threading.Thread(target=httpd.serve_forever, daemon=True); t.start()
    # wait until it answers
    cli = PrefixClient("http://127.0.0.1:%d" % port)
    for _ in range(50):
        try:
            if cli.healthz().get("ok"): break
        except Exception:
            time.sleep(0.02)
    return httpd, cli

def test_http_roundtrip():
    d = tempfile.mkdtemp()
    try:
        cache = PrefixCache(root=d, threshold=10, persist=True)
        httpd, cli = _serve(cache)
        try:
            assert cli.healthz()["ok"] is True
            cli.put("summarize the attached contract and list obligations",
                    b"CACHED-BLOB", tokens=120)
            # near-duplicate query should hit over HTTP
            r = cli.get("please summarize the attached contract and list the obligations")
            assert r["kind"] in ("exact", "near")
            assert r["tokens_saved"] == 120
            import base64
            assert base64.b64decode(r["value"]) == b"CACHED-BLOB"
            # unrelated -> miss
            assert cli.get("what time is lunch")["kind"] == "miss"
        finally:
            httpd.shutdown(); httpd.server_close()
    finally:
        shutil.rmtree(d)

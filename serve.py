#!/usr/bin/env python3
"""
serve.py — serves the long-context test console and proxies requests to any
OpenAI-compatible endpoint (browser pages can't call those directly due to CORS).

  GET  /            -> index.html (test console)
  GET  /report      -> report.html (last bench.py report, if any)
  GET  /results.json-> last bench.py results, if any
  GET  /corpus/all.txt  -> merged local corpus for the browser harness
  POST /proxy       -> {"base":"http://host:port/v1","path":"/chat/completions",
                        "apiKey":"...","payload":{...}}  (streams SSE back)
  GET  /fetch?url=  -> server-side download (for custom corpus URLs), max 16MB

Usage: python3 serve.py [--port 8899] [--host 127.0.0.1]
"""
import argparse, json, os, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request as urlreq
from urllib.parse import urlparse, parse_qs
from urllib.error import HTTPError, URLError

ROOT = os.path.dirname(os.path.abspath(__file__))

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):
        sys.stderr.write("[%s] %s\n" % (self.address_string(), fmt % a))

    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, str): body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            self._file(os.path.join(ROOT, "index.html"), "text/html; charset=utf-8")
        elif p == "/report":
            f = os.path.join(ROOT, "report.html")
            self._file(f, "text/html; charset=utf-8") if os.path.exists(f) \
                else self._send(404, '{"error":"no report.html yet — run bench.py"}')
        elif p == "/results.json":
            f = os.path.join(ROOT, "results.json")
            self._file(f, "application/json") if os.path.exists(f) \
                else self._send(404, '{"error":"no results yet"}')
        elif p == "/corpus/all.txt":
            f = os.path.join(ROOT, "corpus_all.txt")
            if not os.path.exists(f):
                merged, d = [], os.path.join(ROOT, "corpus")
                if os.path.isdir(d):
                    for fn in sorted(os.listdir(d)):
                        if fn.endswith(".txt"):
                            merged.append(open(os.path.join(d, fn), encoding="utf-8",
                                               errors="ignore").read())
                open(f, "w", encoding="utf-8").write("\n\n".join(merged))
            self._file(f, "text/plain; charset=utf-8")
        elif p == "/fetch":
            url = parse_qs(urlparse(self.path).query).get("url", [""])[0]
            if not url.startswith(("http://", "https://")):
                return self._send(400, '{"error":"url must be http(s)"}')
            try:
                req = urlreq.Request(url, headers={"User-Agent": "longctx-bench/1.0"})
                with urlreq.urlopen(req, timeout=120) as r:
                    data = r.read(16 * 1024 * 1024)
                self._send(200, data, "text/plain; charset=utf-8")
            except Exception as e:
                self._send(502, json.dumps({"error": str(e)}))
        else:
            self._send(404, '{"error":"not found"}')

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                self._send(200, f.read(), ctype)
        except OSError as e:
            self._send(500, json.dumps({"error": str(e)}))

    def do_POST(self):
        if urlparse(self.path).path != "/proxy":
            return self._send(404, '{"error":"not found"}')
        try:
            n = int(self.headers.get("Content-Length", 0))
            cfg = json.loads(self.rfile.read(n))
            base = cfg["base"].rstrip("/")
            if not base.startswith(("http://", "https://")):
                raise ValueError("bad base url")
            url = base + cfg.get("path", "/chat/completions")
            headers = {"Content-Type": "application/json",
                       "Accept": "text/event-stream, application/json"}
            if cfg.get("apiKey"):
                headers["Authorization"] = "Bearer " + cfg["apiKey"]
            req = urlreq.Request(url, data=json.dumps(cfg["payload"]).encode(),
                                 headers=headers)
            resp = urlreq.urlopen(req, timeout=1800)
        except HTTPError as e:
            body = e.read()[:8192]
            return self._send(e.code, body, "application/json")
        except Exception as e:
            return self._send(502, json.dumps({"error": str(e)}))
        # stream passthrough
        try:
            self.send_response(200)
            self.send_header("Content-Type",
                             resp.headers.get("Content-Type", "text/event-stream"))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            while True:
                chunk = resp.read(65536)
                if not chunk: break
                self.wfile.write(chunk); self.wfile.flush()
                if b"[DONE]" in chunk: break
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # browser navigated away / stopped
        finally:
            resp.close()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), H)
    print(f"console: http://{args.host}:{args.port}/   report: http://{args.host}:{args.port}/report")
    srv.serve_forever()

if __name__ == "__main__":
    main()

"""Serve the static build locally: http://localhost:8081/

Python's built-in server with the content types the page needs (wasm, ES modules, ONNX
as application/octet-stream, JSON) and no caching, so a rebuild shows up on reload.
localhost counts as a secure origin, so the live camera works without HTTPS.

    python -I tools/serve_static.py [--dir dist/static] [--port 8081]
"""
import argparse
import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".mjs": "text/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".wasm": "application/wasm",
        ".onnx": "application/octet-stream",
        ".md": "text/markdown; charset=utf-8",
    }

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(ROOT, "dist", "static"))
    ap.add_argument("--port", type=int, default=8081)
    args = ap.parse_args()
    if not os.path.isfile(os.path.join(args.dir, "index.html")):
        raise SystemExit(f"{args.dir} has no index.html; run tools/build_static.py first")
    server = ThreadingHTTPServer(("localhost", args.port), partial(Handler, directory=args.dir))
    print(f"Serving {args.dir} at http://localhost:{args.port}/  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

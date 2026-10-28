"""Deterministic image fixture for external FOXML datastream URLs."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGE = Path(__file__).with_name("page.jpg").read_bytes()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            body, mime = b"ok", "text/plain"
        elif self.path.startswith("/qg/") and self.path.endswith((".jpg", ".jpeg")):
            body, mime = PAGE, "image/jpeg"
        elif self.path.startswith("/qg/") and self.path.endswith("/info.json"):
            body = json.dumps(
                {
                    "@context": "http://iiif.io/api/image/2/context.json",
                    "width": 256,
                    "height": 256,
                    "profile": ["http://iiif.io/api/image/2/level1.json"],
                }
            ).encode()
            mime = "application/json"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()

"""Read-only progress dashboard.

`python3 -m orchestrator.driver serve --state PATH [--port 8765]` serves a
single-page app that polls /api/state and renders the pipeline. The web app
never mutates state; it is a viewer over the same JSON the CLI uses.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import driver
from . import state as st

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def load_summary(state_path, model_profiles_home=None):
    state = st.load(state_path)
    acts_path = os.path.join(os.path.dirname(os.path.abspath(state_path)),
                             "acts.json")
    try:
        with open(acts_path, "r", encoding="utf-8") as fh:
            acts = json.load(fh)
    except (OSError, ValueError):
        acts = {}
    current_review_model = None
    if model_profiles_home is not None:
        current_review_model = driver.resolve_current_review_model(
            state_path, model_profiles_home, run_state=state
        )
    return st.summary(
        state,
        acts_overlay=acts if isinstance(acts, dict) else {},
        current_review_model=current_review_model,
    )


def make_handler(state_path, model_profiles_home=None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._serve_index()
            elif self.path == "/api/state":
                self._serve_state()
            else:
                self.send_error(404)

        def _serve_index(self):
            path = os.path.join(STATIC_DIR, "index.html")
            try:
                with open(path, "rb") as fh:
                    body = fh.read()
            except OSError:
                self.send_error(500, "index.html missing")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_state(self):
            try:
                payload = {
                    "ok": True,
                    "summary": load_summary(
                        state_path, model_profiles_home=model_profiles_home
                    ),
                }
            except Exception as exc:  # viewer must never crash the server
                payload = {"ok": False, "error": str(exc)}
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):  # quiet
            pass

    return Handler


def serve(state_path, port=8765, model_profiles_home=None):
    server = ThreadingHTTPServer(
        ("127.0.0.1", port),
        make_handler(state_path, model_profiles_home=model_profiles_home),
    )
    print("orchestrator dashboard: http://127.0.0.1:%d  (state: %s)" % (port, state_path))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0

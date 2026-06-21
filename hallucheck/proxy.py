"""OpenAI-compatible guard proxy: inspect every completion before it's returned.

Point a harness's ``base_url`` at this proxy; it forwards
``/v1/chat/completions`` upstream, runs the guard over the assistant message,
attaches the result + a signed attestation under ``x_hallucheck``, and — with
``$PROXY_FAIL_CLOSED=1`` — replaces a failing message with a refusal. This is the
provider-agnostic injection point for harnesses without hooks. Reference
implementation: non-streaming (``stream:true`` is forwarded unverified).

    UPSTREAM_BASE_URL=https://api.example/v1 PROXY_FAIL_CLOSED=1 \\
        python3 -m hallucheck.proxy --adapter maine --port 8099
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import adapter as _adapter
from . import guard

UPSTREAM = os.environ.get("UPSTREAM_BASE_URL") or os.environ.get(
    "HALLUCHECK_BASE_URL", "http://127.0.0.1:8088/v1")
FAIL_CLOSED = os.environ.get("PROXY_FAIL_CLOSED") == "1"


def _message_text(body: dict) -> str:
    try:
        content = body["choices"][0]["message"]["content"]
    except Exception:
        return ""
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content or ""


def apply_guard(resp_body: dict, adapter, *, scope=None, fail_closed=FAIL_CLOSED,
                log_path=None, llm=False) -> dict:
    """Inspect a chat-completion response body in place and annotate it."""
    text = _message_text(resp_body)
    if not text.strip():
        return resp_body
    res = guard.evaluate(text, adapter, scope=scope, llm=llm, log_path=log_path)
    resp_body["x_hallucheck"] = {
        "blocked": bool(res["block"] and fail_closed),
        "flagged": bool(res["block"]),
        "reason": res["reason"],
        "scan": {k: res["scan"].get(k) for k in
                 ("leaked", "unresolvable", "fabricated_urls", "out_of_vocab")},
        "attestation": res.get("attestation"),
    }
    if res["block"] and fail_closed:
        try:
            resp_body["choices"][0]["message"]["content"] = (
                "[hallucination guard] This response was withheld pending review.\n"
                + res["reason"])
            resp_body["choices"][0]["finish_reason"] = "content_filter"
        except Exception:
            pass
    return resp_body


def make_handler(adapter, *, scope=None, llm=False):
    class _Handler(BaseHTTPRequestHandler):
        server_version = "hallucheck-proxy/1.0"

        def _send(self, code, body, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

        def do_POST(self):
            if not self.path.rstrip("/").endswith("/chat/completions"):
                return self._send(404, b'{"error":"only /v1/chat/completions"}')
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            try:
                req = json.loads(raw)
            except Exception:
                return self._send(400, b'{"error":"invalid JSON"}')
            fwd = urllib.request.Request(UPSTREAM.rstrip("/") + "/chat/completions",
                                         data=raw, method="POST",
                                         headers={"Content-Type": "application/json"})
            if self.headers.get("Authorization"):
                fwd.add_header("Authorization", self.headers["Authorization"])
            try:
                with urllib.request.urlopen(fwd, timeout=300) as r:
                    upstream = r.read()
            except Exception as e:
                return self._send(502, json.dumps({"error": f"upstream: {e}"}).encode())
            if req.get("stream"):
                return self._send(200, upstream)        # not inspected (reference)
            try:
                body = apply_guard(json.loads(upstream), adapter,
                                   scope=self.headers.get("X-Hallucheck-Scope") or scope,
                                   llm=llm)
                out = json.dumps(body, ensure_ascii=False).encode("utf-8")
            except Exception:
                out = upstream                          # fail open
            self._send(200, out)
    return _Handler


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--scope")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8099)
    a = ap.parse_args()
    adapter = _adapter.load(a.adapter)
    print(f"hallucheck proxy on http://{a.host}:{a.port}/v1 -> {UPSTREAM} "
          f"(adapter={a.adapter}, fail_closed={FAIL_CLOSED})", file=sys.stderr)
    ThreadingHTTPServer((a.host, a.port), make_handler(adapter, scope=a.scope, llm=a.llm)).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

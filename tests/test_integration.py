"""Integration tests for every connection method: the `hallucheck` CLI, the
Claude Code Stop hook, the OpenAI-compatible guard proxy (real HTTP, stub
upstream), and the in-process guard API."""
import json
import pathlib
import subprocess
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]


def run(args, *, stdin="", env=None):
    return subprocess.run([sys.executable, "-m", *args], cwd=REPO, input=stdin,
                          capture_output=True, text=True, env=env)


# --------------------------------------------------------------------------- CLI
def test_cli_emit_prompt_lists_only_allowed_keys():
    r = run(["hallucheck.cli", "emit-prompt", "--adapter", "maine", "--scope", "DE-101"])
    assert r.returncode == 0
    assert "[[REF: 18-C §3-401]]" in r.stdout
    assert "9-306" not in r.stdout                 # out-of-scope key not offered


@pytest.mark.parametrize("text,code", [
    ("Clean prose with no citations at all.", 0),
    ("Relief is required, see 18-C §9-999 and https://example.com/x.", 1),
])
def test_cli_scan_exit_codes(text, code):
    r = run(["hallucheck.cli", "scan", "--adapter", "maine"], stdin=text)
    assert r.returncode == code, r.stdout + r.stderr


def test_cli_attest_then_verify_log(tmp_path):
    import os
    env = {**os.environ, "ATTEST_HMAC_KEY": "operator-secret"}
    draft = tmp_path / "d.txt"
    draft.write_text("Relief under 18-C §9-999.")          # fabricated -> needs review
    log = tmp_path / "log.jsonl"
    ins = run(["hallucheck.cli", "scan", "--adapter", "maine"], stdin="ok")  # warm import
    assert ins.returncode == 0
    # write a receipt to the log via the python API path, then verify with the CLI
    rec = run(["hallucheck.cli", "inspect", "--adapter", "maine", "--scope", "DE-101",
               "--draft", str(draft), "--log", str(log)], env=env)
    assert log.exists() and rec.returncode == 1            # needs review (fabricated cite)
    ver = run(["hallucheck.cli", "verify-log", str(log)], env=env)
    assert ver.returncode == 0 and "intact" in ver.stdout
    # wrong key fails verification
    bad = run(["hallucheck.cli", "verify-log", str(log)],
              env={**os.environ, "ATTEST_HMAC_KEY": "wrong"})
    assert bad.returncode == 1


# -------------------------------------------------------------- Claude Code hook
def _transcript(tmp_path, text):
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps({"type": "assistant", "message": {
        "role": "assistant", "content": [{"type": "text", "text": text}]}}) + "\n")
    return p


def test_hook_blocks_on_fabricated_cite(tmp_path):
    t = _transcript(tmp_path, "The rule is clear under 18-C §9-999.")
    r = run(["hallucheck.hooks.claude_code", "--adapter", "maine"],
            stdin=json.dumps({"transcript_path": str(t)}))
    assert r.returncode == 0
    assert json.loads(r.stdout)["decision"] == "block"


def test_hook_allows_clean_turn(tmp_path):
    t = _transcript(tmp_path, "I drafted the petition; please review it.")
    r = run(["hallucheck.hooks.claude_code", "--adapter", "maine"],
            stdin=json.dumps({"transcript_path": str(t)}))
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_hook_fails_open_on_garbage_stdin():
    r = run(["hallucheck.hooks.claude_code", "--adapter", "maine"], stdin="not json")
    assert r.returncode == 0 and r.stdout.strip() == ""


# ------------------------------------------------------- OpenAI-compatible proxy
def _serve(handler_cls):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def _upstream_returning(content):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            body = json.dumps({"id": "x", "object": "chat.completion",
                               "choices": [{"index": 0, "finish_reason": "stop",
                                            "message": {"role": "assistant",
                                                        "content": content}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    return H


def _post(port, payload):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
                                 data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def test_proxy_fail_closed_replaces_bad_completion(monkeypatch):
    from adapters.maine.adapter import MaineProbateAdapter
    from hallucheck import proxy
    up, up_port = _serve(_upstream_returning(
        "You win under 18-C §9-999, see https://example.com/ruling."))
    monkeypatch.setattr(proxy, "UPSTREAM", f"http://127.0.0.1:{up_port}/v1")
    monkeypatch.setattr(proxy, "FAIL_CLOSED", True)
    px, px_port = _serve(proxy.make_handler(MaineProbateAdapter()))
    try:
        body = _post(px_port, {"model": "m", "messages": [{"role": "user", "content": "hi"}]})
    finally:
        up.shutdown(); px.shutdown()
    assert body["x_hallucheck"]["flagged"] is True
    assert body["x_hallucheck"]["blocked"] is True
    assert "withheld" in body["choices"][0]["message"]["content"]
    assert body["choices"][0]["finish_reason"] == "content_filter"
    assert body["x_hallucheck"]["attestation"]["receipt"]["needs_review"] is True


def test_proxy_passes_clean_completion(monkeypatch):
    from adapters.maine.adapter import MaineProbateAdapter
    from hallucheck import proxy
    up, up_port = _serve(_upstream_returning("I prepared the petition for your review."))
    monkeypatch.setattr(proxy, "UPSTREAM", f"http://127.0.0.1:{up_port}/v1")
    monkeypatch.setattr(proxy, "FAIL_CLOSED", True)
    px, px_port = _serve(proxy.make_handler(MaineProbateAdapter()))
    try:
        body = _post(px_port, {"model": "m", "messages": [{"role": "user", "content": "hi"}]})
    finally:
        up.shutdown(); px.shutdown()
    assert body["x_hallucheck"]["flagged"] is False
    assert body["choices"][0]["message"]["content"].startswith("I prepared")


def test_proxy_streaming_is_passthrough_documented_gap(monkeypatch):
    # Known limitation: stream:true is forwarded unverified (no x_hallucheck).
    from adapters.maine.adapter import MaineProbateAdapter
    from hallucheck import proxy
    up, up_port = _serve(_upstream_returning("streamed 18-C §9-999"))
    monkeypatch.setattr(proxy, "UPSTREAM", f"http://127.0.0.1:{up_port}/v1")
    px, px_port = _serve(proxy.make_handler(MaineProbateAdapter()))
    try:
        body = _post(px_port, {"model": "m", "stream": True,
                               "messages": [{"role": "user", "content": "hi"}]})
    finally:
        up.shutdown(); px.shutdown()
    assert "x_hallucheck" not in body


# ------------------------------------------------------------------- guard API
def test_guard_api_require_protocol_toggle():
    from adapters.maine.adapter import MaineProbateAdapter
    from hallucheck import guard
    A = MaineProbateAdapter()
    bare = "The court applies 18-C §3-401 here."
    assert guard.evaluate(bare, A, scope="DE-101", attest=False)["block"] is True
    assert guard.evaluate(bare, A, scope="DE-101", attest=False,
                          require_protocol=False)["block"] is False

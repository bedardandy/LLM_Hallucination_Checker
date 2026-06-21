"""Claude Code Stop hook: block a turn that cites sources badly, and attest it.

Wire it in ``.claude/settings.json``:

    {"hooks": {"Stop": [{"hooks": [{"type": "command",
       "command": "python3 -m hallucheck.hooks.claude_code --adapter maine"}]}]}}

Reads the hook JSON on stdin, pulls the last assistant message out of the
transcript, runs the deterministic guard (offline), and on a finding emits
``{"decision":"block","reason":...}`` so Claude Code feeds the problem back. Every
check is attested to ``$ATTEST_LOG``. Set ``--scope``/``$HALLUCHECK_SCOPE`` to
scope the vocabulary, ``--llm`` to also run the inspector. Fails open. Use
``--text -`` to test without a transcript.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

from .. import adapter as _adapter
from .. import guard


def _last_assistant_text(transcript_path: str) -> str:
    try:
        lines = [ln for ln in pathlib.Path(transcript_path).read_text(
            encoding="utf-8").splitlines() if ln.strip()]
    except Exception:
        return ""
    for ln in reversed(lines):
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        msg = ev.get("message", ev)
        if (msg.get("role") or ev.get("type")) != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [b.get("text", "") for b in content
                     if isinstance(b, dict) and b.get("type") == "text"]
            if any(parts):
                return "\n".join(p for p in parts if p)
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--scope", default=os.environ.get("HALLUCHECK_SCOPE"))
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--text", help="inspect this text (or '-' for stdin) instead of a transcript")
    a = ap.parse_args()

    if a.text is not None:
        text = sys.stdin.read() if a.text == "-" else a.text
    else:
        try:
            payload = json.load(sys.stdin)
        except Exception:
            return 0                                   # fail open
        text = _last_assistant_text(payload.get("transcript_path", ""))
    if not (text or "").strip():
        return 0

    try:
        adapter = _adapter.load(a.adapter)
        res = guard.evaluate(text, adapter, scope=a.scope, llm=a.llm)
    except Exception as e:
        print(f"hallucheck hook: internal error, allowing ({type(e).__name__}: {e})",
              file=sys.stderr)
        return 0

    if res["block"]:
        print(json.dumps({"decision": "block", "reason": res["reason"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

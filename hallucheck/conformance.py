"""Adapter conformance kit — prove an adapter satisfies the :class:`Adapter`
contract.

A new corpus adapter is only useful if the engine, scanner, guards and packet
builder can rely on its shapes. :func:`check` exercises the protocol against a
live adapter instance and returns a list of human-readable problems (empty ==
conforms); :func:`assert_conforms` turns that into a one-line pytest assertion an
adapter author drops into their suite:

    from hallucheck import conformance
    def test_conformance():
        conformance.assert_conforms(MyAdapter(), sample_text="...see 1 A.2d 2...",
                                    resolves_cites=["1 A.2d 2"], in_scope="...")

Every method is called defensively: a method that raises is reported as a failure
rather than crashing the run. Checks are structural (shapes/contracts), not
semantic — they don't judge whether the corpus data is *correct*.
"""
from __future__ import annotations

from .adapter import Adapter


def _check_hit(h, n: int, problems: list) -> None:
    if not isinstance(h, dict):
        problems.append(f"citation hit is not a dict: {h!r}")
        return
    for k in ("raw", "cite", "kind", "span", "resolves"):
        if k not in h:
            problems.append(f"citation hit missing '{k}': {h!r}")
    span = h.get("span")
    if not (isinstance(span, (list, tuple)) and len(span) == 2
            and all(isinstance(x, int) for x in span)):
        problems.append(f"citation hit 'span' must be [int, int]: {span!r}")
    elif not (0 <= span[0] <= span[1] <= n):
        problems.append(f"citation hit 'span' out of bounds 0..{n}: {span!r}")
    if "resolves" in h and not isinstance(h["resolves"], bool):
        problems.append(f"citation hit 'resolves' must be a bool: {h.get('resolves')!r}")
    if not isinstance(h.get("cite"), str):
        problems.append(f"citation hit 'cite' must be a str: {h.get('cite')!r}")


def check(adapter, *, sample_text: str = "", resolves_cites=(), in_scope=None) -> list[str]:
    """Run the conformance battery against ``adapter``. Returns a list of problems
    (empty == conforms). ``sample_text`` should contain a few citations the adapter
    recognizes; ``resolves_cites`` are cites expected to resolve (offline, via
    ``fetch_text=False``); ``in_scope`` is a scope value to exercise."""
    P: list[str] = []

    def cap(label, fn):
        try:
            return fn()
        except Exception as e:                       # a method that raises = a failure
            P.append(f"{label} raised {type(e).__name__}: {e}")
            return None

    name = getattr(adapter, "name", None)
    if not isinstance(name, str) or not name:
        P.append("adapter.name must be a non-empty str")
    disc = getattr(adapter, "disclaimer", None)
    if not isinstance(disc, str) or not disc:
        P.append("adapter.disclaimer must be a non-empty str")
    if not isinstance(adapter, Adapter):
        P.append("adapter does not satisfy the Adapter protocol (missing methods)")
        return P                                     # further checks would just crash

    vocab = cap("build_vocabulary(None)", lambda: adapter.build_vocabulary(None))
    if vocab is not None:
        if not isinstance(vocab, dict):
            P.append("build_vocabulary must return a dict")
        else:
            for k, v in list(vocab.items())[:100]:
                if not isinstance(k, str):
                    P.append(f"vocabulary key is not a str: {k!r}")
                if not isinstance(v, dict) or "cite" not in v:
                    P.append(f"vocabulary value for {k!r} must be a dict with 'cite'")

    for txt, label in (("", "empty"), (sample_text, "sample")):
        hits = cap(f"citation_spans({label})", lambda t=txt: adapter.citation_spans(t))
        if hits is None:
            continue
        if not isinstance(hits, list):
            P.append(f"citation_spans({label}) must return a list")
        else:
            for h in hits:
                _check_hit(h, len(txt), P)

    if sample_text:
        h1 = cap("citation_spans (determinism #1)", lambda: adapter.citation_spans(sample_text))
        h2 = cap("citation_spans (determinism #2)", lambda: adapter.citation_spans(sample_text))
        if h1 is not None and h1 != h2:
            P.append("citation_spans is not deterministic for identical input")

    if in_scope is not None:
        hs = cap("citation_spans(scope=...)",
                 lambda: adapter.citation_spans(sample_text, scope=in_scope))
        for h in hs or []:
            if isinstance(h, dict) and "in_vocab" not in h:
                P.append("citation_spans(scope=...) hits must include 'in_vocab'")
                break

    unknown = cap("resolve(unknown)",
                  lambda: adapter.resolve("ZZ-not-a-real-key-9999", fetch_text=False))
    if unknown is not None and not isinstance(unknown, dict):
        P.append("resolve(unknown key) must return None or a dict")
    for cite in resolves_cites:
        r = cap(f"resolve({cite!r})", lambda c=cite: adapter.resolve(c, fetch_text=False))
        if not isinstance(r, dict):
            P.append(f"resolve({cite!r}) expected a dict, got {type(r).__name__}")
        else:
            if "cite" not in r:
                P.append(f"resolve({cite!r}) result missing 'cite'")
            if not isinstance(r.get("text"), str) or not r.get("text"):
                P.append(f"resolve({cite!r}) must include non-empty 'text'")

    u = cap("url_in_index(...)", lambda: adapter.url_in_index("https://example.invalid/zzz"))
    if u not in (True, False, None):
        P.append("url_in_index must return True, False, or None")

    iu = cap("index_urls()", lambda: adapter.index_urls())
    if iu is not None:
        if not isinstance(iu, dict):
            P.append("index_urls must return a dict")
        else:
            for k, v in iu.items():
                if not isinstance(k, str) or not isinstance(v, (list, tuple)):
                    P.append("index_urls must map url(str) -> list of cites")
                    break

    cd = cap("config_digest()", lambda: adapter.config_digest())
    if cd is not None and not isinstance(cd, str):
        P.append("config_digest must return a str")

    return P


def assert_conforms(adapter, **kw) -> None:
    """pytest one-liner: assert ``adapter`` conforms, with a readable failure."""
    problems = check(adapter, **kw)
    assert not problems, ("Adapter conformance failures for "
                          f"{getattr(adapter, 'name', adapter)!r}:\n  - "
                          + "\n  - ".join(problems))

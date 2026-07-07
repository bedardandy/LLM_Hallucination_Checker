"""Guard fail-closed behavior — the blocking gate shared by the Stop hook and the
proxy. Focus: a cite that is *in vocabulary* but whose authority source can't be
fetched (403/timeout) must BLOCK, not pass. This is the asymmetry the audit found:
``attest.needs_review`` counts ``unresolved`` while the gate did not."""
from hallucheck import attest, guard


class _StubAdapter:
    """Minimal adapter: one in-vocab key whose source fetch fails (returns None),
    so the inspector marks it ``unresolved`` and never inspects it. No network,
    no LLM (a draft with only an unresolved cite has nothing to inspect)."""

    name = "stub"

    def __init__(self, *, resolve_returns=None, raise_on_resolve=False):
        self._resolve_returns = resolve_returns
        self._raise = raise_on_resolve

    def build_vocabulary(self, scope=None):
        return {"1 U.S. 1": {"kind": "case", "cite": "1 U.S. 1"}}

    def resolve(self, key, *, fetch_text=True):
        if self._raise:
            raise TimeoutError("simulated 403/timeout on source fetch")
        return self._resolve_returns

    def citation_spans(self, text, *, scope=None):
        return []

    def url_in_index(self, url):
        return None

    def config_digest(self):
        return "stub/v1"


DRAFT = "The controlling authority is [[REF: 1 U.S. 1]] on this point."


def test_guard_blocks_when_source_fetch_raises():
    """403/timeout during fetch -> unresolved -> must block (fail-closed)."""
    adapter = _StubAdapter(raise_on_resolve=True)
    res = guard.evaluate(DRAFT, adapter, scope="seed", llm=True, attest=False)
    assert res["block"] is True
    assert "unverified" in res["reason"]
    assert "1 U.S. 1" in res["reason"]


def test_guard_blocks_when_source_returns_no_text():
    """Fetch returns a record with no text -> unresolved -> must block."""
    adapter = _StubAdapter(resolve_returns={"cite": "1 U.S. 1", "title": "X"})
    res = guard.evaluate(DRAFT, adapter, scope="seed", llm=True, attest=False)
    assert res["block"] is True
    assert "1 U.S. 1" in res["reason"]


def test_guard_unresolved_block_agrees_with_needs_review():
    """The gate must agree with attest.needs_review on the same result."""
    adapter = _StubAdapter(raise_on_resolve=True)
    out = guard.evaluate(DRAFT, adapter, scope="seed", llm=True, attest=True)
    assert out["block"] is True
    assert out["attestation"]["receipt"]["needs_review"] is True


def test_guard_offline_unresolved_absent_does_not_falsely_block():
    """Offline (llm=False) has no inspector 'unresolved' concept; a clean draft
    with no citation spans must not block (fail-closed only where warranted)."""
    adapter = _StubAdapter(raise_on_resolve=True)
    res = guard.evaluate("Plain prose, no citations.", adapter, attest=False)
    assert res["block"] is False


def test_needs_review_counts_unresolved_directly():
    """Sanity: the attest side counts unresolved, so the gate must too."""
    assert attest.needs_review({"unresolved": ["1 U.S. 1"], "ok": True}) is True

"""Deterministic detection benchmark over the Maine adapter."""
from adapters.maine.adapter import MaineProbateAdapter
from hallucheck import benchmark


def test_bundled_dataset_is_perfectly_detected():
    rep = benchmark.score(MaineProbateAdapter())
    o = rep["overall"]
    assert rep["n_cases"] == len(benchmark.DATASET)
    assert o["fp"] == 0 and o["fn"] == 0          # scanner catches all, invents none
    assert o["precision"] == 1.0 and o["recall"] == 1.0 and o["f1"] == 1.0
    for c in rep["cases"]:
        assert not c["missed"] and not c["spurious"], c


def test_scoring_math_on_a_deliberate_miss():
    # A gold label the scanner cannot satisfy (a non-citation string) -> recall < 1.
    custom = [{"name": "impossible", "draft": "nothing citationy here", "scope": None,
               "expect": {"leaked": ["18-C §1-234"]}}]
    rep = benchmark.score(MaineProbateAdapter(), custom)
    assert rep["overall"]["fn"] == 1
    assert rep["overall"]["recall"] == 0.0
    assert rep["cases"][0]["missed"] == [("leaked", "18-C §1-234")]

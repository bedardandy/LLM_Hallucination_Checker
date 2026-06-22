"""Caselaw cross-check logic (offline: injected lookup)."""
from hallucheck import caseaudit


def test_consistent_case_has_no_issues():
    case = {"name": "Estate of Bonin", "cite": "457 A.2d 1123", "year": 1983}
    res = {"found": True, "case_name": "Estate of Bonin", "date": "1983-04-05",
           "citations": ["457 A.2d 1123", "1983 Me. LEXIS 667"]}
    assert caseaudit.audit_case(case, res) == []


def test_name_case_difference_tolerated():
    case = {"name": "In re Estate of Kruzynski", "cite": "2000 ME 17", "year": 2000}
    res = {"found": True, "case_name": "In Re Estate of Kruzynski",
           "date": "2000-02-03", "citations": ["2000 ME 17"]}
    assert caseaudit.audit_case(case, res) == []      # "In re" vs "In Re" is fine


def test_not_found_flagged():
    assert caseaudit.audit_case({"cite": "9 ZZ 9"}, {"found": False}) == \
        ["did not resolve in CourtListener"]


def test_year_and_citation_and_name_mismatches():
    case = {"name": "Estate of Smith", "cite": "1 A.2d 1", "year": 1990}
    res = {"found": True, "case_name": "Jones v. Acme", "date": "1995-01-01",
           "citations": ["2 A.2d 2"]}
    issues = caseaudit.audit_case(case, res)
    assert any("citation" in i for i in issues)
    assert any("year mismatch" in i for i in issues)
    assert any("name differs" in i for i in issues)


def test_audit_cases_aggregates():
    cases = {"a": {"name": "Estate of Bonin", "cite": "457 A.2d 1123", "year": 1983},
             "b": {"name": "Nope", "cite": "9 ZZ 9", "year": 2000}}

    def lookup(cite, *, token=None):
        if cite == "457 A.2d 1123":
            return {"found": True, "case_name": "Estate of Bonin", "date": "1983-04-05",
                    "citations": ["457 A.2d 1123"]}
        return {"found": False}

    rep = caseaudit.audit_cases(cases, lookup=lookup)
    assert rep["total"] == 2 and rep["with_issues"] == 1
    assert {r["id"] for r in rep["rows"] if not r["issues"]} == {"a"}

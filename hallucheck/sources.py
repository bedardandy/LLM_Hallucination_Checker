"""Citation -> source links across free, subscription, and bar-membership services.

Corpus-agnostic. Given a *citation record* (the ``{cite, kind, title/name, url,
...}`` shape an adapter already produces in ``build_vocabulary`` / ``resolve``),
assemble the links an attorney needs to read the authority **and to prove the
cited text actually exists** — the official source, free aggregators (Google
Scholar, CourtListener), a web-archive snapshot, plus clearly-labeled
subscription / bar-member portals (Westlaw, Lexis, Fastcase·vLex via Maine / New
Hampshire / Massachusetts bar membership; many Maine attorneys hold all three).

In keeping with the rest of this project, it **never fabricates a deep link it
cannot construct from a known, stable URL pattern**. Free links are real URLs
(an official source URL the adapter vouches for, a search query, a reporter
redirect, an archive snapshot). Subscription / bar entries carry the service's
real landing page plus the citation to paste and ``requires_login: True`` — never
a guessed document URL. Following a link and confirming the authority is current
good law remains the attorney's job.
"""
from __future__ import annotations

import re
from urllib.parse import quote, quote_plus

# Access tiers, surfaced on every link so callers can filter / label.
FREE, OFFICIAL, SUBSCRIPTION, BAR, ARCHIVE = (
    "free", "official", "subscription", "bar", "archive")

# Traditional reporter cites we can turn into a CourtListener citation redirect
# (https://www.courtlistener.com/c/<reporter>/<vol>/<page>/ is a stable endpoint).
_REPORTER_CITE = re.compile(
    r"\b(\d+)\s+(A\.?\s?2d|A\.?\s?3d|U\.?\s?S\.?|S\.?\s?Ct\.?|"
    r"F\.?\s?2d|F\.?\s?3d|F\.?\s?Supp\.?\s?\d?d?|L\.?\s?Ed\.?\s?2d)\s+(\d+)\b",
    re.IGNORECASE)
# Vendor-neutral cites (e.g. "2000 ME 17", "2014 ME 2").
_NEUTRAL_CITE = re.compile(r"\b(\d{4})\s+([A-Z]{2,4})\s+(\d+)\b")

_REPORTER_SLUG = {
    "a2d": "A.2d", "a3d": "A.3d", "us": "U.S.", "sct": "S. Ct.",
    "f2d": "F.2d", "f3d": "F.3d", "led2d": "L. Ed. 2d",
}

# Subscription research services. Real landing pages; the citation is pasted in
# after login — we do not invent document URLs.
SUBSCRIPTION_PORTALS = (
    {"provider": "westlaw", "label": "Westlaw",
     "portal_url": "https://1.next.westlaw.com",
     "note": "Subscription. Paste the citation into the search bar after login."},
    {"provider": "lexis", "label": "Lexis+",
     "portal_url": "https://advance.lexis.com",
     "note": "Subscription. Paste the citation into the search bar after login."},
)

# Bar-membership research benefits. Many Maine attorneys are also admitted in NH
# and MA; each bar's member portal includes a primary-law research service
# (Fastcase / vLex historically). Real bar landing pages, not deep links.
BAR_PORTALS = (
    {"provider": "msba_fastcase", "label": "Maine State Bar Association (Fastcase·vLex)",
     "portal_url": "https://www.mainebar.org",
     "note": "Member benefit: primary-law research (Fastcase/vLex). Log in to the "
             "MSBA member area, open the legal-research benefit, and search the citation."},
    {"provider": "nhba_research", "label": "New Hampshire Bar Association",
     "portal_url": "https://www.nhbar.org",
     "note": "Member benefit: Fastcase/Casemaker-style legal research via the NHBA "
             "member area. (Many Maine attorneys are also admitted in NH.)"},
    {"provider": "mass_bar_research", "label": "Massachusetts Bar Association",
     "portal_url": "https://www.massbar.org",
     "note": "Member benefit: legal research via the MBA member area. (Many Maine "
             "attorneys are also admitted in MA.)"},
    {"provider": "fastcase_vlex", "label": "Fastcase · vLex (direct)",
     "portal_url": "https://www.fastcase.com",
     "note": "Access is typically granted through a state-bar membership; log in "
             "via your bar's portal, then search the citation."},
)


def _q(s: str) -> str:
    return quote_plus((s or "").strip())


def reporter_redirect(cite: str) -> str | None:
    """CourtListener citation redirect for a recognized reporter cite, else None."""
    m = _REPORTER_CITE.search(cite or "")
    if not m:
        return None
    vol, reporter, page = m.group(1), m.group(2), m.group(3)
    slug = _REPORTER_SLUG.get(re.sub(r"[^a-z0-9]", "", reporter.lower()))
    if not slug:
        return None
    return (f"https://www.courtlistener.com/c/{quote(slug)}/"
            f"{vol}/{page}/")


def wayback(url: str | None) -> dict | None:
    """View + on-demand-save links for a source URL via the Internet Archive.

    The *save* link lets an attorney capture a timestamped snapshot — durable
    proof that the cited text existed and read as quoted on a given date."""
    if not url:
        return None
    return {
        "provider": "wayback", "label": "Internet Archive (snapshot)",
        "access": ARCHIVE,
        "view_url": "https://web.archive.org/web/*/" + url,
        "save_url": "https://web.archive.org/save/" + url,
        "note": "Open 'save' to capture a timestamped snapshot proving the text "
                "existed as cited.",
    }


def for_citation(rec: dict) -> dict:
    """Assemble source links for one citation record.

    ``rec`` uses the adapter shape: ``{cite, kind, title|name, url, ...}``.
    Returns ``{cite, kind, links, portals, snapshot}`` where ``links`` are real,
    followable URLs (free/official/archive) and ``portals`` are subscription /
    bar entries carrying a landing page + the citation to paste (requires_login).
    """
    cite = (rec.get("cite") or "").strip()
    kind = rec.get("kind") or ("case" if _NEUTRAL_CITE.search(cite)
                               or _REPORTER_CITE.search(cite) else "statute")
    name = rec.get("name") or rec.get("title") or ""
    url = rec.get("url")
    is_case = kind == "case"

    links: list[dict] = []
    if url:
        links.append({"provider": "official", "label": "Official / primary source",
                      "access": OFFICIAL, "url": url})

    # A descriptive query: name + cite reads better for cases; cite for statutes.
    query = f'{name} {cite}'.strip() if (is_case and name) else cite

    if is_case:
        links.append({"provider": "google_scholar", "label": "Google Scholar (case law)",
                      "access": FREE,
                      "url": f"https://scholar.google.com/scholar?q={_q(query)}&as_sdt=4"})
        deep = reporter_redirect(cite)
        if deep:
            links.append({"provider": "courtlistener", "label": "CourtListener (citation)",
                          "access": FREE, "url": deep})
        links.append({"provider": "courtlistener_search", "label": "CourtListener (search)",
                      "access": FREE,
                      "url": f"https://www.courtlistener.com/?q={_q(query)}"})

    # A plain web search works for both statutes and cases and never fabricates.
    links.append({"provider": "google_web", "label": "Web search",
                  "access": FREE, "url": f"https://www.google.com/search?q={_q(query)}"})

    snap = wayback(url)
    if snap:
        links.append(snap)

    portals = [{**p, "access": SUBSCRIPTION, "requires_login": True, "query": cite}
               for p in SUBSCRIPTION_PORTALS]
    portals += [{**p, "access": BAR, "requires_login": True, "query": cite}
                for p in BAR_PORTALS]

    return {"cite": cite, "kind": kind, "links": links, "portals": portals,
            "snapshot": snap}

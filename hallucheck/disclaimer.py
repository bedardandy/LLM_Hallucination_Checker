"""Disclaimers stamped onto everything this library produces.

The whole point of the project is to make AI output *checkable*, not *trusted*.
Every generated artifact (verification packet, research memo, DOCX/PDF appendix)
carries the library disclaimer below, and — when an adapter supplies one — its
corpus disclaimer too. Keep this text blunt: it is the last line of defense
between a model's confident prose and a filing.
"""
from __future__ import annotations

LIBRARY_DISCLAIMER = (
    "EXPERIMENTAL SOFTWARE — NOT LEGAL ADVICE. This tool helps surface and "
    "organize citations for human review; it does not verify that any authority "
    "is correctly characterized, currently in force, or still good law. Treat "
    "every result as unverified until a licensed attorney has read each cited "
    "source in full and confirmed it supports the proposition for which it is "
    "cited. AI/LLM-generated content can be wrong, out of date, or fabricated. "
    "Use extreme caution before relying on this in any production or "
    "client-facing system, and never file or rely on output that a licensed "
    "attorney has not independently reviewed."
)

# Short one-liner for footers, page headers, and CLI banners.
SHORT_DISCLAIMER = (
    "Experimental — not legal advice. Every citation must be independently "
    "reviewed by a licensed attorney before any reliance."
)

REVIEW_REMINDER = (
    "Attorney review required: confirm each authority exists, says what it is "
    "cited for, and remains good law (check subsequent history / negative "
    "treatment). This tool cannot determine negative treatment."
)


def combined(adapter_disclaimer: str | None = None) -> str:
    """Library disclaimer, plus the adapter's corpus disclaimer when present."""
    parts = [LIBRARY_DISCLAIMER]
    if adapter_disclaimer:
        parts.append("CORPUS: " + adapter_disclaimer.strip())
    parts.append(REVIEW_REMINDER)
    return "\n\n".join(parts)

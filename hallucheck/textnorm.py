"""Text normalization to defeat homoglyph / invisible-character citation evasion.

LLM output (or a copy-paste attacker) can hide a fabricated citation from a regex
scanner with characters that *look* like ASCII but aren't: a non-breaking hyphen
in ``18‑C §9‑999``, a zero-width space inside ``§9-9{ZWSP}99``, a no-break space,
or a bidi control. :func:`clean` folds the common hyphen/space lookalikes to ASCII
and strips zero-width / bidi controls, so the downstream patterns see canonical
text. Applied once at the top of the scan so all spans stay mutually consistent.
"""
from __future__ import annotations

# Deleted outright (never legitimately inside a citation): zero-width + bidi.
_DELETE = {cp: None for cp in (
    0x200B, 0x200C, 0x200D, 0xFEFF, 0x2060,           # zero-width space/joiner/BOM/word-joiner
    0x200E, 0x200F, 0x061C,                            # LRM / RLM / ALM
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E,            # bidi embeddings/overrides
    0x2066, 0x2067, 0x2068, 0x2069,                    # bidi isolates
    0x00AD,                                            # soft hyphen
)}

# Folded to an ASCII equivalent (kept, so this stays close to length-stable).
_FOLD = {
    0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2212: "-",  # hyphen/minus variants
    0x00A0: " ", 0x2007: " ", 0x2008: " ", 0x2009: " ", 0x200A: " ",  # nbsp/figure/thin/hair
    0x202F: " ", 0x205F: " ", 0x3000: " ",                            # narrow-nbsp/math/ideographic
    0xFF03: "#", 0xFE6B: "@",
}
_TABLE = {**_DELETE, **_FOLD}


def clean(text: str) -> str:
    """Fold hyphen/space homoglyphs to ASCII and strip zero-width/bidi controls.
    Idempotent: ``clean(clean(t)) == clean(t)``."""
    return (text or "").translate(_TABLE)

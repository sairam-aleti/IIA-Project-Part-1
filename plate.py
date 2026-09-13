"""
Plate canonicalisation
======================
The five source databases were designed in isolation and each records the
registration mark in its own house format:

    rto        DL-3C-AB-1234      hyphen separated
    insurance  DL 3C AB 1234      space separated, sometimes lower case
    police     DL3CAB1234         compact
    camera     DL3CAB1234         compact, sometimes with stray whitespace
    mot        DL3CAB1234         compact

Part A resolves *format* heterogeneity deterministically: separators, case and
padding are stripped to yield one canonical mark. Two raw strings that reduce to
the same canonical mark are the same vehicle, with certainty.

Part A deliberately does NOT resolve *character* corruption from the ANPR
cameras (O read as 0, B read as 8, and so on). Those reads simply fail to link
and become INSUFFICIENT_EVIDENCE, which is the honest Part A answer.
`confusable_key` below is the hook Part B will use to generate candidate
matches with probabilities instead of abstaining.
"""

import re

# Characters that different agencies use as separators, plus the Unicode
# variants that turn up when data is pasted out of spreadsheets and PDFs.
_SEPARATORS = re.compile(r"[\s\-\u2010-\u2015_./,:;|]+")
_NON_ALNUM = re.compile(r"[^A-Z0-9]")

# An Indian registration mark: state code, district code, series, number.
#   DL3CAB1234   MH12AB1234   WB06A1234   KA01AA0001
_WELLFORMED = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$")

# Glyph pairs the ANPR stack confuses. Part B territory; declared here so the
# two phases share one definition of what "nearly the same plate" means.
_CONFUSABLES = {
    "0": "O", "O": "O",
    "1": "I", "I": "I",
    "5": "S", "S": "S",
    "8": "B", "B": "B",
    "2": "Z", "Z": "Z",
    "6": "G", "G": "G",
    "4": "A", "A": "A",
}


def canonical(raw):
    """
    Reduce any source's raw registration string to the canonical mark.

    Returns None for input that cannot represent a plate at all, so callers can
    distinguish "no value" from "a value I could not use".

    >>> canonical("  dl-3c ab 1234 ")
    'DL3CAB1234'
    >>> canonical("DL 3C AB 1234") == canonical("DL-3C-AB-1234")
    True
    """
    if raw is None:
        return None
    text = str(raw).strip().upper()
    if not text:
        return None
    text = _SEPARATORS.sub("", text)
    text = _NON_ALNUM.sub("", text)
    return text or None


def is_wellformed(mark):
    """True if the canonical mark matches the national plate grammar."""
    return bool(mark) and bool(_WELLFORMED.match(mark))


def confusable_key(mark):
    """
    Collapse OCR-confusable glyphs onto one representative character.

    Part A does not use this for linking — it is the blocking key Part B will
    use to propose candidate vehicles for a corrupted read.

    >>> confusable_key("DL3CAB1234") == confusable_key("DL3CA8I234")
    True
    """
    if not mark:
        return None
    return "".join(_CONFUSABLES.get(ch, ch) for ch in mark)


# ----------------------------------------------------------------------
# Format emitters — used only by the data generator, so that each source
# genuinely stores its own house format rather than a shared one.
# ----------------------------------------------------------------------

def as_hyphenated(mark):
    """DL3CAB1234 -> DL-3C-AB-1234 (the RTO's printed format)."""
    parts = _split(mark)
    return "-".join(parts) if parts else mark


def as_spaced(mark):
    """DL3CAB1234 -> DL 3C AB 1234 (the insurers' format)."""
    parts = _split(mark)
    return " ".join(parts) if parts else mark


def _split(mark):
    """Break a canonical mark into state / district / series / number."""
    m = re.match(r"^([A-Z]{2})([0-9]{1,2})([A-Z]{1,3})([0-9]{4})$", mark or "")
    return list(m.groups()) if m else None

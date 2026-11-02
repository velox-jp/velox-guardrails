"""PII masking for Japanese and English text: phone, postal code, email, card-like numbers.

Bare 7-digit numbers are NOT treated as PII. A postal code is matched only with
the postal mark or a nearby keyword.
"""
from __future__ import annotations

import re
from typing import Callable

_START = r"(?<![\d-])"  # not glued to a longer number
_END = r"(?![\d-])"

# (kind, pattern). A named group "v", if present, is the part to mask.
_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    ("email", re.compile(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")),
    # Card-like: 4-4-4-4 separated by hyphen or space. Plain digits are checked with Luhn below.
    ("card", re.compile(_START + r"\d{4}([- ])\d{4}\1\d{4}\1\d{4}" + _END)),
    # Japanese phone: +81 form, mobile (050/070/080/090), hyphenated landline, freedial.
    ("phone", re.compile(r"(?<![\d-])\+81[- ]?\(?0?\)?[1-9]\d?[- ]?\d{3,4}[- ]?\d{4}" + _END)),
    ("phone", re.compile(_START + r"0[5789]0[- ]?\d{4}[- ]?\d{4}" + _END)),
    ("phone", re.compile(_START + r"0[1-9]\d{0,3}-\d{1,4}-\d{4}" + _END)),
    ("phone", re.compile(_START + r"0120[- ]?\d{3}[- ]?\d{3}" + _END)),
    # Postal code with the mark.
    ("postal", re.compile(r"〒\s?\d{3}-?\d{4}(?!\d)")),
    # Postal code after a keyword (hyphen optional).
    (
        "postal",
        re.compile(
            r"(?:郵便番号|postal\s*code|post\s*code|zip(?:\s*code)?)\s*[:：]?\s*"
            r"(?P<v>\d{3}-?\d{4})" + _END,
            re.IGNORECASE,
        ),
    ),
]

_PLAIN_CARD = re.compile(_START + r"\d{13,16}" + _END)


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _valid_phone(matched: str) -> bool:
    """Digit-count check: Japanese numbers have 10 or 11 digits (9 or 10 after +81)."""
    digits = re.sub(r"\D", "", matched)
    if matched.startswith("+81"):
        rest = digits[2:]
        if rest.startswith("0"):
            rest = rest[1:]
        return len(rest) in (9, 10)
    return len(digits) in (10, 11) and digits[0] == "0"


def find_pii(text: str) -> list[tuple[str, int, int]]:
    """Return non-overlapping (kind, start, end) spans, sorted by start."""
    spans: list[tuple[str, int, int]] = []
    for kind, rx in _PATTERNS:
        for m in rx.finditer(text):
            if "v" in rx.groupindex:
                spans.append((kind, m.start("v"), m.end("v")))
            else:
                if kind == "phone" and not _valid_phone(m.group()):
                    continue
                spans.append((kind, m.start(), m.end()))
    for m in _PLAIN_CARD.finditer(text):
        if _luhn(m.group()):
            spans.append(("card", m.start(), m.end()))
    spans.sort(key=lambda s: (s[1], -(s[2] - s[1])))
    merged: list[tuple[str, int, int]] = []
    for s in spans:
        if merged and s[1] < merged[-1][2]:
            continue
        merged.append(s)
    return merged


def mask_pii(text: str, replacement: str | Callable[[str], str] = "[MASKED]") -> str:
    """Mask PII. `replacement` may be a string or a function of the kind ("email", ...)."""
    out: list[str] = []
    last = 0
    for kind, start, end in find_pii(text):
        out.append(text[last:start])
        out.append(replacement(kind) if callable(replacement) else replacement)
        last = end
    out.append(text[last:])
    return "".join(out)

"""First-pass prompt-injection filter (regular expressions, English and Japanese).

This is a simple keyword/phrase filter. It catches common, literal attack
phrasing and nothing more. Paraphrased, translated, encoded or multi-turn
attacks will get through. Use it as one cheap layer, not as a defense.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

# 17 patterns. Matched case-insensitively unless a pattern turns that off with (?-i:...).
DEFAULT_PATTERNS: tuple[str, ...] = (
    # --- English ---
    r"\bignore\s+(?:all\s+)?(?:(?:previous|above|prior|earlier)\s+)?(?:instructions|rules|prompts?)\b",
    r"\bforget\s+(?:everything\s+(?:above|before|you\s+were\s+told)|all\s+(?:previous|prior)\s+\w+|(?:your|previous|prior)\s+instructions)",
    # "you are now" only when followed by a role/mode change, not "you are now ready".
    r"\byou\s+are\s+now\s+(?:in\s+\w+\s+mode|an?\s+(?:unrestricted|unfiltered|uncensored|jailbroken|different|new|evil)\b|(?-i:DAN)\b|free\s+(?:of|from)\b|no\s+longer\b)",
    # "act as" only when it asks for a rule-free or privileged persona.
    r"\bact\s+as\s+(?:if\s+you\s+(?:are|were|have)\s+(?:not\s+bound|no\s+(?:rules|restrictions|limits)|unrestricted|free\b)|an?\s+(?:unrestricted|unfiltered|uncensored|jailbroken|evil|different\s+ai)\b|(?:the\s+)?(?:system|root|admin(?:istrator)?|developer)\b|(?-i:DAN)\b)",
    r"\bnew\s+system\s+prompt\b",
    r"\boverride\s+(?:your|the)\s+(?:instructions|rules|constraints|training|safety)",
    r"\bdisregard\s+(?:your|the|all|any|previous|prior)\s+(?:\w+\s+)?(?:instructions|rules|guidelines|prompts?)",
    r"\bjailbreak(?:s|ed|ing)?\b",
    # Case-sensitive on purpose: the name "Dan" must not match.
    r"(?-i:\bDAN\b)\s+(?:mode|prompt)|\bdo\s+anything\s+now\b",
    r"\bprompt\s+injection\b",
    # --- Japanese ---
    r"以下の指示を無視",
    r"システムプロンプトを(?:変更|無視|上書き)",
    r"あなたは今から[^。\n]{0,30}?(?:として|になりきっ|のふり|を演じ|です)",
    r"新しい(?:役割|ルール|指示)(?:として|に従|を与え|だけ|のみ|で(?:動|行動))",
    r"制約を(?:無視|削除|解除)",
    r"ルールを(?:無効|無視|削除)",
    r"これ以前の(?:すべて|全て)の(?:指示|命令|ルール|プロンプト)",
)


@dataclass(frozen=True)
class InjectionResult:
    safe: bool
    threat_level: str  # "none" | "low" | "high"
    detected: list[str] = field(default_factory=list)  # matched pattern strings


def _compile(patterns: Iterable[str]) -> list[tuple[str, "re.Pattern[str]"]]:
    return [(p, re.compile(p, re.IGNORECASE)) for p in patterns]


def scan_injection(
    text: str,
    patterns: Sequence[str] | None = None,
    extra_patterns: Sequence[str] = (),
) -> InjectionResult:
    """Scan text. One matching pattern is "low", two or more is "high".

    patterns: replace the default list. extra_patterns: add to it.
    """
    pats = list(DEFAULT_PATTERNS if patterns is None else patterns) + list(extra_patterns)
    detected = [p for p, rx in _compile(pats) if rx.search(text or "")]
    level = "none" if not detected else ("high" if len(detected) >= 2 else "low")
    return InjectionResult(safe=not detected, threat_level=level, detected=detected)


def sanitize_injection(
    text: str,
    patterns: Sequence[str] | None = None,
    extra_patterns: Sequence[str] = (),
    replacement: str = "[FILTERED]",
) -> str:
    """Replace each matched phrase with `replacement`."""
    pats = list(DEFAULT_PATTERNS if patterns is None else patterns) + list(extra_patterns)
    out = text or ""
    for _, rx in _compile(pats):
        out = rx.sub(replacement, out)
    return out

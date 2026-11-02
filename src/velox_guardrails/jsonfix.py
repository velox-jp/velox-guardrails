"""Parse JSON from LLM output: strips code fences and surrounding prose, repairs truncation."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def _scan(text: str) -> tuple[list[str], bool, bool]:
    """Return (open-bracket stack as closers, in_string, dangling_escape) for text."""
    stack: list[str] = []
    in_str = esc = False
    for c in text:
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]":
            if not stack or stack[-1] != c:
                return [], False, False
            stack.pop()
    return stack, in_str, esc


def _extract(text: str) -> str | None:
    """From the first "{", return the balanced object, or the rest of the text if unclosed."""
    start = text.find("{")
    if start < 0:
        return None
    stack: list[str] = []
    in_str = esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]":
            if stack and stack[-1] == c:
                stack.pop()
                if not stack:
                    return text[start : i + 1]
            else:
                return None
    return text[start:]


def _repair(fragment: str) -> str | None:
    """Close a truncated fragment: open string, dangling key or comma, unclosed brackets."""
    stack, in_str, esc = _scan(fragment)
    if not stack and not in_str:
        return None
    s = fragment
    if esc:
        s = s[:-1]
    if in_str:
        s += '"'
    s = s.rstrip()
    s = re.sub(r",\s*$", "", s)
    if s.endswith(":"):
        s += " null"
    elif stack and stack[-1] == "}" and re.search(r'[{,]\s*"(?:[^"\\]|\\.)*"$', s):
        s += ": null"  # a key with no value yet
    return s + "".join(reversed(stack))


def _loads(s: str) -> Any:
    try:
        return json.loads(s)
    except ValueError:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", s))  # tolerate trailing commas


def parse_llm_json(
    text: str | None,
    required: list[str] | None = None,
    defaults: dict | None = None,
    return_info: bool = False,
) -> Any:
    """Return a dict, or None if no usable JSON object is found or a required key is missing/null.

    With return_info=True, return (value, repaired) instead. `repaired` is True when the
    text was not valid JSON as it stood (truncation closed, trailing comma removed, or
    code fence / surrounding prose stripped).
    """
    value, repaired = _parse(text, required, defaults)
    repaired = repaired and value is not None
    return (value, repaired) if return_info else value


def _parse(text, required, defaults) -> tuple[dict | None, bool]:
    if not text or not text.strip():
        return None, False
    cleaned = re.sub(r"```(?:json|JSON)?", "", text).strip()
    parsed: Any = None
    repaired = cleaned != text.strip()
    try:
        parsed = _loads(cleaned)
        if not repaired:
            try:
                json.loads(cleaned)
            except ValueError:
                repaired = True
    except ValueError:
        repaired = True
        cand = _extract(cleaned)
        if cand:
            try:
                parsed = _loads(cand)
            except ValueError:
                fixed = _repair(cand)
                if fixed:
                    try:
                        parsed = _loads(fixed)
                    except ValueError:
                        parsed = None
    if not isinstance(parsed, dict):
        logger.warning("parse_llm_json: no JSON object found: %r", text[:200])
        return None, repaired
    for k, v in (defaults or {}).items():
        parsed.setdefault(k, v)
    missing = [k for k in (required or []) if parsed.get(k) is None]
    if missing:
        logger.warning("parse_llm_json: missing fields %s", missing)
        return None, repaired
    return parsed, repaired

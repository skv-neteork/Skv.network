"""Mask secrets in text that leaves the turn before saving (search queries, state). Same fallback rules as /remember."""
import re
_RX = [re.compile(r"(?<![\[\w:])([A-Za-z0-9][\w\-.@/+=]{3,})(\s*)\[SECRET\]"),
       re.compile(r"(?i)((?:secret|token|api[ _-]?key|key|password|passcode|пароль|токен|ключ)\s*(?:is|=|:|—|-|это)\s*[\"«']?)(?=[^\s\"«']*\d)([A-Za-z0-9][\w\-.@/+=]{5,})"),
       re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{6,}\b|\bsk-[A-Za-z0-9_-]{16,}\b|\bgh[pousr]_[A-Za-z0-9]{20,}\b|\b(?:pza|skint)_[A-Za-z0-9_\-]{8,}|\bsk_[A-Za-z0-9]{16,}\b")]


def scrub(s, sensitive=None):
    if not s or not isinstance(s, str):
        return s
    for x in sorted([x for x in (sensitive or []) if isinstance(x, str) and len(x.strip()) >= 3], key=len, reverse=True):
        s = s.replace(x.strip(), "[SECRET]")
    s = _RX[0].sub(lambda m: "[SECRET]" if m.group(1) != "SECRET" else m.group(0), s)
    s = _RX[1].sub(lambda m: m.group(1) + "[SECRET]", s)
    s = _RX[2].sub("[SECRET]", s)
    return s.replace("[SECRET] [SECRET]", "[SECRET]")

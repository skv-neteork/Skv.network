"""English text for shared-cube search.

Memory search stays in the memory language. The cube catalog is English, so a
non-English query is translated once and cached. English text is returned as-is.
A failed translation returns the original text.
"""
import os
import re
import threading
import time

_CACHE = {}
_LOCK = threading.Lock()
_MAX = 256
_TTL = 86400
_CYR = re.compile(r"[А-Яа-яЁёІіЇїЄє]")
_LAT = re.compile(r"[A-Za-z]")


def needs_english(text: str) -> bool:
    """True when the query is not already English enough for the cube catalog."""
    t = text or ""
    cyr = len(_CYR.findall(t))
    if cyr < 3:
        return False
    lat = len(_LAT.findall(t))
    return lat < cyr * 2


def english_query(text: str) -> str:
    raw = (text or "").strip()
    if not raw or not needs_english(raw):
        return raw
    key = re.sub(r"\s+", " ", raw.lower())[:400]
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[1] < _TTL:
            return hit[0]
    en = _translate(raw)
    if not en:
        return raw
    with _LOCK:
        if len(_CACHE) >= _MAX:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = (en, now)
    return en


def _model() -> str:
    env = (os.environ.get("SKV_CUBE_TRANSLATE_MODEL") or "").strip()
    if env:
        return env
    try:
        from app.memory_v2 import config
        cfg = config()
        return cfg.get("cube_translate_model") or cfg.get("recall_later_model") or cfg.get("llm_model") or "deepseek/deepseek-v4-flash"
    except Exception:
        return "deepseek/deepseek-v4-flash"


def _translate(text: str) -> str:
    if (os.environ.get("SKV_CUBE_TRANSLATE") or "1").strip().lower() in ("0", "off", "false", "no"):
        return ""
    try:
        from app.memory_v2 import mask_text
        from app.security import polza_post
        masked = (mask_text(text) or "").strip()[:400]
        if not masked:
            return ""
        model = _model()
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": (
                    "Translate the search query into English for an experience-cube catalog. "
                    "Keep names, numbers, code, ids and quoted text verbatim. "
                    "Reply with the translation only, one line, no quotes."
                )},
                {"role": "user", "content": masked},
            ],
            "temperature": 0,
            "max_tokens": 80,
            "reasoning": {"enabled": False},
        }
        r = polza_post(body, timeout=8, connect_timeout=5, tries=1)
        if r.status_code >= 400:
            print(f"[cube_query] translate http {r.status_code}", flush=True)
            return ""
        d = r.json()
        content = ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        line = content.strip().strip('"').strip("«»")
        line = line.splitlines()[0].strip() if line else ""
        line = re.sub(r"^(translation|english)\s*:\s*", "", line, flags=re.I).strip()
        if len(_LAT.findall(line)) < 3:
            return ""
        try:
            from app import memory_v2_llm as L
            u = d.get("usage") or {}
            L._log({"ts": time.time(), "job": "cube_query", "model": model,
                    "prompt": u.get("prompt_tokens", 0), "completion": u.get("completion_tokens", 0),
                    "cost_rub": u.get("cost_rub", d.get("cost_rub"))})
        except Exception:
            pass
        return line[:300]
    except Exception as e:
        print(f"[cube_query] translate skipped: {type(e).__name__}", flush=True)
        return ""

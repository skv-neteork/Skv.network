"""Checks before a cube becomes shared (2026-10-19): secrets, PII, English-only.
Secret detection reuses the vault patterns (app.vault._AUTO) without storing anything."""
import re

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_EVENT = re.compile(r"\b[^\s:]{3,}::[A-Za-z0-9_\-]+")
_PHONE = re.compile(r"(?<![\w.])\+?\d[\d \-()]{8,}\d(?![\w.])")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_VREF = re.compile(r"\[vault:[^\]]+\]")


def secret_labels(text):
    if not text:
        return []
    out = []
    if _VREF.search(text):
        out.append("vault_ref")
    try:
        from app import vault as _v
        for label, rx, grp in _v._AUTO:
            for m in rx.finditer(text):
                val = m.group(grp) or ""
                if val and not _v._PLACEHOLDER.match(val) and not val.startswith("[vault:"):
                    out.append(label or "secret")
    except Exception:
        if re.search(r"\bsk_[A-Za-z0-9]{16,}\b", text):
            out.append("skv_key")
    return sorted(set(out))


def mask_pii(text):
    if not text:
        return text, []
    found = []
    for name, rx, rep in (("event_id", _EVENT, "[event]"), ("email", _EMAIL, "[email]"), ("card", _CARD, "[number]"),
                          ("phone", _PHONE, "[phone]"), ("ip", _IP, "[ip]")):
        text, n = rx.subn(rep, text)
        if n:
            found.append(name)
    return text, found


def is_english(text):
    letters = [ch for ch in (text or "") if ch.isalpha()]
    if not letters:
        return True
    non_latin = sum(1 for ch in letters if not ("a" <= ch.lower() <= "z"))
    return non_latin / len(letters) <= 0.1


def prepare_shared(topic, essence, rules, evidence, require_english=True, skill_md="", hooks=""):
    """Returns (ok, fields, reasons, pii_found). fields are PII-masked. ok=False means: do not publish.
    skill_md + hooks are optional skill-cube fields; checked the same way (secrets/English)."""
    fields = {"topic": topic or "", "essence": essence or "", "rules": rules or "", "evidence": evidence or "",
              "skill_md": skill_md or "", "hooks": hooks if isinstance(hooks, str) else ("" if hooks is None else str(hooks))}
    reasons = []
    sec = sorted({l for v in fields.values() for l in secret_labels(v)})
    if sec:
        reasons.append("secret:" + ",".join(sec))
    pii = []
    for k in fields:
        fields[k], f = mask_pii(fields[k])
        pii += f
    eng_blob = " ".join([fields["topic"], fields["essence"], fields["rules"], fields["skill_md"], fields["hooks"]])
    if require_english and not is_english(eng_blob):
        reasons.append("not_english")
    if not fields["essence"].strip() or not fields["rules"].strip():
        reasons.append("empty")
    return (not reasons), fields, reasons, sorted(set(pii))


def field_report(**fields):
    """Strict check for shared cubes: [{field, reason}] for secrets and PII (event ids are allowed evidence)."""
    out = []
    for k, v in fields.items():
        v = v if isinstance(v, str) else ("" if v is None else str(v))
        for l in secret_labels(v):
            out.append({"field": k, "reason": "secret:" + l})
        t = _EVENT.sub("[event]", v)
        for name, rx in (("email", _EMAIL), ("card", _CARD), ("phone", _PHONE), ("ip", _IP)):
            for m in rx.finditer(t):
                g = m.group(0)
                if name == "phone" and (sum(ch.isdigit() for ch in g) < 10 or re.fullmatch(r"\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?", g.strip())):
                    continue
                if name == "card" and sum(ch.isdigit() for ch in g) < 13:
                    continue
                out.append({"field": k, "reason": name})
                break
    return out

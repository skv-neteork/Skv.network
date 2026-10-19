"""Cheap non-AI auto-capture of critical facts (names, dates, links, phones, emails, addresses).

Runs on every saved turn (account_memory.queue_turn), after vault scrubbing, so secrets never land here.
Facts go to table critical_auto (deduped by kind+normalized value) and are shown in the Critical
layer after the agent's own >>> marks, inside the same critical budget (memory_config budgets.critical).
Toggle: memory_config.json "critical_auto": false.
"""
import re
import sqlite3

_URL = re.compile(r"\bhttps?://[^\s<>\"')\]]+|\bwww\.[^\s<>\"')\]]+", re.I)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_PHONE = re.compile(r"(?<![\w.])\+?\d[\d\s().-]{8,16}\d(?![\w.])")
_MON = (r"(?:январ[яь]|феврал[яь]|марта?|апрел[яь]|ма[яй]|июн[яь]|июл[яь]|августа?|сентябр[яь]|октябр[яь]|ноябр[яь]|декабр[яь]|"
        r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_DATE = re.compile(r"\b(?:\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+" + _MON + r"(?:\s+\d{4})?|" + _MON + r"\s+\d{1,2}(?:,?\s+\d{4})?)\b", re.I)
_ADDR = re.compile(r"(?:\b(?:ул\.|улица|пр-т|проспект|пер\.|переулок|шоссе|бульвар|наб\.|набережная)\s+[А-ЯЁA-Z][\w.-]*(?:\s+[А-ЯЁA-Z][\w.-]*)?,?\s*(?:д\.?\s*)?\d+[\w/]*"
                   r"|\b\d{1,5}\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Boulevard|Blvd\.?|Lane|Ln\.?|Drive|Dr\.?)\b)")
_NAME = re.compile(r"(?i:меня зовут|зовут|его зовут|её зовут|ее зовут|по имени|my name is|named|called|i am|i'm)\s+([А-ЯЁA-Z][а-яёa-z]+(?:\s+[А-ЯЁA-Z][а-яёa-z]+)?)")
_STOP_NAMES = {"I", "The", "A", "Ok", "Okay"}


def _ctx(text, m, width=40):
    a, b = max(0, m.start() - width), min(len(text), m.end() + width)
    return re.sub(r"\s+", " ", text[a:b]).strip()


def extract(text):
    """-> [(kind, value, context)]; pure regex, no model."""
    text = text or ""
    out, taken = [], []
    def add(kind, m, val=None):
        span = m.span(1) if val is not None else m.span()
        if any(s <= span[0] < e for s, e in taken):
            return
        taken.append(span)
        out.append((kind, (val or m.group(0)).strip().rstrip(".,;:"), _ctx(text, m)))
    for m in _URL.finditer(text): add("link", m)
    for m in _EMAIL.finditer(text): add("email", m)
    for m in _DATE.finditer(text):
        n = re.match(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})$", m.group(0))
        if n and not (1 <= int(n.group(1)) <= 31 and 1 <= int(n.group(2)) <= 12 and len(n.group(3)) in (2, 4)):
            continue
        add("date", m)
    for m in _PHONE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 10 <= len(digits) <= 15: add("phone", m)
    for m in _ADDR.finditer(text): add("address", m)
    for m in _NAME.finditer(text):
        if m.group(1) not in _STOP_NAMES: add("name", m, m.group(1))
    return out


def _norm(kind, value):
    v = value.lower()
    if kind == "phone":
        v = re.sub(r"\D", "", v)
    return kind + ":" + re.sub(r"\s+", " ", v)


def ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS critical_auto (
        key TEXT PRIMARY KEY, kind TEXT, value TEXT, context TEXT, event_id TEXT, time_str TEXT, hits INTEGER DEFAULT 1)""")


def capture(conn, event_id, time_str, text, max_per_turn=8):
    facts = extract(text)[:max_per_turn]
    if not facts:
        return 0
    ensure(conn)
    for kind, value, ctx in facts:
        conn.execute("""INSERT INTO critical_auto (key, kind, value, context, event_id, time_str) VALUES (?,?,?,?,?,?)
                        ON CONFLICT(key) DO UPDATE SET hits = hits + 1, time_str = excluded.time_str""",
                     (_norm(kind, value), kind, value[:200], ctx[:160], event_id, time_str))
    return len(facts)


def lines(conn, limit=200):
    try:
        rows = conn.execute("SELECT kind, value, context, time_str FROM critical_auto ORDER BY time_str DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
    except sqlite3.OperationalError:
        return []
    return rows

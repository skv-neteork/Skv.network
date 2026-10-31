"""'On this day in past years': events, critical marks (>>> and critical_auto dates) and agent_calendar
whose month-day falls within +-otd_window_days of today, from earlier years (or yearly items: birthdays etc.).
Sent once per calendar day per account (first recall of the day), own budget otd_tokens.
Config (memory_config.json): otd_enabled (true), otd_tokens (300), otd_window_days (1), user_tz ("Europe/Moscow")."""
import datetime as _dt, re
from app import shelves as _sh
from app.memory_v2 import clip, est_tokens, mask_text, norm_date

MON_RU = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12}
MON_EN = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
YEARLY = re.compile(r"рожден|birthday|годовщин|anniversar|юбиле|свадьб|праздник|памят|ежегодн|yearly|annual", re.I)
_DMY = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4}|\d{2})\b")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMON = re.compile(r"\b(\d{1,2})\s+([А-Яа-яЁёA-Za-z]{3,9})\.?(?:\s+(\d{4}))?")
_MOND = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b")


def _mon(w):
    w = w.lower()
    if w[:3] in MON_EN and re.match(r"[a-z]", w):
        return MON_EN[w[:3]]
    for k, v in sorted(MON_RU.items(), key=lambda x: -len(x[0])):
        if w.startswith(k) and (k != "ма" or w in ("мая", "май", "мае")):
            return v
    return None


def dates_in(text):
    """-> [(year|None, month, day)] named in free text."""
    out = []
    for m in _ISO.finditer(text or ""):
        out.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in _DMY.finditer(text or ""):
        y = int(m.group(3)); y = y + 2000 if y < 100 else y
        out.append((y, int(m.group(2)), int(m.group(1))))
    for m in _DMON.finditer(text or ""):
        mo = _mon(m.group(2))
        if mo: out.append((int(m.group(3)) if m.group(3) else None, mo, int(m.group(1))))
    for m in _MOND.finditer(text or ""):
        mo = _mon(m.group(1))
        if mo and re.match(r"[A-Za-z]", m.group(1)): out.append((int(m.group(3)) if m.group(3) else None, mo, int(m.group(2))))
    return [(y, mo, d) for y, mo, d in out if 1 <= mo <= 12 and 1 <= d <= 31]


def _ts_date(ts):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", norm_date(ts or ""))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def today_for(cfg, as_of=None, uid=None):
    if as_of:
        try:
            return _dt.date.fromisoformat(str(as_of).strip()[:10])
        except ValueError:
            pass
    tz = cfg.get("user_tz", "Europe/Moscow")
    try:
        from zoneinfo import ZoneInfo
        return _dt.datetime.now(ZoneInfo(tz)).date()
    except Exception:
        return _dt.datetime.utcnow().date()


def _near(today, mo, d, win):
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            if abs((_dt.date(y, mo, d) - today).days) <= win:
                return True
        except ValueError:
            continue
    return False


def collect(uid, today, win=1, limit=40):
    """-> list of dict(year, month, day, text, src, event_id, yearly)."""
    out, seen = [], set()
    def add(y, mo, d, text, src, eid="", yearly=False):
        text = re.sub(r"(>{2,}\s*)+|✅|\b[QA]:\s*", "", re.sub(r"\s+", " ", text or "")).strip(" :-")
        key = (mo, d, text[:60].lower())
        if not text or key in seen or (eid and (eid, mo, d) in seen) or (y and y >= today.year and not yearly):
            return
        if not _near(today, mo, d, win):
            return
        seen.add(key); seen.add((eid, mo, d))
        out.append({"year": y, "month": mo, "day": d, "text": text, "src": src, "event_id": eid, "yearly": yearly})
    conn = _sh.connect(uid)
    try:
        tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "event_metadata" in tabs:
            # critical marks: dates named inside, else the event date
            for eid, ts, raw in conn.execute("SELECT event_id, time_str, raw_dialogue FROM event_metadata WHERE raw_dialogue LIKE '%>>>%' ORDER BY rowid DESC LIMIT 2000"):
                for ln in (raw or "").split("\n"):
                    if ">>>" not in ln:
                        continue
                    yr = bool(YEARLY.search(ln)); ds = dates_in(ln); td = _ts_date(ts)
                    for y, mo, d in ds:
                        add(y or (td[0] if td and not yr else None), mo, d, ln, "critical", eid, yr or y is None)
                    if not ds and td:
                        add(td[0], td[1], td[2], ln, "critical", eid, yr)
            # past events by their own date (same month-day, earlier year)
            pats = []
            for k in range(-win, win + 1):
                x = today + _dt.timedelta(days=k)
                pats += [f"%-{x.month:02d}-{x.day:02d}%", f"%, {x.day:02d}.{x.month:02d}.%"]
            q = " OR ".join("time_str LIKE ?" for _ in pats)
            for eid, ts, raw, kind in conn.execute(f"SELECT event_id, time_str, raw_dialogue, kind FROM event_metadata WHERE ({q}) AND raw_dialogue NOT LIKE '%>>>%' ORDER BY rowid DESC LIMIT 400", pats):
                td = _ts_date(ts)
                if td and td[0] < today.year and kind not in ("doc", "docs", "document", "code", "log", "file") and len((raw or "").strip()) > 40:
                    add(td[0], td[1], td[2], raw[:300], "event", eid, bool(YEARLY.search(raw or "")))
        if "critical_auto" in tabs:
            for kind, value, ctx, eid, ts in conn.execute("SELECT kind, value, context, event_id, time_str FROM critical_auto WHERE kind='date' LIMIT 2000"):
                yr = bool(YEARLY.search(ctx or "")); td = _ts_date(ts)
                for y, mo, d in dates_in(value):
                    add(y or (td[0] if td and not yr else None), mo, d, ctx or value, "auto", eid or "", yr or y is None)
        if "agent_calendar" in tabs:
            for cid, date, title, kind in conn.execute("SELECT id, date, title, kind FROM agent_calendar"):
                ds = dates_in(date or "") or []
                yr = bool(YEARLY.search((kind or "") + " " + (title or "")))
                for y, mo, d in ds:
                    add(y, mo, d, title, "calendar", f"cal:{cid}", yr)
    finally:
        conn.close()
    pri = {"critical": 0, "calendar": 0, "auto": 1, "event": 2}
    out.sort(key=lambda r: (not r["yearly"], pri.get(r["src"], 3), -(r["year"] or 0)))
    return out[:limit]


def render(today, rows, budget):
    if not rows:
        return ""
    head = f"Сегодня {today.day} {GEN[today.month - 1]} {today.year} (в этот день в прошлые годы):"
    L, used = [head], est_tokens(head)
    for r in rows:
        when = f"{r['day']} {GEN[r['month'] - 1]}" + (f" {r['year']}" if r["year"] else "")
        tag = " (каждый год)" if r["yearly"] else ""
        ref = f" [{r['event_id']}]" if r["event_id"] else ""
        line = f"- {when}{tag}: {mask_text(clip(r['text'], 40))}{ref}"
        c = est_tokens(line) + 2
        if used + c > budget:
            break
        L.append(line); used += c
    return "\n".join(L) if len(L) > 1 else ""


def for_recall(uid, cfg, as_of=None, force=False):
    if not cfg.get("otd_enabled", True):
        return ""
    today = today_for(cfg, as_of, uid)
    conn = _sh.connect(uid)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS otd_state (id INTEGER PRIMARY KEY CHECK (id=1), last_day TEXT)")
        row = conn.execute("SELECT last_day FROM otd_state WHERE id=1").fetchone()
        if row and row[0] == today.isoformat() and not force:
            return ""
        conn.execute("INSERT OR REPLACE INTO otd_state (id, last_day) VALUES (1, ?)", (today.isoformat(),))
        conn.commit()
    finally:
        conn.close()
    rows = collect(uid, today, int(cfg.get("otd_window_days", 1)))
    return render(today, rows, int(cfg.get("otd_tokens", 300) or 300))

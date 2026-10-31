"""Archived raw text access (archive steps 1+2, 25.10). archive_cold() moves raw text older than 90 days to
event_archive and leaves '[archived] <id>' in event_metadata. Here: read it back and keyword-search it. No vectors."""
import re, sqlite3
from datetime import datetime, timedelta

MARK = "[archived]"
FMTS = ("%H:%M, %d.%m.%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d")


def is_marker(raw):
    return isinstance(raw, str) and raw.startswith(MARK)


def _has(conn):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name='event_archive'").fetchone())


def full_text(conn, eid):
    try:
        if not _has(conn):
            return None
        from app.archive_store import text_of
        cols = {c[1] for c in conn.execute("PRAGMA table_info(event_archive)")}
        if "body_z" in cols:
            r = conn.execute("SELECT raw_dialogue, body_z FROM event_archive WHERE event_id=?", (eid,)).fetchone()
            return text_of(r[0], r[1]) if r else None
        r = conn.execute("SELECT raw_dialogue FROM event_archive WHERE event_id=?", (eid,)).fetchone()
        return r[0] if r else None
    except sqlite3.Error:
        return None


def _when(ts):
    for f in FMTS:
        try:
            return datetime.strptime((ts or "").strip()[:len(datetime(2000, 1, 1, 0, 0).strftime(f))], f)
        except Exception:
            pass
    return None


def is_old(query, days=85):
    """True if the query points at a date/period older than ~the archive cutoff."""
    q = (query or "").lower()
    now = datetime.utcnow()
    if re.search(r"(год|года|лет|years?|месяц\w* назад|months? ago|давно|прошл\w+ (год|весн|лет|осен|зим)|last (year|spring|summer|autumn|winter))", q):
        return True
    for d, m, y in re.findall(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", q):
        try:
            if datetime(int(y), int(m), int(d)) < now - timedelta(days=days): return True
        except Exception: pass
    for y, m, d in re.findall(r"\b(\d{4})-(\d{2})-(\d{2})\b", q):
        try:
            if datetime(int(y), int(m), int(d)) < now - timedelta(days=days): return True
        except Exception: pass
    for y in re.findall(r"\b(20\d\d)\b", q):
        if int(y) < now.year: return True
    return False


def _terms(query):
    try:
        from app.search_v2 import query_terms
        return [s.lower() for _, s, _ in query_terms(query)][:6]
    except Exception:
        return [w.lower()[:6] for w in re.findall(r"\w{3,}", query or "")][:6]


def search_conn(conn, query, limit=5):
    if not _has(conn):
        return []
    terms = [t for t in _terms(query) if len(t) >= 3]
    if not terms:
        return []
    from app.archive_store import text_of
    cols = {c[1] for c in conn.execute("PRAGMA table_info(event_archive)")}
    zc = "a.body_z" if "body_z" in cols else "NULL"
    # text is zlib-compressed: decompress and scan in Python (slower, archive search is rare)
    out = []
    for eid, raw0, bz, ts in conn.execute("SELECT a.event_id, a.raw_dialogue, " + zc + ", m.time_str FROM event_archive a "
                                          "LEFT JOIN event_metadata m ON m.event_id=a.event_id"):
        try:
            raw = text_of(raw0, bz)
        except Exception:
            continue
        lo = raw.lower()
        hit = sum(1 for t in terms if t in lo)
        if not hit:
            continue
        pos = min([lo.find(t) for t in terms if t in lo] or [0])
        snip = (raw or "")[max(0, pos - 80): pos + 220].replace("\n", " ")
        out.append({"event_id": eid, "time_str": ts, "score": round(hit / len(terms), 3), "snippet": snip, "archived": True})
    out.sort(key=lambda x: (-x["score"], -((_when(x["time_str"]) or datetime.min).timestamp() if _when(x["time_str"]) else 0)))
    return out[:limit]


def search(uid, query, limit=5):
    try:
        from app.memory_v2 import db_path
        conn = sqlite3.connect(db_path(uid), timeout=10)
        try:
            return search_conn(conn, query, limit)
        finally:
            conn.close()
    except Exception:
        return []

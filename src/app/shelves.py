"""Memory shelves: kind / source / project on every record (default kind=dialogue)."""
import hashlib
import os
import re
import sqlite3

BASE_DIR = "/data/skv/metadata_store"
# recommended defaults; any other English slug creates a custom shelf on first write
DEFAULT_KINDS = ("dialogue", "email", "document", "code", "file")
_ready = set()


def normalize_kind(kind):
    """Free-form shelf slug: lowercase English a-z0-9 and '-', max 32. None if invalid."""
    k = re.sub(r"[\s_]+", "-", (kind or "").strip().lower())
    k = re.sub(r"-+", "-", k).strip("-")
    if not k:
        return "dialogue"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", k):
        return None
    return k


def _name(user_id):
    return "".join(c for c in (user_id or "") if c.isalnum() or c in ("_", "-"))


def connect(user_id):
    path = os.path.join(BASE_DIR, _name(user_id) + ".db")
    conn = sqlite3.connect(path, timeout=30)
    if path not in _ready:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(event_metadata)")}
        if cols:
            for col, ddl in (("kind", "TEXT DEFAULT 'dialogue'"), ("source", "TEXT DEFAULT ''"), ("project", "TEXT DEFAULT ''")):
                if col not in cols:
                    conn.execute(f"ALTER TABLE event_metadata ADD COLUMN {col} {ddl}")
            conn.execute("CREATE TABLE IF NOT EXISTS shelves (slug TEXT PRIMARY KEY, description TEXT, created_at TEXT)")
            conn.commit()
            _ready.add(path)
    return conn


def tag(user_id, ids, kind="dialogue", source="", project="", description=""):
    if not ids:
        return
    kind = normalize_kind(kind) or "dialogue"
    conn = connect(user_id)
    try:
        conn.execute("INSERT OR IGNORE INTO shelves (slug, description, created_at) VALUES (?,?,datetime('now'))", (kind, description or ""))
        if description:
            conn.execute("UPDATE shelves SET description=? WHERE slug=?", (description[:200], kind))
        conn.executemany("UPDATE event_metadata SET kind=?, source=?, project=? WHERE event_id=?",
                         [(kind, source or "", project or "", i) for i in ids])
        conn.commit()
    finally:
        conn.close()


def has_filter(kind=None, source=None, project=None):
    return bool(kind or source or project)


def allowed(user_id, ids, kind=None, source=None, project=None):
    ids = [i for i in ids if i]
    kind = normalize_kind(kind) if kind else None
    if not ids or not has_filter(kind, source, project):
        return set(ids)
    conn = connect(user_id)
    try:
        q = "SELECT event_id FROM event_metadata WHERE event_id IN (%s)" % ",".join("?" * len(ids))
        args = list(ids)
        for col, val in (("kind", kind), ("source", source), ("project", project)):
            if val:
                q += f" AND coalesce({col},'{'dialogue' if col == 'kind' else ''}') = ?"
                args.append(val)
        return {r[0] for r in conn.execute(q, args)}
    finally:
        conn.close()


def select_ids(user_id, kind=None, source=None, project=None, limit=200):
    kind = normalize_kind(kind) if kind else None
    conn = connect(user_id)
    try:
        q = "SELECT event_id, time_str, substr(raw_dialogue,1,160) FROM event_metadata WHERE event_id LIKE ?"
        args = [user_id + "::%"]
        for col, val in (("kind", kind), ("source", source), ("project", project)):
            if val:
                q += f" AND coalesce({col},'{'dialogue' if col == 'kind' else ''}') = ?"
                args.append(val)
        return conn.execute(q + " LIMIT ?", args + [limit]).fetchall()
    finally:
        conn.close()


def counts(user_id):
    """Only shelves that have records exist."""
    conn = connect(user_id)
    try:
        desc = dict(conn.execute("SELECT slug, description FROM shelves"))
        shelves = []
        for k, n in conn.execute("SELECT coalesce(kind,'dialogue'), count(*) FROM event_metadata GROUP BY 1 ORDER BY 2 DESC"):
            parts = [{"source": s, "project": p, "count": c} for s, p, c in conn.execute(
                "SELECT coalesce(source,''), coalesce(project,''), count(*) FROM event_metadata WHERE coalesce(kind,'dialogue')=? GROUP BY 1,2 ORDER BY 3 DESC LIMIT 20", (k,))]
            shelves.append({"shelf": k, "count": n, "description": desc.get(k, ""), "default": k in DEFAULT_KINDS, "by_source_project": parts})
        return shelves
    finally:
        conn.close()


def rename(user_id, src, dst, description=""):
    """Rename a shelf, or merge it into an existing one. Records keep source/project/critical marks."""
    src_n, dst_n = normalize_kind(src), normalize_kind(dst)
    if not src_n or not dst_n:
        raise ValueError("shelf names must be English slugs: a-z, 0-9, '-'")
    conn = connect(user_id)
    try:
        merged = conn.execute("SELECT count(*) FROM event_metadata WHERE coalesce(kind,'dialogue')=?", (dst_n,)).fetchone()[0] > 0
        n = conn.execute("UPDATE event_metadata SET kind=? WHERE coalesce(kind,'dialogue')=?", (dst_n, src_n)).rowcount
        old = conn.execute("SELECT description FROM shelves WHERE slug=?", (src_n,)).fetchone()
        conn.execute("INSERT OR IGNORE INTO shelves (slug, description, created_at) VALUES (?,?,datetime('now'))", (dst_n, description or (old[0] if old else "")))
        if description:
            conn.execute("UPDATE shelves SET description=? WHERE slug=?", (description[:200], dst_n))
        if src_n != dst_n:
            conn.execute("DELETE FROM shelves WHERE slug=?", (src_n,))
        conn.commit()
        return {"from": src_n, "to": dst_n, "moved": n, "merged": merged}
    finally:
        conn.close()


# ---------- chunking ----------
_PY_DEF = re.compile(r"^(?:async\s+def|def|class)\s+(\w+)", re.M)
_JS_DEF = re.compile(r"^(?:export\s+)?(?:async\s+)?(?:function\s+(\w+)|class\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s*)?\()", re.M)


def _split_at(text, starts, max_chars=3000):
    starts = sorted(set([0] + starts + [len(text)]))
    parts = []
    for a, b in zip(starts, starts[1:]):
        seg = text[a:b].strip("\n")
        while len(seg) > max_chars:
            parts.append(seg[:max_chars])
            seg = seg[max_chars:]
        if seg.strip():
            parts.append(seg)
    return parts


def chunk(kind, text, path="", version="", sender="", date="", title=""):
    """Returns [(header, body), ...]."""
    text = text or ""
    if kind == "code":
        m = list(_PY_DEF.finditer(text)) or list(_JS_DEF.finditer(text))
        parts = _split_at(text, [x.start() for x in m])
        out = []
        for p in parts:
            mm = _PY_DEF.search(p) or _JS_DEF.search(p)
            fn = next((g for g in mm.groups() if g), "") if mm else "module"
            out.append((f"CODE {path or title} @ {version or 'unversioned'} :: {fn}", p))
        return out
    if kind == "document":
        heads = [m.start() for m in re.finditer(r"^#{1,4}\s+.+$", text, re.M)]
        out = []
        for p in _split_at(text, heads):
            h = p.splitlines()[0].lstrip("# ").strip() if p.lstrip().startswith("#") else (title or "section")
            out.append((f"DOC {title or path} :: {h}", p))
        return out
    if kind == "email":
        return [(f"EMAIL from {sender or '?'} on {date or '?'} :: {title}", p) for p in _split_at(text, [], 4000)]
    return [(title or kind, p) for p in _split_at(text, [], 3000)]


def chunk_id(user_id, kind, project, header, body):
    h = hashlib.sha1((header + "\n" + body).encode("utf-8", "replace")).hexdigest()[:12]
    proj = "".join(c for c in (project or "") if c.isalnum() or c in "-_")[:40]
    return f"{user_id}::{kind}_{proj + '_' if proj else ''}{h}"

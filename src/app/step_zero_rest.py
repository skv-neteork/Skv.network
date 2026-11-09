"""Step-zero pages for a client that has no local account database.

The pages are the memory pack 8/8/8 plus the constitution texts.
A failure returns ok=false, pages=[] and a non-empty error. Never a silent blank page.
"""
import os
import re
import sqlite3


def _chunks(text, limit=7000):
    text = text or ""
    if not text:
        return []
    return [text[i:i + limit] for i in range(0, len(text), limit)]


def constitution_pages(shared_db="", owners=None):
    """Constitution cube texts. An absent source is an explicit page, not an empty string."""
    from app.memory_pack888 import SHARED_DB, mask
    path = shared_db or SHARED_DB
    header = "=== SKV CONSTITUTION: CUBE 00-04 ===\n"
    if not path or not os.path.isfile(path):
        return [header + "CONSTITUTION ABSENT: shared database was not found.\n"]
    authors = {"system"}
    for owner in owners or []:
        name = str(owner or "").strip().lower()
        if name:
            authors.add(name)
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
    except sqlite3.Error as exc:
        return [header + "CONSTITUTION ABSENT: %s\n" % type(exc).__name__]
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cubes_new'").fetchone():
            return [header + "CONSTITUTION ABSENT: no constitution table.\n"]
        rows = conn.execute(
            "SELECT cube_id, essence, rules_markdown, created_by, status FROM cubes_new "
            "WHERE cube_id LIKE 'cube_const_%'"
        ).fetchall()
    except sqlite3.Error as exc:
        return [header + "CONSTITUTION ABSENT: %s\n" % type(exc).__name__]
    finally:
        conn.close()
    latest = {}
    for eid, essence, raw, author, status in rows:
        if (status or "") in ("deprecated", "archived", "quarantine", "source"):
            continue
        if (author or "").strip().lower() not in authors:
            continue
        num = str(eid).replace("cube_const_", "").split("_")[0]
        match = re.search(r"_v(\d+)$", str(eid))
        ver = int(match.group(1)) if match else -1
        if num not in latest or ver > latest[num][0]:
            latest[num] = (ver, eid, essence or "", raw or "")
    if not latest:
        return [header + "CONSTITUTION ABSENT: no trusted constitution cubes.\n"]
    parts = [header]
    for num in sorted(latest):
        _ver, eid, essence, raw = latest[num]
        body, _changed = mask(raw)
        parts.append("=== CUBE %s (%s) ===\n%s\n%s\n" % (num.zfill(2), eid, essence, body))
    text = "\n".join(parts)
    return _chunks(text) or [header + "CONSTITUTION ABSENT: empty constitution text.\n"]


def build_pages(user_id, user_db="", shared_db=""):
    """Full step_zero page list for one account. Does not open a live key by itself."""
    from app.memory_pack888 import (
        SHARED_DB, assemble_step_zero, leak_names, load_pack, owner_list, render_document, split_document,
    )
    try:
        owners = owner_list(user_id)
        pack = load_pack(user_id, user_db or "", shared_db or "")
        doc = render_document(pack)
        leaks = leak_names(doc)
        if leaks:
            return {"ok": False, "pages": [], "error": "secret patterns remain: " + ",".join(leaks)}
        pack_pages = split_document(doc)
        if not any((p or "").strip() for p in pack_pages):
            return {"ok": False, "pages": [], "error": "empty memory pack"}
        intro = (
            "HOW TO WORK: read every page until done=true before you answer. "
            "The pages marked PACK888 are the memory pack 8/8/8. "
            "Concatenate the text under each PACK888 line, in order. "
            "A page break does not end a record. "
            "Constitution pages follow the pack. Read those too.\n"
        )
        const_pages = constitution_pages(shared_db or SHARED_DB, owners)
        pages = assemble_step_zero([intro], pack_pages, const_pages)
        if not any((p or "").strip() for p in pages):
            return {"ok": False, "pages": [], "error": "empty step_zero pages"}
        return {"ok": True, "pages": pages, "error": ""}
    except Exception as exc:
        line = (str(exc).splitlines() or [type(exc).__name__])[0][:180]
        return {"ok": False, "pages": [], "error": line or type(exc).__name__}

"""Step-zero pages for a client that has no local account database.

The pages are the memory pack 8/8/8 plus the constitution texts.
A failure returns ok=false, pages=[] and a non-empty error. Never a silent blank page.

REST serves one page per call. The text is grouped from the MCP step_zero slices
up to about 14 KB, and the JSON body stays within 16 KB. The room block is not
part of that text; the route adds it only on page 1.
"""
import json
import os
import re
import sqlite3

# One page of pack text, measured as the JSON body without the room block.
REST_PAGE_JSON = 14000
# Room fields on page 1. Kept apart so page boundaries do not depend on the room.
REST_ROOM_JSON = 2000
REST_RESPONSE_JSON = 16000


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


def _json_bytes(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _page_envelope(text: str) -> dict:
    return {"ok": True, "page": 99, "total_pages": 99, "text": text, "error": ""}


def _page_fits(text: str) -> bool:
    return _json_bytes(_page_envelope(text)) <= REST_PAGE_JSON


def _split_to_fit(text: str) -> list:
    """Split one slice that is larger than a REST page. Nothing is dropped."""
    parts = []
    rest = text or ""
    end_mark = "<<<END>>>\n"
    while rest:
        if _page_fits(rest):
            parts.append(rest)
            break
        lo, hi, best = 1, len(rest), 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if _page_fits(rest[:mid]):
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        snap = rest.rfind(end_mark, 0, best)
        snap_len = 0 if snap < 0 else snap + len(end_mark)
        if snap_len >= max(200, best // 5):
            best = snap_len
        if best < 1:
            best = 1
        parts.append(rest[:best])
        rest = rest[best:]
    return parts


def group_pages(pages) -> list:
    """Reuse the MCP slices, then cut the same text again near 14 KB.

    The MCP slices are sized for a 9 KB tool reply. A REST page can be larger,
    so neighbors are joined and split on the REST budget. Nothing is dropped.
    """
    whole = "".join(raw or "" for raw in (pages or []))
    if not whole.strip():
        return []
    return [part for part in _split_to_fit(whole) if (part or "").strip()]


def room_addon(room) -> dict:
    """Room fields for page 1 only, trimmed so they stay inside REST_ROOM_JSON."""
    if not isinstance(room, dict):
        return {}
    ordered = []
    if room.get("identify_hint"):
        ordered.append(("identify_hint", room.get("identify_hint")))
    if room.get("while_away"):
        ordered.append(("while_away", room.get("while_away")))
    if room.get("kind"):
        ordered.append(("kind", room.get("kind")))
    ordered.append(("step_zero", bool(room.get("step_zero"))))
    if room.get("text"):
        ordered.append(("room_text", room.get("text")))
    if room.get("others_block"):
        ordered.append(("others_block", room.get("others_block")))
    fields = {}
    for key, value in ordered:
        trial = dict(fields)
        trial[key] = value
        if _json_bytes(trial) <= REST_ROOM_JSON:
            fields = trial
            continue
        if not isinstance(value, str) or not value:
            break
        lo, hi, best = 0, len(value), ""
        while lo <= hi:
            mid = (lo + hi) // 2
            trial[key] = value[:mid]
            if _json_bytes(trial) <= REST_ROOM_JSON:
                best = value[:mid]
                lo = mid + 1
            else:
                hi = mid - 1
        if best:
            fields[key] = best
        break
    return fields


def select_rest_page(built, page=None, room=None) -> dict:
    """One page of the pack. Missing page means page 1, not the whole pack."""
    try:
        page_n = 1 if page in (None, "", 0) else int(page)
    except (TypeError, ValueError):
        page_n = 0
    if not isinstance(built, dict) or not built.get("ok"):
        err = ""
        if isinstance(built, dict):
            err = built.get("error") or ""
        err = err or "memory pack unavailable"
        out = {
            "ok": False,
            "error": err,
            "pack_error": err,
            "text": "",
            "page": 1,
            "total_pages": 0,
            "pages": [],
        }
        hint = (room or {}).get("identify_hint") if isinstance(room, dict) else ""
        if hint:
            out["identify_hint"] = hint
        return out
    slices = group_pages(built.get("pages") or [])
    if not slices:
        err = "empty step_zero pages"
        return {
            "ok": False,
            "error": err,
            "pack_error": err,
            "text": "",
            "page": 1,
            "total_pages": 0,
            "pages": [],
        }
    total = len(slices)
    if page_n < 1 or page_n > total:
        return {
            "ok": False,
            "error": "page out of range",
            "pack_error": "page out of range",
            "text": "",
            "page": page_n,
            "total_pages": total,
            "pages": [],
        }
    body = {"ok": True, "page": page_n, "total_pages": total, "text": slices[page_n - 1], "error": ""}
    if page_n == 1:
        body.update(room_addon(room))
    return body

"""Named-event dispatcher for installed skill hooks.

When an event fires, matching hook do-text is returned at once. This module
does not call a model. Short event names match here. A hook phrase of at least
12 characters that appears in the user message stays on cube_suggest.trigger_match.
"""
import json
import re
import sqlite3

LIVE = (
    "session_start", "before_reply", "after_reply", "task_end",
    "secret_in_text", "task_matches_skill_cube", "user_says_install",
    "user_wants_new_cube",
)
PLANNED = (
    "on_rework", "on_error", "on_task_start", "on_create", "on_install",
    "user_wants_cube_review", "cubes_used", "before_publish_big",
)
EVENTS = LIVE + PLANNED

_TOKEN = re.compile(r"[a-z0-9_]+")
_DO_CAP = 160
_CUE_CAP = 4


def normalize_hooks(raw):
    """Accept a list, a JSON list, or when-strings. Same shape as cube_suggest._whens."""
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if isinstance(raw, dict):
        raw = [raw]
    out = []
    for hook in raw or []:
        if isinstance(hook, str) and hook.strip():
            out.append({"when": hook.strip(), "do": ""})
        elif isinstance(hook, dict) and (hook.get("when") or hook.get("if")):
            out.append({
                "when": str(hook.get("when") or hook.get("if")).strip(),
                "do": str(hook.get("do") or hook.get("then") or "").strip(),
            })
    return out


def matches(when, event):
    """Exact name, or the event as a whole token inside the when-text."""
    event = (event or "").strip().lower()
    if not event or event not in EVENTS:
        return False
    text = (when or "").strip().lower()
    if not text:
        return False
    if text == event:
        return True
    return event in _TOKEN.findall(text)


def fire(event, hooks, cube_id=""):
    """Return do-text for hooks whose when matches event. No model call."""
    event = (event or "").strip().lower()
    out = []
    for hook in normalize_hooks(hooks):
        when = hook.get("when") or ""
        if not matches(when, event):
            continue
        item = {
            "event": event,
            "when": when,
            "do": hook.get("do") or "",
            "cube_id": cube_id or "",
        }
        if event == "before_publish_big":
            item["gate"] = True
            item["published"] = False
        out.append(item)
    return out


def rework_should_fire(write, read, after_checkpoint, first_create, same_burst_retry):
    """Material write after a checkpoint or a finished first create. Not a read. Not a same-burst retry."""
    if read or same_burst_retry or not write:
        return False
    return bool(after_checkpoint or first_create)


def fire_rework(hooks, cube_id="", write=False, read=False, after_checkpoint=False, first_create=False, same_burst_retry=False):
    if not rework_should_fire(write, read, after_checkpoint, first_create, same_burst_retry):
        return []
    return fire("on_rework", hooks, cube_id)


def session_field_cubes_used(ids):
    """The personal-memory cubes_used list is not the cubes_used event and does not change rank."""
    return {"source": "session_field", "fired": [], "rank_updated": False, "ids": list(ids or [])}


def cues_from_pack(pack, events):
    """Fire events against an already-loaded installed-skill pack."""
    cues = []
    for cube in pack or []:
        if not isinstance(cube, dict) or cube.get("missing"):
            continue
        cid = cube.get("cube_id") or ""
        for event in events or []:
            for hit in fire(event, cube.get("hooks") or [], cid):
                hit["do"] = (hit.get("do") or "")[:_DO_CAP]
                cues.append(hit)
                if len(cues) >= _CUE_CAP:
                    return cues
    return cues


def _follow_hooks(sc, cube_id):
    """Read-only superseded_by walk. Returns (live_id, hooks_raw) or (None, None)."""
    cid = cube_id
    for _ in range(8):
        row = sc.execute(
            "SELECT coalesce(status,''), links_json, hooks FROM cubes_new WHERE cube_id=?",
            (cid,),
        ).fetchone()
        if not row:
            return None, None
        if row[0] != "superseded":
            return cid, row[2] or ""
        try:
            nxt = (json.loads(row[1] or "{}") or {}).get("superseded_by")
        except Exception:
            nxt = None
        if not nxt:
            return cid, row[2] or ""
        cid = nxt
    return cid, ""


def cues_for_installed(uid, events, chain_id="session"):
    """Read installed hooks and fire. Read-only. Empty on any error. No model call."""
    if not uid or not events:
        return []
    try:
        from app.chain_skills import SHARED_DB, _norm_chain
        from app.memory_v2 import db_path as user_db
    except Exception:
        return []
    chain = _norm_chain(chain_id)
    try:
        uc = sqlite3.connect("file:%s?mode=ro" % user_db(uid), uri=True, timeout=5)
    except Exception:
        return []
    try:
        try:
            rows = uc.execute(
                "SELECT cube_id FROM chain_skills WHERE chain_id=? ORDER BY attached_at",
                (chain,),
            ).fetchall()
        except sqlite3.Error:
            rows = []
    finally:
        uc.close()
    if not rows:
        return []
    try:
        sc = sqlite3.connect("file:%s?mode=ro" % SHARED_DB, uri=True, timeout=5)
    except Exception:
        return []
    pack = []
    try:
        for (cid,) in rows:
            live, hooks = _follow_hooks(sc, cid)
            if live:
                pack.append({"cube_id": live, "hooks": hooks or ""})
    except sqlite3.Error:
        return []
    finally:
        sc.close()
    return cues_from_pack(pack, events)

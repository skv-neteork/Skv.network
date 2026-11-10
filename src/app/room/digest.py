"""While-away digest. No LLM. The cursor moves only after a successful serialize."""
import re
from datetime import timedelta

from app.room.clock import as_dt, iso, parse_iso
from app.room.copy import VISIBLE
from app.room.events import list_events
from app.room.schema import ensure

_OVERFLOW = "+%d ещё с ev:%s — memory_search(since=%s, lines=all)"
_MSK_HOURS = 3   # Europe/Moscow, no DST
_ID_LIKE = re.compile(r"^\S*(?:remember|ev|evt)_\d{6,}$")


def short_id(event_id):
    """Event ids are stored as <account>::<id>; people and agents see the part after ::."""
    return str(event_id or "").split("::")[-1]


def _hhmm_msk(created_at):
    dt = parse_iso(created_at)
    if not dt:
        return "--:--"
    return (dt + timedelta(hours=_MSK_HOURS)).strftime("%H:%M")


def _entry(agent, created_at, gist, event_id):
    """One stable line per foreign move: <agent> HH:MM MSK: <gist> [ev:id@agent]. The citation tail is never cut."""
    ev = short_id(event_id)
    head = "%s %s MSK: " % (agent, _hhmm_msk(created_at))
    tail = " [ev:%s@%s]" % (ev, agent)
    g = re.sub(r"\s+", " ", gist or "").strip()
    if not g or _ID_LIKE.match(g):
        g = "ход"
    room = 140 - len(head) - len(tail)
    if room < 12:
        room = 12
    if len(g) > room:
        g = g[: room - 1].rstrip() + "…"
    return head + g + tail


def cursor_of(conn, actor_id, chain_id):
    ensure(conn)
    r = conn.execute(
        "SELECT delivered_upto FROM agent_cursors WHERE actor_id=? AND chain_id=?",
        (actor_id, chain_id),
    ).fetchone()
    return int(r[0]) if r else 0


def commit_cursor(conn, actor_id, chain_id, upto, now=None):
    if upto is None:
        return cursor_of(conn, actor_id, chain_id)
    cur = cursor_of(conn, actor_id, chain_id)
    upto = max(cur, int(upto))
    conn.execute(
        """INSERT INTO agent_cursors (actor_id, chain_id, delivered_upto, updated_at) VALUES (?,?,?,?)
           ON CONFLICT(actor_id, chain_id) DO UPDATE SET delivered_upto=excluded.delivered_upto, updated_at=excluded.updated_at""",
        (actor_id, chain_id, upto, iso(as_dt(now))),
    )
    conn.commit()
    return upto


def _mine(conn, actor_id, chain_id, now):
    paths, tasks = set(), set()
    now_dt = as_dt(now)
    for r in conn.execute(
        "SELECT path, lease_until, released_at FROM resource_claims WHERE chain_id=? AND actor_id=?",
        (chain_id, actor_id),
    ):
        if r[2]:
            continue
        exp = parse_iso(r[1])
        if exp and exp >= now_dt:
            paths.add(r[0])
    cols = {c[1] for c in conn.execute("PRAGMA table_info(board_items)")}
    if "claimed_by" in cols:
        for r in conn.execute(
            "SELECT item_id, claimed_by, created_by, lease_until FROM board_items WHERE removed=0"
        ):
            if r[1] == actor_id or r[2] == actor_id:
                exp = parse_iso(r[3]) if r[1] == actor_id else now_dt
                if r[1] != actor_id or (exp and exp >= now_dt) or r[2] == actor_id:
                    tasks.add(r[0])
    since = iso(now_dt - timedelta(hours=24))
    for r in conn.execute(
        "SELECT path, task_id, at FROM room_touches WHERE chain_id=? AND actor_id=? AND at>=?",
        (chain_id, actor_id, since),
    ):
        if r[0]:
            paths.add(r[0])
        if r[1]:
            tasks.add(r[1])
    return paths, tasks


def _clip(line):
    line = re.sub(r"\s+", " ", line).strip()
    if len(line) <= 140:
        return line
    return line[:137] + "..."


def _is_conflict(e, paths, tasks, actor_id):
    if not e.get("actor_agent_id") or e.get("actor_agent_id") == actor_id:
        return False
    if e.get("ev_kind") == "file_change" and e.get("path") and e["path"] in paths:
        return True
    if e.get("ev_kind") == "claim" and e.get("task_id") and e["task_id"] in tasks:
        return True
    return False


def _agg_files(events):
    groups = []
    index = {}
    for e in events:
        key = e.get("path") or e.get("event_id")
        if key in index and e.get("path"):
            groups[index[key]].append(e)
        else:
            index[key] = len(groups)
            groups.append([e])
    lines = []
    for g in groups:
        ids = [e["id"] for e in g]
        evs = [e["event_id"] for e in g]
        if len(g) == 1:
            text = _entry(g[0]["actor_agent_id"], g[0].get("created_at"), g[0].get("gist") or "FILE_CHANGE", g[0]["event_id"])
        else:
            text = "FILE_CHANGE %s ×%d [ev:%s..%s]" % (g[0].get("path") or "?", len(g), short_id(evs[0]), short_id(evs[-1]))
        lines.append({"text": _clip(text), "ids": ids, "evs": evs, "conflict": False})
    return lines


def _line_for(e, conflict=False):
    agent = e.get("actor_agent_id") or "?"
    gist = e.get("gist") or e.get("ev_kind") or ""
    if conflict:
        text = _clip("⚠ КОНФЛИКТ %s [ev:%s@%s]" % (gist, short_id(e["event_id"]), agent))
    else:
        text = _entry(agent, e.get("created_at"), gist, e["event_id"])
    return {"text": text, "ids": [e["id"]], "evs": [e["event_id"]], "conflict": conflict}


def build_while_away(conn, actor_id, key_id, chain_id, role="assistant", now=None):
    """Assemble the digest. Does not move the cursor."""
    ensure(conn)
    role = role if role in VISIBLE else "assistant"
    allowed = VISIBLE[role]
    cur = cursor_of(conn, actor_id, chain_id)
    paths, tasks = _mine(conn, actor_id, chain_id, now)
    window = []
    for e in list_events(conn, chain_id):
        if e["id"] <= cur:
            continue
        if not e.get("actor_agent_id"):
            continue
        if e.get("actor_agent_id") == actor_id and (not key_id or e.get("key_id") == key_id):
            continue
        if e.get("ev_kind") == "turn" or e.get("ev_kind") in allowed:
            window.append(e)
    if not window:
        return {"text": None, "lines": [], "proposed_upto": cur, "covered": [], "event_ids": [], "unshown_event_ids": []}
    conflicts, directed, results, changes, raws = [], [], [], [], []
    for e in window:
        if _is_conflict(e, paths, tasks, actor_id):
            conflicts.append(e)
        elif e.get("ev_kind") in ("human_directive", "handoff") and (not e.get("target_actor") or e.get("target_actor") == actor_id):
            directed.append(e)
        elif e.get("ev_kind") in ("result", "blocked"):
            results.append(e)
        elif e.get("ev_kind") in ("claim", "file_change"):
            changes.append(e)
        elif e.get("ev_kind") == "turn":
            raws.append(e)
    # a conflict is not also listed in its plain bucket
    conflict_ids = {e["id"] for e in conflicts}
    directed = [e for e in directed if e["id"] not in conflict_ids]
    results = [e for e in results if e["id"] not in conflict_ids]
    changes = [e for e in changes if e["id"] not in conflict_ids]
    files = [e for e in changes if e.get("ev_kind") == "file_change"]
    claims = [e for e in changes if e.get("ev_kind") != "file_change"]
    ordered = (
        [_line_for(e, True) for e in conflicts]
        + [_line_for(e) for e in directed]
        + [_line_for(e) for e in results]
        + [_line_for(e) for e in claims]
        + _agg_files(files)
    )
    for e in raws:
        # one line per foreign turn (agent, MSK time, one-phrase gist, citation)
        ordered.append({
            "text": _entry(e.get("actor_agent_id") or "?", e.get("created_at"), e.get("gist") or e.get("essence") or "", e["event_id"]),
            "ids": [e["id"]], "evs": [e["event_id"]], "conflict": False,
        })
    shown, used = [], set()
    budget = 700

    def weigh(lines):
        return sum(len(x["text"]) + 1 for x in lines)

    for item in ordered:
        fresh = [i for i in item["ids"] if i not in used]
        if not fresh and item["ids"]:
            continue
        room_for_more = False
        for later in ordered:
            if later is item:
                continue
            if any(i not in used and i not in item["ids"] for i in later["ids"]):
                room_for_more = True
                break
        limit = 4 if room_for_more else 5
        if len(shown) >= limit:
            break
        if weigh(shown) + len(item["text"]) + 1 > budget:
            break
        shown.append(item)
        used.update(item["ids"])
    all_ids = [e["id"] for e in window]
    unshown = [e for e in window if e["id"] not in used]
    lines = [s["text"] for s in shown]
    if unshown:
        if len(lines) >= 5:
            # keep conflicts; drop the last non-conflict to fit the overflow line
            for i in range(len(shown) - 1, -1, -1):
                if not shown[i]["conflict"]:
                    dropped = shown.pop(i)
                    used.difference_update(dropped["ids"])
                    break
            else:
                dropped = shown.pop()
                used.difference_update(dropped["ids"])
            lines = [s["text"] for s in shown]
            unshown = [e for e in window if e["id"] not in used]
        nxt = min(unshown, key=lambda e: e["id"])
        lines.append(_clip(_OVERFLOW % (len(unshown), short_id(nxt["event_id"]), short_id(nxt["event_id"]))))
        if len(lines) > 5:
            lines = lines[:4] + [lines[-1]]
    text = "\n".join(lines)
    if len(text) > 700:
        text = text[:700]
    proposed = (min(e["id"] for e in unshown) - 1) if unshown else max(all_ids)
    if proposed < cur:
        proposed = cur
    covered = sorted(used)
    evs = []
    for s in shown:
        evs.extend(short_id(x) for x in s["evs"])
    unshown_event_ids = [short_id(e["event_id"]) for e in unshown]
    return {
        "text": text or None,
        "lines": lines,
        "proposed_upto": proposed,
        "covered": covered,
        "event_ids": evs,
        "unshown_event_ids": unshown_event_ids,
    }


def deliver(conn, serialize, actor_id, key_id, chain_id, role="assistant", now=None):
    """Move the cursor only when serialize returns without raising."""
    built = build_while_away(conn, actor_id, key_id, chain_id, role, now)
    before = cursor_of(conn, actor_id, chain_id)
    try:
        serialize(built)
    except Exception:
        return {**built, "committed": False, "cursor": before}
    if not built.get("text"):
        return {**built, "committed": False, "cursor": before}
    upto = commit_cursor(conn, actor_id, chain_id, built["proposed_upto"], now)
    return {**built, "committed": True, "cursor": upto}

"""Own lane, other agents in the third person, unsigned legacy history."""
import re

from app.room.copy import EMPTY_LANE, LEGACY_HEADER, OTHERS_HEADER, VISIBLE
from app.room.events import legacy_rows, list_events

_FIRST = re.compile(r"(?i)\b(я|меня|мне|мой|моя|мои|моё|мое)\b")
_CITE = re.compile(r"\[ev:([^\]\s]+)\]")


def split_cite(token):
    if "@" in token:
        ev, agent = token.split("@", 1)
        return ev, agent
    return token, None


def third_person(agent, gist):
    g = _FIRST.sub(agent, gist or "")
    g = re.sub(r"\s+", " ", g).strip()
    line = "[ev:%s@%s] агент %s — %s" % ( "", agent, agent, g)  # placeholder, caller fills ev
    return g


def other_line(event):
    agent = event.get("actor_agent_id") or "?"
    ev = event.get("event_id") or ""
    g = third_person(agent, event.get("gist") or event.get("essence") or event.get("ev_kind") or "ход")
    line = "[ev:%s@%s] агент %s — %s" % (ev, agent, agent, g)
    return line[:140]


def own_line(event):
    ev = event.get("event_id") or ""
    g = event.get("gist") or event.get("essence") or event.get("ev_kind") or ""
    return ("[ev:%s] %s" % (ev, g)).strip()[:140]


def _is_self(event, actor_id, key_id):
    if not event.get("actor_agent_id"):
        return False
    if key_id and event.get("key_id") and event.get("key_id") != key_id:
        return False
    return event.get("actor_agent_id") == actor_id


def visible_other(event, role):
    if event.get("ev_kind") == "turn":
        return False
    return event.get("ev_kind") in VISIBLE.get(role or "assistant", VISIBLE["assistant"])


def others_block(events, actor_id, key_id, role):
    lines = []
    for e in events:
        if _is_self(e, actor_id, key_id) or not e.get("actor_agent_id"):
            continue
        if e.get("ev_kind") == "turn":
            continue
        if not visible_other(e, role):
            continue
        lines.append(other_line(e))
    if not lines:
        return ""
    return OTHERS_HEADER + "\n" + "\n".join(lines)


def legacy_block(conn, room_legacy):
    rows = list(room_legacy or [])
    rows.extend(legacy_rows(conn, 5))
    lines = []
    seen = set()
    for r in rows:
        ev = r.get("event_id") or ""
        if not ev or ev in seen:
            continue
        seen.add(ev)
        g = (r.get("gist") or r.get("essence") or "").strip()
        lines.append(("[ev:%s] %s" % (ev, g)).strip()[:140])
        if len(lines) >= 5:
            break
    if not lines:
        return ""
    return LEGACY_HEADER + "\n" + "\n".join(lines)


def facts_for(conn, actor_id, key_id, chain_id, role="assistant", digest_ids=None):
    """Facts with actor and is_self. An ev already covered by the digest is not repeated."""
    digest_ids = set(digest_ids or [])
    events = list_events(conn, chain_id)
    facts = []
    legacy = []
    for e in events:
        if e["event_id"] in digest_ids:
            continue
        self_ = _is_self(e, actor_id, key_id)
        if not e.get("actor_agent_id"):
            legacy.append(e)
            continue
        if not self_ and e.get("ev_kind") == "turn":
            continue
        if not self_ and not visible_other(e, role):
            continue
        cite = own_line(e) if self_ else other_line(e)
        facts.append({
            "ev": e["event_id"],
            "actor": e.get("actor_agent_id"),
            "is_self": bool(self_),
            "fact": cite,
            "kind": e.get("ev_kind"),
        })
    own = [e for e in events if _is_self(e, actor_id, key_id)]
    return {
        "actor": actor_id,
        "facts": facts,
        "own_lines": [own_line(e) for e in own],
        "own_empty": EMPTY_LANE if not own else "",
        "others_block": others_block(events, actor_id, key_id, role),
        "legacy_block": legacy_block(conn, legacy),
    }


def check_citations(text, owners):
    """Both [ev:id] and [ev:id@agent]. @agent must be the server actor. owners: event_id -> actor or None."""
    bad = []
    for tok in dict.fromkeys(_CITE.findall(text or "")):
        if tok.strip().lower() in ("id", "ids", "..."):
            continue
        ev, agent = split_cite(tok.strip())
        if ev not in owners:
            bad.append(tok)
            continue
        if agent is not None and owners.get(ev) != agent:
            bad.append(tok)
    return bad


def owners_map(conn, chain_id):
    return {e["event_id"]: e.get("actor_agent_id") for e in list_events(conn, chain_id)}

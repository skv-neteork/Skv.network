"""T84 turn pack: fact diet, date window, duty close-lines, desk, next_step.

Pure helpers plus a small sidecar (ids and hashes only). finish() never raises.
The live constitution and the live profile are not written here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import date, datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    _MSK = ZoneInfo("Europe/Moscow")
except Exception:  # pragma: no cover
    _MSK = None

_DEFAULT_DB = "/data/skv/metadata_store/turn_pack.db"
_SESSION_TAIL = 50
_WINDOW_CAP = 5
_SEEN_CAP = 80

_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
_GH = re.compile(r"github\.com/\S+", re.I)
_SURGE = re.compile(r"nssurge|surge\.sh", re.I)
_MASKED = re.compile(r"https?://\S*(?:\*{3,}|\[secret\]|sk-\*{2,})", re.I)
_REF = re.compile(r"\bt(\d{1,7})u\b", re.I)
_CORE = "AUTHOR CUBE CORE ("
_CUBE_ID = re.compile(r"cube_[0-9a-f]{8,}")
_ISO = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_DMY = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b")
_MON = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
_NAMED = re.compile(
    r"\b(\d{1,2})\s+([A-Za-zА-Яа-яё]{3,})\s+(20\d{2})\b",
    re.I,
)
_TIME_PHRASE = re.compile(
    r"(?i)\b("
    r"yesterday|today|tomorrow|day before yesterday|the day before|a week ago|last week|"
    r"вчера|сегодня|завтра|позавчера|неделю назад|на прошлой неделе"
    r")\b"
)
_BOILER = re.compile(r"(?i)^(ok|test|n/?a|none|todo|tbd|see above|as discussed|note)\.?$")

# One line each: when to use + a minimal example. Keep this aligned with B/C/I.
DESK_LINES = (
    "memory_search: search the event, not the question. Yesterday (MSK) is since=until=that day. memory_search(query=\"gift\", since=\"YYYY-MM-DD\", until=\"YYYY-MM-DD\").",
    "memory_recall_later: when facts are weak, deep search in the same window, then memory_recall_status(job_id). memory_recall_later(query=\"...\", since=\"A\", until=\"B\").",
    "board: board_act(action=\"start\"|\"done\"|\"park\", item_id=\"...\"). A \"looks done, close?\" line is a choice, not a close.",
    "critical: turn(critical=\"lasting fact\"). A critical that belongs to an L1/L2 is a line inside that record: CRITICAL: title [ev:id].",
    "L1/L2: turn(l1_summary=\"stages\", source_event_ids=\"ev,ev\") and l2_summary with those source ids. Critical lines sit inside the record.",
    "cubes: cube_search(query) / cube_get(id) / cube_install only after a yes / cube_vote. Nothing new: duty=cube_nothing + reason.",
    "profile: lasting rules via turn(profile=[{\"op\":\"add\",\"kind\":\"rule\",\"text\":\"...\"}]).",
    "vault: secrets only. turn(sensitive=\"exact\") or vault_inject. Never paste a secret into chat, cubes, or profile.",
    "drive: drive_list / drive_read / drive_put / drive_sync on this memory line.",
)


def _hash(obj):
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:12]


def _user_key(user):
    return hashlib.sha256((user or "").strip().lower().encode("utf-8", "replace")).hexdigest()[:16]


def tok(obj):
    """Same token estimate as turn_diet._tok: json length // 4, at least 1."""
    raw = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    return max(1, len(raw) // 4)


def msk_today(now=None):
    if isinstance(now, date) and not isinstance(now, datetime):
        return now
    if now is None:
        if _MSK is not None:
            return datetime.now(_MSK).date()
        return datetime.utcnow().date()
    if isinstance(now, datetime):
        if now.tzinfo is None and _MSK is not None:
            return now.replace(tzinfo=_MSK).date()
        if now.tzinfo is not None and _MSK is not None:
            return now.astimezone(_MSK).date()
        return now.date()
    return now


def _iso(d):
    return d.isoformat()


def _parse_explicit(text, today):
    m = _ISO.search(text or "")
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = _NAMED.search(text or "")
    if m:
        mon = _MON.get(m.group(2).lower())
        if mon:
            try:
                return date(int(m.group(3)), mon, int(m.group(1)))
            except ValueError:
                pass
    m = _DMY.search(text or "")
    if m:
        dd, mm, yy = int(m.group(1)), int(m.group(2)), m.group(3)
        if yy:
            year = int(yy)
            if year < 100:
                year += 2000
        else:
            year = today.year
        try:
            if 1 <= mm <= 12 and 1 <= dd <= 31:
                return date(year, mm, dd)
        except ValueError:
            return None
    return None


def date_window(message, today=None):
    """MSK window for a time phrase. None when the message has no time reference.

    yesterday / позавчера: that calendar day (since=until).
    a week ago / неделю назад: today-7 ± 3 days.
    An explicit date: that day ± 1, rank false (14.11 decision).
    """
    today = msk_today(today)
    text = message or ""
    low = text.lower()
    explicit = _parse_explicit(text, today)
    if re.search(r"\byesterday\b|\bвчера\b", low) and explicit is None:
        day = today - timedelta(days=1)
        return {"label": "yesterday", "since": _iso(day), "until": _iso(day), "rank": False}
    if re.search(r"позавчера|day before", low) and explicit is None:
        day = today - timedelta(days=2)
        return {"label": "day_before", "since": _iso(day), "until": _iso(day), "rank": False}
    if re.search(r"a week ago|неделю назад|last week|на прошлой неделе", low) and explicit is None:
        center = today - timedelta(days=7)
        return {
            "label": "week_ago",
            "since": _iso(center - timedelta(days=3)),
            "until": _iso(center + timedelta(days=3)),
            "rank": True,
        }
    if explicit is not None:
        return {
            "label": "date",
            "since": _iso(explicit - timedelta(days=1)),
            "until": _iso(explicit + timedelta(days=1)),
            "rank": False,
        }
    return None


def strip_time_phrases(text):
    t = _TIME_PHRASE.sub(" ", text or "")
    t = _ISO.sub(" ", t)
    t = _NAMED.sub(" ", t)
    t = _DMY.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def is_junk_fragment(text):
    """Email lines, bare links, github/nssurge links, masked-key URLs. Not a fact."""
    t = re.sub(r"\s+", " ", text or "").strip()
    t = re.sub(r"(?i)^\[critical\]\s*", "", t)
    t = re.sub(r"(?i)^CRITICAL:\s*", "", t).strip()
    if not t:
        return True
    if _SURGE.search(t) or _MASKED.search(t):
        return True
    if _GH.search(t) and len(t) < 240:
        return True
    bare = t.strip(" .,<>\"'")
    if _URL.fullmatch(bare):
        return True
    em = _EMAIL.search(t)
    if em:
        rest = (t[:em.start()] + " " + t[em.end():])
        rest = re.sub(r"(?i)\b(email|e-mail|mail|почта|address)\b", " ", rest)
        rest = re.sub(r"[\s:;,|\-]+", " ", rest).strip()
        if len(rest) < 24:
            return True
    return False


def is_boilerplate_critical(text):
    s = re.sub(r"(?i)^(?:\[critical\]\s*|CRITICAL:\s*)", "", text or "").strip()
    if len(s) < 8:
        return True
    return bool(_BOILER.fullmatch(s))


def _fact_time(fact):
    return str((fact or {}).get("time") or "")


def _newer(a, b):
    """True when fact a is newer than fact b. Missing time loses to a real time; else later in the list wins via the caller."""
    ta, tb = _fact_time(a), _fact_time(b)
    if ta and tb and ta != tb:
        return ta > tb
    if ta and not tb:
        return True
    if tb and not ta:
        return False
    return False


def dedupe_facts(facts):
    """One row per ev. Keep the newest time. Stable order of first appearance."""
    best = {}
    order = []
    for i, f in enumerate(facts or []):
        if not isinstance(f, dict):
            continue
        ev = str(f.get("ev") or "")
        key = ev or ("#%d" % i)
        prev = best.get(key)
        if prev is None:
            best[key] = (i, f)
            order.append(key)
            continue
        if _newer(f, prev[1]) or (not _newer(prev[1], f) and _fact_time(f) == _fact_time(prev[1])):
            # equal time: the later copy is the newest version
            if _newer(f, prev[1]) or _fact_time(f) == _fact_time(prev[1]):
                best[key] = (i, f)
    out = []
    seen = set()
    for key in order:
        if key in seen:
            continue
        seen.add(key)
        out.append(best[key][1])
    return out


def _day_of(time_s):
    m = re.search(r"(20\d{2}-\d{2}-\d{2})", str(time_s or ""))
    return m.group(1) if m else ""


def _in_window(fact, window):
    """A full timestamp uses the MSK span of since/until. A date-only stamp stays on the calendar day."""
    if not window:
        return False
    ts = _fact_time(fact).strip()
    if not ts:
        return False
    since = str(window.get("since") or "")
    until = str(window.get("until") or "")
    if len(ts) <= 10:
        day = _day_of(ts)
        if not day:
            return False
        return (not since or since[:10] <= day) and (not until or day <= until[:10])
    try:
        from app.search_window import msk_bounds
        start = msk_bounds(since[:10])[0] if len(since) >= 10 else None
        end = msk_bounds(until[:10])[1] if len(until) >= 10 else None
    except Exception:
        start = end = None
    stamp = ts[:16]
    if start or end:
        if start and stamp < start:
            return False
        if end and stamp >= end:
            return False
        return True
    day = _day_of(ts)
    if not day:
        return False
    return (not since or since[:10] <= day) and (not until or day <= until[:10])


def _is_critical_fact(fact):
    layer = str(fact.get("layer") or "").lower()
    text = str(fact.get("fact") or "")
    return layer == "critical" or text.lower().startswith("[critical]") or text.startswith("CRITICAL:")


def select_facts(facts, message="", recent_ids=None, seen_fact_ids=None, compressed=False, compressed_at="", today=None, window_cap=_WINDOW_CAP):
    """Dedupe, drop junk, apply the session cutoff and the novelty filter.

    Default (no compressed flag): drop ids in recent_ids (the last ~50 of this session).
    compressed=true: the agent lost that window, so those ids may return.
    compressed_at: drop facts whose time is at or after that stamp.
    A time-only question keeps facts inside the date window (capped) instead of
    requiring the word "yesterday" to match the fact.
    """
    rows = dedupe_facts(facts)
    kept = []
    for f in rows:
        if is_junk_fragment(f.get("fact") or ""):
            continue
        if _is_critical_fact(f) and is_boilerplate_critical(f.get("fact") or ""):
            continue
        kept.append(f)
    recent = {str(x).split("::")[-1] for x in (recent_ids or []) if x}
    recent |= {str(x) for x in (recent_ids or []) if x}
    if not compressed and not (compressed_at or "").strip():
        kept = [f for f in kept if str(f.get("ev") or "") not in recent and str(f.get("ev") or "").split("::")[-1] not in recent]
    if (compressed_at or "").strip():
        stamp = str(compressed_at).strip()
        def _after(f):
            ts = _fact_time(f)
            return bool(ts) and ts >= stamp[:19]
        kept = [f for f in kept if not _after(f)]
    if not compressed and not (compressed_at or "").strip():
        seen = {str(x).split("::")[-1] for x in (seen_fact_ids or []) if x}
        seen |= {str(x) for x in (seen_fact_ids or []) if x}
        kept = [f for f in kept if str(f.get("ev") or "") not in seen and str(f.get("ev") or "").split("::")[-1] not in seen]
    window = date_window(message, today=today)
    topic = strip_time_phrases(message or "")
    try:
        from app.turn_context import content_words, on_topic
        words = content_words(topic)
    except Exception:
        words, on_topic = [], None

    def _self(f):
        return bool(f.get("is_self"))

    def _keep(f):
        # The 2400 compact pack already chose this row. A second topic cut would drop it.
        if f.get("pack2400"):
            return True
        if _self(f):
            return False
        if window and _in_window(f, window):
            return True
        if words and on_topic is not None:
            return bool(on_topic(topic, f.get("fact") or ""))
        return False

    if words and on_topic is not None:
        inside, outside = [], []
        for f in kept:
            if not _keep(f):
                continue
            if window and _in_window(f, window):
                inside.append(f)
            else:
                outside.append(f)
        kept = inside[:window_cap] + outside
    elif window:
        kept = [f for f in kept if _keep(f)][:window_cap]
    for f in kept:
        if isinstance(f, dict):
            f.pop("pack2400", None)
    return kept


def system_skip_refs(recap):
    """Client refs marked skip=system are not chat messages (voice-call end and the like)."""
    nums = []
    items = []
    if isinstance(recap, dict):
        items = [recap]
    elif isinstance(recap, list):
        items = [x for x in recap if isinstance(x, dict)]
    elif isinstance(recap, str) and recap.strip().startswith(("{", "[")):
        try:
            parsed = json.loads(recap)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            items = [parsed]
        elif isinstance(parsed, list):
            items = [x for x in parsed if isinstance(x, dict)]
    for x in items:
        if str(x.get("skip") or "").strip().lower() != "system":
            continue
        ref = str(x.get("ref") or "")
        m = _REF.search(ref) or re.fullmatch(r"\s*(\d{1,7})\s*", ref)
        if m:
            nums.append(int(m.group(1)))
    return nums


def nest_critical(records, criticals, rows=None):
    """Put critical marks inside L1/L2 via memory_pack888._attach_critical.

    Returns (records, placed short ev ids). When rows do not map, a critical is
    attached only if the L1/L2 text cites its ev. The line format is the helper's.
    """
    from app.memory_pack888 import _attach_critical
    rows = dict(rows or {})
    cited = not rows
    n = 1
    for name in ("l2", "l1", "raw"):
        block = records.setdefault(name, {"included": []})
        for rec in block.get("included") or []:
            if "row_lo" not in rec or "row_hi" not in rec:
                rec["row_lo"] = rec["row_hi"] = n
            n += 1
            if not cited:
                continue
            text = "%s %s" % (rec.get("body") or "", rec.get("text") or "")
            for c in criticals or []:
                ev = str(c.get("event_id") or "")
                short = ev.split("::")[-1]
                if short and short in text:
                    rows[ev] = rec["row_lo"]
    _attach_critical(records, list(criticals or []), rows)
    placed = set()
    for name in ("l2", "l1", "raw"):
        for rec in records.get(name, {}).get("included") or []:
            for line in rec.get("critical_lines") or []:
                m = re.search(r"\[ev:([^\]]+)\]", str(line))
                if m:
                    placed.add(m.group(1))
    return records, placed


def _blob(duty):
    if isinstance(duty, str):
        return duty
    if isinstance(duty, dict):
        return " ".join(str(duty.get(k) or "") for k in ("id", "kind", "do", "note", "close", "text", "rules"))
    return str(duty or "")


def _is_summary_copy(duty, summary_due):
    if summary_due in (None, "", [], {}):
        return False
    if duty == summary_due:
        return True
    if isinstance(duty, dict) and duty.get("id") in ("summary_due", "l1_overdue"):
        return True
    if isinstance(duty, str) and isinstance(summary_due, str) and duty.strip() == summary_due.strip():
        return True
    if isinstance(duty, str) and isinstance(summary_due, dict):
        ask = str(summary_due.get("l1") or "")
        if ask and ask[:80] in duty:
            return True
    return False


def dedupe_summary_due(resp):
    """Keep the summary_due field. Drop the same ask from duties."""
    sd = resp.get("summary_due")
    if not sd:
        return
    duties = []
    if isinstance(sd, dict):
        sd = dict(sd)
    for d in resp.get("duties") or []:
        if not _is_summary_copy(d, sd):
            duties.append(d)
            continue
        if isinstance(d, dict) and isinstance(sd, dict):
            for k in ("l1", "l1_pending", "l1_source_event_ids", "l2"):
                if d.get(k) and not sd.get(k):
                    sd[k] = d.get(k)
            if d.get("do") and not sd.get("l1"):
                sd["l1"] = d.get("do")
    resp["duties"] = duties
    resp["summary_due"] = sd


def _duty_kind(duty):
    b = _blob(duty).lower()
    if "unsealed_gap" in b:
        return "unsealed"
    if "cube" in b:
        return "cube"
    if "vote" in b:
        return "vote"
    if "l2" in b:
        return "l2"
    if "l1" in b or "summary" in b:
        return "l1"
    if "missed" in b:
        return "missed"
    return "other"


def _is_vote_reminder(duty):
    b = _blob(duty).lower()
    return "vote" in b and any(x in b for x in ("vote_nothing", "rule vote", "cube_vote", "проголосуй"))


def _is_l2_due(duty):
    b = _blob(duty).lower()
    return "l2" in b and any(x in b for x in ("due", "summary", "rule l2", "l2_summary"))


def _is_textbook(duty):
    b = _blob(duty).strip()
    return b.startswith("RULE ") and "MANDATORY" not in b


def _is_cube_duty(duty):
    b = _blob(duty).lower()
    return any(x in b for x in ("cube_harvest", "cube duty", "rule experience cube", "author cube core", "task cube", "cube_nothing"))


def _close_line(duty, n):
    kind = _duty_kind(duty)
    if kind == "cube":
        return "куб: опубликуй или cube_nothing, висит %d хода" % n
    if kind == "vote":
        return "vote: cube_vote или vote_nothing, висит %d хода" % n
    if kind == "l1":
        return "L1: пришли l1_summary и source_event_ids, висит %d хода" % n
    if kind == "l2":
        return "L2: пришли l2_summary, висит %d хода" % n
    if kind == "missed":
        return "missed: пришли recap по каждому ref, висит %d хода" % n
    if kind == "unsealed":
        return "previous answer sent without seal: send recap"
    return "закрой это действие, висит %d хода" % n


def _shrink_core(text, core_sent):
    """CORE textbook once per session, then one line plus the cube id."""
    if _CORE not in (text or ""):
        return text, core_sent
    if not core_sent:
        return text, True
    m = _CUBE_ID.search(text)
    cid = m.group(0) if m else "cube"
    head = text.split(_CORE)[0].rstrip()
    line = "cube %s" % cid
    return (head + "\n" + line).strip() if head else line, True


def _nothing_open(resp, duties):
    if resp.get("summary_due"):
        return False
    for d in duties:
        b = _blob(d).lower()
        if any(k in b for k in ("missed_turns", "cube_harvest", "task cube", "profile_", "l1_overdue", "mandatory", "author cube core")):
            return False
    return True


def shape_duties(duties, summary_due=None, cube_applied=False, l1_just_saved=False, closed=None, trigger_id="", open_counts=None, core_sent=False):
    """Drop untriggered reminders. First line of what remains is the close action and the open counter."""
    closed = closed or {}
    counts = dict(open_counts or {})
    resp_like = {"summary_due": summary_due, "duties": list(duties or [])}
    dedupe_summary_due(resp_like)
    raw = list(resp_like["duties"])
    quiet = _nothing_open(resp_like, raw)
    out = []
    sent = bool(core_sent)
    trig = str(trigger_id or "")
    for d in raw:
        blob = _blob(d)
        if _is_vote_reminder(d) and not cube_applied:
            continue
        if l1_just_saved and _is_l2_due(d):
            continue
        if quiet and _is_textbook(d):
            continue
        kind = _duty_kind(d)
        if kind == "other":
            out.append(d)
            continue
        if kind == "cube" and _is_cube_duty(d):
            if trig and closed.get((trig, "cube")):
                continue
            if any(closed.get((ev, "cube")) and ev in blob for ev in _evs(blob)):
                continue
        if kind == "vote" and trig and closed.get((trig, "vote")):
            continue
        counts[kind] = int(counts.get(kind) or 0) + 1
        n = counts[kind]
        action = _close_line(d, n)
        if isinstance(d, str):
            body, sent = _shrink_core(d, sent)
            out.append(action + "\n" + body if body else action)
        elif isinstance(d, dict):
            item = dict(d)
            for fld in ("do", "note", "text"):
                if isinstance(item.get(fld), str):
                    item[fld], sent = _shrink_core(item[fld], sent)
            item["close"] = action
            if item.get("do"):
                item["do"] = action + " " + str(item["do"])
            out.append(item)
        else:
            out.append(action)
    return out, counts, sent, resp_like.get("summary_due")


def _evs(text):
    return re.findall(r"remember_\d+|grokexp_[0-9a-f]+", text or "")


def note_closed(db, user, trigger_id, kind):
    """Record cube_nothing / vote_nothing for one trigger (an L1 ev id). Ids only."""
    if not db or not trigger_id or kind not in ("cube", "vote"):
        return
    try:
        c = _db(db)
        try:
            c.execute(
                "insert or replace into tp_closed(user_key, trigger_id, kind, t) values(?,?,?,?)",
                (_user_key(user), str(trigger_id)[:80], kind, _now()),
            )
            c.commit()
        finally:
            c.close()
    except Exception:
        return


def closed_map(db, user):
    out = {}
    if not db:
        return out
    try:
        c = _db(db)
        try:
            for trig, kind in c.execute("select trigger_id, kind from tp_closed where user_key=?", (_user_key(user),)):
                out[(trig, kind)] = True
        finally:
            c.close()
    except Exception:
        return {}
    return out


def judge_keep_direct(evidence, query, missing=""):
    """A direct overlap in the top 5 stays selected even if the model says there is no event."""
    try:
        from app.turn_context import on_topic
    except Exception:
        return evidence, missing
    changed = False
    for item in list(evidence or [])[:5]:
        if not isinstance(item, dict) or item.get("selected"):
            continue
        if on_topic(query or "", item.get("text") or ""):
            item["selected"] = True
            item["why"] = "direct match"
            changed = True
    if changed and re.search(r"нет события|no event", str(missing or ""), re.I):
        missing = ""
    return evidence, missing


def looks_done_hint(board, commits):
    """Optional. Match a todo item id, or a title slice such as 'T73 v2', to local commit subjects.

    Does not close anything. Empty when nothing matches.
    """
    hits = []
    for item in board or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "todo").strip().lower()
        if status not in ("todo", ""):
            continue
        iid = str(item.get("id") or "").strip()
        title = str(item.get("title") or "")
        created = _epoch(item.get("created_at"))
        if created is None:
            continue
        hashes = []
        for c in commits or []:
            sub = str(c.get("subject") or "")
            h = str(c.get("hash") or "")
            ts = _epoch(c.get("ts") if c.get("ts") is not None else c.get("time"))
            if not h or not sub or ts is None or not (created < ts):
                continue
            if iid and iid in sub:
                hashes.append(h)
                continue
            if _title_hit(title, sub):
                hashes.append(h)
        if hashes:
            label = iid or title[:24]
            hits.append("%s (%s)" % (label, ", ".join(hashes[:3])))
    if not hits:
        return ""
    return "looks done, close? " + "; ".join(hits[:3])


def _epoch(v):
    """Unix seconds. Missing or unreadable is None, and that commit or item does not hint."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    if re.fullmatch(r"\d+", s):
        return float(s)
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def _title_hit(title, subject):
    sub = subject.lower()
    for m in re.finditer(r"T\d+\s*v\d+", title or "", re.I):
        if m.group(0).lower() in sub:
            return True
    for m in re.finditer(r"\bT\d+\b", title or ""):
        if re.search(r"\b%s\b" % re.escape(m.group(0)), subject):
            return True
    return False


_COMMITS = None


def local_commits(root="/root/skv-core", limit=40):
    """Read git log only when .git exists. Cached. Never raises. Does not invent hashes."""
    global _COMMITS
    if _COMMITS is not None:
        return _COMMITS
    _COMMITS = []
    try:
        if not os.path.isdir(os.path.join(root, ".git")):
            return _COMMITS
        import subprocess
        p = subprocess.run(
            ["git", "-C", root, "log", "-n", str(int(limit)), "--pretty=%h%x09%ct%x09%s"],
            capture_output=True, text=True, timeout=3,
        )
        if p.returncode != 0:
            return _COMMITS
        for line in (p.stdout or "").splitlines():
            h, ts, sub = (line.split("\t", 2) + ["", ""])[:3]
            if re.fullmatch(r"[0-9a-f]{7,40}", h or "") and re.fullmatch(r"\d+", ts or ""):
                _COMMITS.append({"hash": h, "subject": sub, "ts": int(ts)})
    except Exception:
        return _COMMITS
    return _COMMITS


def next_step_for(resp, message="", closed_duty=None):
    """Name the open duty and the exact close action.

    kind=other never drives the line. cube_nothing / vote_nothing on this turn
    drops that kind. Nothing is closed here.
    """
    closed_duty = closed_duty or {}
    duties = []
    for d in resp.get("duties") or []:
        kind = _duty_kind(d)
        if kind == "other":
            continue
        if kind == "cube" and closed_duty.get("cube"):
            continue
        if kind == "vote" and closed_duty.get("vote"):
            continue
        duties.append(d)
    if duties:
        d0 = duties[0]
        kind = _duty_kind(d0)
        if isinstance(d0, dict):
            name = str(d0.get("id") or d0.get("do") or kind)
        else:
            name = " ".join(str(d0).split())
        return "close duty %s: %s (%s)" % (kind, _close_line(d0, 1), name[:80])
    window = resp.get("window") or {}
    weak = not resp.get("facts")
    if window and weak:
        return "search first with since=%s until=%s" % (window.get("since"), window.get("until"))
    if weak and (resp.get("facts_note") or resp.get("tool_duty") or _asks_past(message)):
        return "search first"
    return "answer"


def _asks_past(message):
    return bool(re.search(r"(?i)\b(remember|recall|вчера|yesterday|неделю назад|a week ago|what did we)\b", message or ""))


def window_map(facts, window):
    rows = []
    if not window:
        return rows
    for f in facts or []:
        if not isinstance(f, dict) or not _in_window(f, window):
            continue
        text = str(f.get("fact") or "")
        layer = str(f.get("layer") or "")
        if text.startswith("[l1]") or layer == "l1":
            name = "l1"
        elif text.startswith("[l2]") or layer == "l2":
            name = "l2"
        else:
            continue
        rows.append({"layer": name, "ev": f.get("ev") or "", "time": f.get("time") or "", "text": text[:180]})
    return rows


def _now():
    return datetime.utcnow().timestamp()


def _db(path):
    c = sqlite3.connect(path, timeout=10)
    c.execute(
        "create table if not exists tp_sess("
        "user_key text, session text, desk_h text, dig_h text, lang_h text, prof_h text,"
        "core_sent int, seen_json text, duty_json text, primary key(user_key, session))"
    )
    c.execute(
        "create table if not exists tp_used("
        "user_key text, chain text, turn_key text, fact_id text, t real)"
    )
    c.execute(
        "create table if not exists tp_closed("
        "user_key text, trigger_id text, kind text, t real, primary key(user_key, trigger_id, kind))"
    )
    return c


def _load_sess(db, user, session):
    empty = {"desk_h": "", "dig_h": "", "lang_h": "", "prof_h": "", "core_sent": 0, "seen": [], "duty": {}}
    if not db:
        return empty, False
    try:
        c = _db(db)
        try:
            row = c.execute(
                "select desk_h, dig_h, lang_h, prof_h, core_sent, seen_json, duty_json from tp_sess where user_key=? and session=?",
                (_user_key(user), (session or "s")[:80]),
            ).fetchone()
        finally:
            c.close()
    except Exception:
        return empty, False
    if not row:
        return empty, False
    try:
        seen = json.loads(row[5] or "[]")
    except Exception:
        seen = []
    try:
        duty = json.loads(row[6] or "{}")
    except Exception:
        duty = {}
    return {
        "desk_h": row[0] or "",
        "dig_h": row[1] or "",
        "lang_h": row[2] or "",
        "prof_h": row[3] or "",
        "core_sent": int(row[4] or 0),
        "seen": seen if isinstance(seen, list) else [],
        "duty": duty if isinstance(duty, dict) else {},
    }, True


def _save_sess(db, user, session, st):
    if not db:
        return
    try:
        c = _db(db)
        try:
            c.execute(
                "insert or replace into tp_sess values(?,?,?,?,?,?,?,?,?)",
                (
                    _user_key(user), (session or "s")[:80],
                    st.get("desk_h") or "", st.get("dig_h") or "", st.get("lang_h") or "", st.get("prof_h") or "",
                    1 if st.get("core_sent") else 0,
                    json.dumps(list(st.get("seen") or [])[-_SEEN_CAP:]),
                    json.dumps(st.get("duty") or {}),
                ),
            )
            c.commit()
        finally:
            c.close()
    except Exception:
        return


def store_used_facts(db, user, chain, turn_key, fact_ids):
    """Ids only. No message text."""
    if not db or not fact_ids:
        return
    try:
        c = _db(db)
        try:
            now = _now()
            uk = _user_key(user)
            for fid in fact_ids:
                fid = str(fid).split("::")[-1][:80]
                if not fid:
                    continue
                c.execute(
                    "insert into tp_used(user_key, chain, turn_key, fact_id, t) values(?,?,?,?,?)",
                    (uk, (chain or "")[:40], (turn_key or "")[:80], fid, now),
                )
            c.commit()
        finally:
            c.close()
    except Exception:
        return


def _parse_ids(raw):
    if raw is None or raw == "":
        return []
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    s = str(raw).strip()
    if s.startswith("["):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass
    return [x.strip() for x in re.split(r"[,|\s]+", s) if x.strip()]


def _gate(resp, key, stored, force):
    val = resp.get(key)
    if val in (None, "", [], {}):
        return stored or ""
    h = _hash(val)
    if not force and stored and h == stored:
        resp.pop(key, None)
        return stored
    return h


def apply_desk(resp, stored_hash, first, compressed):
    lines = list(DESK_LINES)
    h = _hash(lines)
    if first or compressed or not stored_hash:
        resp["desk"] = lines
        resp.pop("desk_delta", None)
        return h
    if h == stored_hash:
        resp.pop("desk", None)
        resp.pop("desk_delta", None)
        return h
    resp.pop("desk", None)
    resp["desk_delta"] = lines
    resp["desk_version"] = h
    return h


def recent_session_ids(user, session, n=_SESSION_TAIL):
    """Last n event ids of this session. Read-only. Empty if the shelf is missing. Never creates a db."""
    if not user or not session:
        return []
    try:
        from app import shelves
        path = os.path.join(shelves.BASE_DIR, shelves._name(user) + ".db")
        if not os.path.isfile(path):
            return []
        c = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        try:
            cols = {r[1] for r in c.execute("PRAGMA table_info(event_metadata)")}
            if "session_id" not in cols or "event_id" not in cols:
                return []
            rows = c.execute(
                "SELECT event_id FROM event_metadata WHERE session_id=? ORDER BY rowid DESC LIMIT ?",
                (session, int(n)),
            ).fetchall()
        finally:
            c.close()
        return [r[0] for r in rows if r and r[0]]
    except Exception:
        return []


def _spread(rows, n):
    rows = list(rows or [])
    if len(rows) <= n:
        return rows
    if n <= 1:
        return rows[:1]
    if n == 2:
        return [rows[0], rows[-1]]
    mid = rows[len(rows) // 2]
    return [rows[0], mid, rows[-1]]


def _load_window_shelf(user, window):
    """2-3 events plus the L1/L2 that cover them. Never creates an account db."""
    if not user or not window:
        return []
    try:
        from app import shelves
        path = os.path.join(shelves.BASE_DIR, shelves._name(user) + ".db")
        if not os.path.isfile(path):
            return []
        from app.search_window import collect
        bounds = {
            "since": window.get("since"), "until": window.get("until"),
            "since_kind": "date", "until_kind": "date", "window_set": True,
        }
        rows = [r for r in collect(user, bounds, db=path) if (r.get("content") or "").strip()]
        picked = _spread(rows, 3)
        if not picked:
            return []
        facts = []
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        try:
            ids = [r["id"] for r in picked]
            qmarks = ",".join("?" * len(ids))
            rids = [r[0] for r in conn.execute(
                "SELECT rowid FROM event_metadata WHERE event_id IN (%s)" % qmarks, ids)]
            l1s, l2s = [], []
            if rids:
                lo, hi = min(rids), max(rids)
                try:
                    l1s = conn.execute(
                        "SELECT session_id, topic, summary_text FROM summary_l1 "
                        "WHERE to_rowid >= ? AND from_rowid <= ? LIMIT 2",
                        (lo, hi),
                    ).fetchall()
                except Exception:
                    l1s = []
                try:
                    l2s = conn.execute(
                        "SELECT id, text FROM summary_l2_blocks "
                        "WHERE to_rowid >= ? AND from_rowid <= ? AND source != 'legacy_summary_l2' LIMIT 2",
                        (lo, hi),
                    ).fetchall()
                except Exception:
                    l2s = []
        finally:
            conn.close()
        stamp = str(picked[0].get("date") or "")[:16]
        for sess, topic, text in l1s:
            body = ("%s: %s" % (topic or "", text or "")).strip(": ").strip()
            if body:
                facts.append({
                    "ev": "l1:%s" % (sess or "win"), "time": stamp,
                    "fact": "[l1] " + body[:400], "layer": "l1",
                })
        for lid, text in l2s:
            if text:
                facts.append({
                    "ev": "l2:%s" % lid, "time": stamp,
                    "fact": "[l2] " + str(text)[:400], "layer": "l2",
                })
        for r in picked:
            facts.append({
                "ev": str(r.get("id") or "").split("::")[-1],
                "time": str(r.get("date") or "")[:16],
                "fact": str(r.get("content") or "")[:400],
                "layer": "event",
            })
        return [f for f in facts if f.get("ev") and f.get("fact")]
    except Exception:
        return []


def _window_pack(ctx, user, window):
    if not user or not window:
        return []
    if "window_loader" in (ctx or {}):
        loader = ctx.get("window_loader")
        if not callable(loader):
            return []
        try:
            got = loader(user, window) or []
        except Exception:
            return []
        return [f for f in got if isinstance(f, dict) and not f.get("is_self") and f.get("ev")]
    return _load_window_shelf(user, window)


def finish(resp, ctx=None):
    """Apply the pack to a turn dict. Never raises. Returns the same dict."""
    try:
        return _finish(resp, ctx or {})
    except Exception:
        return resp


def _finish(resp, ctx):
    if not isinstance(resp, dict):
        return resp
    if resp.get("status") in (401, 403):
        return resp
    if resp.get("ok") is False and "facts" not in resp and "verdict" not in resp and "mode" not in resp:
        return resp
    if not any(k in resp for k in ("facts", "verdict", "mode", "duties", "desk")):
        return resp
    user = ctx.get("user") or ""
    session = ctx.get("session") or "s"
    message = ctx.get("message") or ""
    if "db" in ctx:
        db = ctx.get("db") or ""
    elif os.path.isdir(os.path.dirname(_DEFAULT_DB)):
        db = os.environ.get("SKV_TURN_PACK_DB") or _DEFAULT_DB
    else:
        db = ""
    compressed = bool(ctx.get("compressed"))
    compressed_at = str(ctx.get("compressed_at") or "")
    today = ctx.get("today")
    st, existed = _load_sess(db, user, session)
    first = not existed
    if "recent_ids" in ctx:
        recent_ids = ctx.get("recent_ids") or []
    elif compressed or compressed_at:
        recent_ids = []
    else:
        recent_ids = recent_session_ids(user, session)
    if "seen_fact_ids" in ctx:
        seen = ctx.get("seen_fact_ids") or []
    elif compressed or compressed_at:
        seen = []
    else:
        seen = st.get("seen") or []
    facts = select_facts(
        resp.get("facts") or [],
        message=message,
        recent_ids=recent_ids,
        seen_fact_ids=seen,
        compressed=compressed,
        compressed_at=compressed_at,
        today=today,
    )
    records = ctx.get("records")
    criticals = ctx.get("criticals")
    if records and criticals:
        records, placed = nest_critical(records, criticals, ctx.get("rows"))
        resp["records"] = _public_records(records)
        facts = [f for f in facts if str(f.get("ev") or "").split("::")[-1] not in placed]
    window = date_window(message, today=today)
    if window and user:
        have = {str(f.get("ev") or "").split("::")[-1] for f in facts if isinstance(f, dict)}
        for extra in _window_pack(ctx, user, window):
            ev = str(extra.get("ev") or "").split("::")[-1]
            if not ev or ev in have or extra.get("is_self"):
                continue
            if not _in_window(extra, window):
                continue
            facts.append(extra)
            have.add(ev)
    resp["facts"] = facts
    if window:
        resp["window"] = window
        mapped = window_map(facts, window)
        if mapped:
            resp["window_map"] = mapped
        else:
            resp.pop("window_map", None)
        ev = ""
        for f in facts:
            if _in_window(f, window) and f.get("ev"):
                ev = str(f.get("ev")).split("::")[-1]
                break
        resp["window_hint"] = "open full event %s / memory_search since=%s until=%s" % (
            ev or "<ev>", window["since"], window["until"])
    else:
        resp.pop("window", None)
        resp.pop("window_hint", None)
        resp.pop("window_map", None)
    duty = str(ctx.get("duty") or "").strip().lower()
    reason = str(ctx.get("duty_reason") or "").strip()
    trigger = str(ctx.get("trigger_id") or "")
    if not trigger:
        ids = _parse_ids(ctx.get("source_event_ids"))
        trigger = ids[0] if ids else ""
    if duty == "cube_nothing" and reason and trigger:
        note_closed(db, user, trigger, "cube")
    if duty == "vote_nothing" and trigger:
        note_closed(db, user, trigger, "vote")
    closed = closed_map(db, user)
    if ctx.get("closed"):
        closed.update(ctx["closed"])
    shaped, counts, core_sent, sd = shape_duties(
        resp.get("duties") or [],
        summary_due=resp.get("summary_due"),
        cube_applied=bool(ctx.get("cube_applied")),
        l1_just_saved=bool(ctx.get("l1_just_saved")),
        closed=closed,
        trigger_id=trigger,
        open_counts=st.get("duty") or {},
        core_sent=bool(st.get("core_sent")),
    )
    resp["duties"] = shaped
    if sd:
        resp["summary_due"] = sd
    elif "summary_due" in resp and not resp.get("summary_due"):
        resp.pop("summary_due", None)
    force_echo = first or compressed or bool(compressed_at)
    st["dig_h"] = _gate(resp, "profile_digest", st.get("dig_h"), force_echo)
    st["lang_h"] = _gate(resp, "search_language_rule", st.get("lang_h"), force_echo)
    st["prof_h"] = _gate(resp, "profile", st.get("prof_h"), force_echo)
    st["desk_h"] = apply_desk(resp, st.get("desk_h"), first, compressed or bool(compressed_at))
    st["core_sent"] = 1 if core_sent else st.get("core_sent")
    st["duty"] = counts
    sent_ids = [str(f.get("ev")) for f in facts if isinstance(f, dict) and f.get("ev")]
    if compressed or compressed_at:
        st["seen"] = sent_ids[-_SEEN_CAP:]
    else:
        st["seen"] = (list(seen) + sent_ids)[-_SEEN_CAP:]
    _save_sess(db, user, session, st)
    used = _parse_ids(ctx.get("used_fact_ids"))
    if used:
        store_used_facts(db, user, ctx.get("chain") or "", str(resp.get("event_id") or session), used)
    if "board_hint" not in resp or not resp.get("board_hint"):
        commits = ctx.get("commits")
        if commits is None and resp.get("board"):
            commits = local_commits()
        hint = looks_done_hint(resp.get("board") or [], commits or [])
        if hint:
            resp["board_hint"] = hint
    closed_now = {}
    if duty == "cube_nothing":
        closed_now["cube"] = True
    if duty == "vote_nothing":
        closed_now["vote"] = True
    resp["next_step"] = next_step_for(resp, message, closed_duty=closed_now)
    return resp


def _public_records(records):
    """Short list for the turn body. Bodies are not repeated; critical lines are."""
    out = []
    for name in ("l2", "l1"):
        for rec in (records.get(name) or {}).get("included") or []:
            lines = rec.get("critical_lines") or []
            if not lines and not rec.get("id"):
                continue
            out.append({
                "layer": name,
                "id": rec.get("id") or "",
                "critical_lines": lines,
            })
    return out

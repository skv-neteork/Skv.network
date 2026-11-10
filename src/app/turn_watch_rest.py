"""REST twin of the MCP turn-watch (mcp/mcp_skv.py _tw_ref / _save_recaps): optional msg_ref and recap on /agent/turn.
msg_ref = the client's ordinal of this user message ("t648u", "648", "t754u-t755u"). A jump above the previous saved
msg_ref is a gap: the answers in between went out without turn -> duty missed_turns. recap=[{ref,user,answer}] (JSON list,
JSON string or "tNu: ask => answer" lines) saves those answers (topic=recap, no seal) and covers the gap.
Clients that send neither msg_ref nor recap are not affected. Scope: account + agent (hash of agent_token, never stored raw)."""
import hashlib, json, re, sqlite3, time

DB = "/data/skv/metadata_store/compact_state_rest.db"
_REF_RX = re.compile(r"\bt(\d{1,7})u\b")
_RANGE_RX = re.compile(r"\bt(\d{1,7})u?\s*(?:-|\u2013|\u2014|\.\.)\s*t?(\d{1,7})u?\b")
PIN = "Call SKV turn before every reply, even short ones, including during browser/tool-heavy work."


def _db():
    c = sqlite3.connect(DB, timeout=10)
    c.execute("create table if not exists rtw_ref(k text primary key, last_ref int, t real)")
    c.execute("create table if not exists rtw_cov(k text, ref int, t real, primary key(k, ref))")
    return c


def scope(user: str, agent_token: str = "") -> str:
    return (user or "env") + (("#" + hashlib.sha256(agent_token.encode()).hexdigest()[:10]) if agent_token else "")


def span(msg_ref) -> tuple:
    """(lo, hi) ordinals; (0, 0) = unknown. Only the explicit msg_ref counts (user_message tags are not parsed on REST)."""
    src = str(msg_ref or "")
    if not src.strip():
        return 0, 0
    nums = []
    for r in _RANGE_RX.finditer(src):
        a, b = int(r.group(1)), int(r.group(2))
        if b >= a and b - a <= 50:
            nums += [a, b]
    nums += [int(x) for x in _REF_RX.findall(src)]
    if not nums:
        m = re.fullmatch(r"\s*(\d{1,7})\s*", src)
        if m:
            nums = [int(m.group(1))]
    return (min(nums), max(nums)) if nums else (0, 0)


def parse_recap(recap) -> list:
    items = []
    if not recap:
        return items
    try:
        o = recap if isinstance(recap, (list, dict)) else json.loads(recap)
        if isinstance(o, dict):
            o = [o]
        if isinstance(o, list):
            for x in o:
                if isinstance(x, dict):
                    items.append((str(x.get("ref") or ""), str(x.get("user") or x.get("query") or ""), str(x.get("answer") or x.get("response") or "")))
                elif isinstance(x, str) and x.strip():
                    items.append(("", x, ""))
            return items
    except Exception:
        pass
    if not isinstance(recap, str):
        return items
    for ln in recap.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        m = re.match(r"^\[?(t\d+u)\]?\s*[:\-]\s*(.*)$", ln)
        ref, rest = (m.group(1), m.group(2)) if m else ("", ln)
        u, _, a = rest.partition("=>")
        items.append((ref, u.strip(), a.strip()))
    return items


def _num(ref: str) -> int:
    m = _REF_RX.search(ref or "") or re.fullmatch(r"\s*(\d{1,7})\s*", ref or "")
    return int(m.group(1)) if m else 0


def last_ref(k: str) -> int:
    try:
        c = _db(); r = c.execute("select last_ref from rtw_ref where k=?", (k,)).fetchone(); c.close()
        return int(r[0]) if r and r[0] else 0
    except Exception:
        return 0


def cover(k: str, nums) -> None:
    """Recaps cover missed messages: they no longer count as missed."""
    try:
        nums = sorted({int(n) for n in nums if n})
        if not nums:
            return
        c = _db(); now = time.time()
        c.executemany("insert or replace into rtw_cov values(?,?,?)", [(k, n, now) for n in nums])
        c.execute("delete from rtw_cov where t < ?", (now - 7 * 86400,)); c.commit(); c.close()
    except Exception:
        pass


def check(k: str, ref, saved: bool) -> list:
    """Missing message ordinals between the previous saved msg_ref and lo (minus recap-covered). On save stores hi."""
    lo, hi = ref if isinstance(ref, tuple) else (ref, ref)
    if not hi:
        return []
    c = _db()
    try:
        r = c.execute("select last_ref from rtw_ref where k=?", (k,)).fetchone()
        prev = int(r[0]) if r and r[0] else 0
        missing = []
        if prev and lo > prev + 1:
            cov = {int(x[0]) for x in c.execute("select ref from rtw_cov where k=? and ref>? and ref<?", (k, prev, lo))}
            missing = [n for n in range(prev + 1, lo) if n not in cov]
        if saved and hi >= prev:
            c.execute("insert or replace into rtw_ref values(?,?,?)", (k, hi, time.time()))
            c.execute("delete from rtw_cov where k=? and ref<=?", (k, hi))
            c.commit()
        return missing
    finally:
        c.close()


def fmt_refs(ns: list, ru: bool = True) -> str:
    out, i = [], 0
    while i < len(ns):
        j = i
        while j + 1 < len(ns) and ns[j + 1] == ns[j] + 1:
            j += 1
        out.append("t%du" % ns[i] if i == j else ("t%du–t%du" if ru else "t%du..t%du") % (ns[i], ns[j])); i = j + 1
    return (", " if ru else ",").join(out)


def duty(missing: list) -> dict:
    return {"id": "missed_turns", "kind": "missed_turns", "n": len(missing), "source": "msg_ref", "pin": PIN, "refs": fmt_refs(missing, False)[:200],
            "do": "missed_turns: пропущены %s (%d), пришли recap=[{ref,user,answer}] в этом же вызове /agent/turn (по одному на ответ, старые первыми, вместе с предыдущим ответом); "
                  "recap сохраняется как recap-событие без печати. Передавай msg_ref=tNNNu." % (fmt_refs(missing)[:200], len(missing))}


def save_recaps(req, key: str, k: str, recap, session_id: str, sensitive, scrub) -> dict:
    """Save recap items via /remember (topic=recap, no seal) and cover their refs. req(key, method, path, body) -> dict."""
    items = [x for x in parse_recap(recap) if x[1] or x[2]][:20]
    out = {}
    if not items:
        return {"recap_error": "recap is empty or unreadable: pass a JSON list of {ref,user,answer}"}
    done_ref, ids, errs, dup = last_ref(k), [], [], []
    sens = [x for x in (sensitive or []) if x]
    for ref, u, a in items:
        n = _num(ref)
        if n and n <= done_ref:
            dup.append(ref); continue          # that message already has a saved turn
        body = {"query": "[recap%s] %s" % ((" " + ref) if ref else "", scrub(u[:600], sens)), "response": scrub(a[:1200], sens), "topic": "recap",
                "session_id": session_id or "rest", "sensitive": sens}
        d = req(key, "POST", "/remember", body)
        e = (d.get("event_id") or ((d.get("saved") or [""])[0])) if isinstance(d, dict) and d.get("ok") is not False else ""
        if e:
            ids.append(e.split("::")[-1]); cover(k, [n] if n else [])
        else:
            errs.append(ref or u[:40])
    out["recap_saved"] = len(ids); out["recap_event_ids"] = ids
    if dup: out["recap_already_saved"] = dup
    if errs: out["recap_failed"] = errs
    return out

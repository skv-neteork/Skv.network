"""SKV memory v2: background LLM summaries (bg_llm=true in memory_config.json). FALLBACK only.

Agents should write L1/L2 themselves via /remember (l1_summary, l2_map). The server job only fills gaps.
- L1: uncovered stretches (older than the newest `llm_keep_raw` turns) that have no agent or llm L1 range yet.
  Any summary_l1 with from/to_rowid already covers those rowids, so agent-written L1 is never overwritten.
  English, `llm_l1_turns` per L1, session_id llm_l1_<from>_<to>; max `llm_l1_per_cycle` per account per cycle.
- L2: one block (source 'llm') from >= `llm_l2_min_l1` new llm L1 rows; max 1 per account per cycle.
- Never touches summary_l2. Skips excluded topics (skv_eval*) and doc/code kinds. Masks secrets before sending.
- Usage and cost (RUB) are appended to /data/skv/llm_usage.jsonl.
"""
import json
import os
import re
import sqlite3
import time
import urllib.request

from app.memory_v2 import BASE_DIR, clip, config, est_tokens, mask_text, norm_date, strip_critical
from app import memory_v2_windows as W

URL = "https://api.polza.ai/v1/chat/completions"
USAGE_LOG = "/data/skv/llm_usage.jsonl"


def _c(k, d):
    return config().get(k, d)


def _llm(messages, max_tokens, json_mode=False):
    key = os.environ.get("POLZA_KEY", "")
    if not key:
        raise RuntimeError("POLZA_KEY not set")
    req = urllib.request.Request(URL, data=json.dumps({
        "model": _c("llm_model", "deepseek/deepseek-chat-v3.1"), "messages": messages,
        "temperature": 0.1, "max_tokens": max_tokens, **({"response_format": {"type": "json_object"}} if json_mode else {})}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=int(_c("llm_timeout_s", 60))) as r:
        d = json.loads(r.read())
    u = d.get("usage") or {}
    cost = u.get("cost_rub", d.get("cost_rub", u.get("cost", d.get("cost"))))
    return d["choices"][0]["message"]["content"], {"prompt": u.get("prompt_tokens", 0), "completion": u.get("completion_tokens", 0), "cost_rub": cost}


def _log(rec):
    try:
        with open(USAGE_LOG, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


_JUNK = re.compile(r"^\s*(here\s+is|here's|below\s+is|sure|certainly|okay|thinking process)[^\n]*\n+", re.I)


def clean_llm(text):
    """Post-processor: drop chatty prefixes, code fences, markdown topic headers."""
    s = (text or "").strip()
    for _ in range(3):
        s = _JUNK.sub("", s, count=1).strip()
    s = re.sub(r"^```[a-zA-Z]*\s*", "", s); s = re.sub(r"\s*```\s*$", "", s)
    s = s.replace("```json", "").replace("```", "").strip()
    s = re.sub(r"^\*\*topic:[^\n]*\*\*\s*", "", s, flags=re.I).strip()
    return s


def _json_out(text):
    s = clean_llm(text)
    a, b = s.find("{"), s.rfind("}")
    if a >= 0 and b > a:
        try:
            return json.loads(s[a:b + 1])
        except Exception:
            pass
    return {"topic": "", "summary": s}


def _topic_ok(ess, topics_json):
    if W._excluded_topic(ess):
        return False
    try:
        return not any(W._excluded_topic(str(t)) for t in json.loads(topics_json or "[]"))
    except Exception:
        return True


def _uncovered_chunks(conn, user_id=None):
    keep = max(int(_c("llm_keep_raw", 10)), int(_c("llm_agent_grace_turns", 30)))   # agent-first: summary_due fires at 15, agent gets a grace window before the fallback
    size = int(_c("llm_l1_turns", 15))
    mn = int(_c("llm_l1_min_turns", 6))
    mx = conn.execute("SELECT MAX(rowid) FROM event_metadata").fetchone()[0] or 0
    limit = mx - keep
    covered = conn.execute("SELECT from_rowid, to_rowid FROM summary_l1 WHERE to_rowid IS NOT NULL").fetchall()
    cov = set()
    for fr, to in covered:
        cov.update(range(fr or to, to + 1))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(event_metadata)")}
    sel = ", ".join(c if c in cols else f"NULL AS {c}" for c in ("essence", "topics_json", "kind", "raw_dialogue"))
    rows = conn.execute(f"SELECT rowid, {sel}, event_id FROM event_metadata WHERE rowid <= ? ORDER BY rowid DESC LIMIT 3000", (limit,)).fetchall()
    try:   # memory lines: an L1 chunk never spans two key lines
        from app import memory_lines as _ml
        lmap = _ml.line_map(user_id) if user_id else {}
    except Exception:
        lmap = {}
    chunks, cur, cur_line = [], [], None
    for rid, ess, tj, kind, raw, eid in rows:            # newest first
        bad = rid in cov or not _topic_ok(ess, tj)
        ln = lmap.get(eid)
        if bad or (cur and cur[-1][0] != rid + 1) or len(cur) >= size or (cur and ln != cur_line):
            if len(cur) >= mn:
                chunks.append(list(reversed(cur)))
            cur = []
        if bad:
            continue
        if not cur:
            cur_line = ln
        if W._window_kind_ok(kind) and (raw or ess):
            cur.append((rid, ess, raw))
        elif cur:
            cur.append((rid, ess, ""))
    if len(cur) >= mn:
        chunks.append(list(reversed(cur)))
    return chunks


_TRIVIAL_RX = re.compile(r"^(deniz|the user|user)\b[^.]{0,20}\b(is|as) (the )?(user|owner|decision|main)|\bis (mandatory|required) in (the )?skv( system)?\.?$", re.I)

L1_PROMPT = "You write long-term memory for an AI agent: an L1 summary of one stretch of a user's conversations with AI agents. This is a FALLBACK: the agent should have written it itself. Output STRICT JSON only (no prose, no code fences) with keys: topic: 1-3 lowercase words joined by underscores (e.g. skv_memory); summary: chronological STAGES, one per line, each 'STAGE n: done ...; decided ...; outcome ...' (only what happened in the text), final line 'OPEN: ...' if tasks remain; about 5-8 percent of the input; English; keep names, numbers, codes, file names exactly; critical: 0-3 lasting facts the agent must always remember: decisions taken, standing rules, agreements, names and roles of people other than the user, account or project facts; each fact specific (the concrete value: number, name, setting, decision). Not plans, opinions, general knowledge, dates alone or links alone; not trivial facts (who the user is, that the user leads the project, that a rule exists or is mandatory). Empty list if none; sensitive: exact strings from the text that are real secrets (passwords, private API keys, tokens, card numbers, private codes). Public keys (ssh-ed25519/ssh-rsa), IPs, domains and emails are NOT secrets. Empty list if none. Never copy a secret into summary or critical. Use only facts present in the text. Never invent."


def gen_l1(conn, user_id, acct):
    made, usage = 0, []
    _chs = _uncovered_chunks(conn, user_id)
    _cap = int(_c("llm_l1_per_cycle", 3))
    if len(_chs) > _cap:   # backlog (e.g. busy test accounts): catch up faster instead of falling further behind
        _cap = max(_cap, int(_c("llm_l1_catchup_max", 8)))
    for ch in _chs[:_cap]:
        fr, to = ch[0][0], ch[-1][0]
        sid = f"llm_l1_{fr}_{to}"
        if conn.execute("SELECT 1 FROM summary_l1 WHERE session_id=?", (sid,)).fetchone():
            continue
        body = "\n".join(f"[{rid}] " + clip(mask_text(strip_critical(raw or ess or "")), 220) for rid, ess, raw in ch)
        text, u = _llm([{"role": "system", "content": L1_PROMPT}, {"role": "user", "content": body}], 900, json_mode=True)
        j = _json_out(text)
        _sv = j.get("summary") or ""
        if isinstance(_sv, list):
            _sv = "\n".join(x if isinstance(x, str) else " - ".join(str(v) for v in (x or {}).values()) for x in _sv)
        summ = mask_text(clean_llm(str(_sv)))
        _sec = [x for x in (j.get("sensitive") or []) if isinstance(x, str) and len(x) >= 4]
        for _x in _sec:
            summ = summ.replace(_x, "[SECRET]")
        _facts = [str(x).strip() for x in (j.get("critical") or []) if str(x).strip()][:3]
        _facts = [x for x in _facts if not _TRIVIAL_RX.search(x)]
        if summ.lstrip().startswith("{") or "\"summary\"" in summ:
            continue
        if len(summ) < 20:
            continue
        topic = str(j.get("topic") or "").strip().lower().replace(" ", "_")[:60]
        if not topic or "snake_case" in topic or topic in ("topic", "short_topic"):
            topic = "llm_summary"
        conn.execute("INSERT INTO summary_l1 (session_id, user_id, topic, summary_text, summary_json, message_count, created_at, from_rowid, to_rowid, lang) VALUES (?,?,?,?,?,?,datetime('now'),?,?,?)",
                     (sid, user_id, topic, summ, json.dumps({"source": "server_fallback", "model": _c("llm_model", "deepseek/deepseek-chat-v3.1"), "usage": u}), len(ch), fr, to, "en"))
        conn.commit()
        try:
            from app import source_links as _sl; _sl.link_all(conn)
        except Exception as _e:
            print(f"[source_links] {_e}", flush=True)
        try:   # model-picked lasting facts (fallback, not regex)
            from app import critical_auto as _ca
            _ca.ensure(conn)
            _eid = conn.execute("SELECT event_id, time_str FROM event_metadata WHERE rowid=?", (to,)).fetchone() or ("", "")
            for _f in _facts:
                if any(_x in _f for _x in _sec):
                    continue
                conn.execute("INSERT OR IGNORE INTO critical_auto (key, kind, value, context, event_id, time_str, source) VALUES (?,?,?,?,?,?,?)",
                             ("fact:" + _f.lower()[:120], "fact", _f[:200], "l1 " + sid, _eid[0], _eid[1], "server_fallback"))
            conn.commit()
        except Exception as _e:
            print(f"[llm facts] {_e}", flush=True)
        made += 1
        usage.append(u)
        _log({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "account": acct, "kind": "l1", "range": [fr, to], **u})
    return made, usage


L2_PROMPT = ("Compress these L1 memory summaries (oldest first) into an L2 map. English. "
             "L2 must be about 5 percent of the combined L1 length: short HEADLINES of the chronological stages, "
             "one line per stage, then an OPEN: line for remaining tasks. Plain text, no JSON, no paragraphs.")


def gen_l2(conn, user_id, acct):
    last = conn.execute("SELECT MAX(to_rowid) FROM summary_l2_blocks WHERE source IN ('llm','server_fallback')").fetchone()[0] or 0
    rows = conn.execute("SELECT topic, summary_text, from_rowid, to_rowid FROM summary_l1 WHERE session_id LIKE 'llm_l1_%' AND from_rowid > ? ORDER BY to_rowid LIMIT 12", (last,)).fetchall()
    rows = [r for r in rows if not W._excluded_topic(r[0])]
    _ag = conn.execute("SELECT MAX(to_rowid) FROM summary_l2_blocks WHERE source='agent'").fetchone()[0] or 0
    rows = [r for r in rows if (r[2] or 0) > _ag]   # agent L2 already covers that range: no server re-summary
    if len(rows) < int(_c("llm_l2_min_l1", 8)):
        return 0, []
    body = "\n".join(f"[{r[2]}-{r[3]}] {r[0]}: {r[1]}" for r in rows)
    text, u = _llm([{"role": "system", "content": L2_PROMPT}, {"role": "user", "content": body}], 200)
    text = mask_text(clean_llm(text))
    fr, to = rows[0][2], rows[-1][3]
    d = W._dates_for(conn, [fr, to])
    topics = list(dict.fromkeys(r[0] for r in rows))[:6]
    conn.execute("INSERT OR IGNORE INTO summary_l2_blocks (user_id, source, period_key, period_from, period_to, from_rowid, to_rowid, topics_json, text) VALUES (?,?,?,?,?,?,?,?,?)",
                 (user_id, "server_fallback", f"llm:{fr}", d.get(fr, ""), d.get(to, ""), fr, to, json.dumps(topics, ensure_ascii=False), text))
    conn.commit()
    _log({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "account": acct, "kind": "l2", "range": [fr, to], **u})
    return 1, [u]


def run_account(fname):
    path = os.path.join(BASE_DIR, fname)
    acct = fname[:-3]
    conn = sqlite3.connect(path, timeout=30)
    try:
        if not W._has_events(conn):
            return {"skipped": "no event_metadata"}
        n = conn.execute("SELECT COUNT(*) FROM event_metadata").fetchone()[0]
        if n < int(_c("llm_min_events", 30)):
            return {"skipped": f"{n} events"}
        W.ensure_schema(conn)
        uid = (conn.execute("SELECT user_id FROM summary_l1 WHERE user_id LIKE '%@%' LIMIT 1").fetchone() or [acct])[0]
        l1, u1 = gen_l1(conn, uid, acct)
        l2, u2 = gen_l2(conn, uid, acct)
        if l1 or l2:
            W.rebuild_auto_blocks(conn, uid)
            conn.commit()
        return {"l1": l1, "l2": l2, "usage": u1 + u2}
    finally:
        conn.close()


def run_cycle(only=None):
    out = {}
    for f in sorted(os.listdir(BASE_DIR)):
        if not f.endswith(".db") or f in ("shared_master.db", "anonymous.db"):
            continue
        if only and f != only:
            continue
        if not only and any(f.startswith(p) for p in _c("llm_skip_account_prefixes", ["test_", "guest_", "anonymous"])):
            continue
        try:
            out[f] = run_account(f)
        except Exception as e:
            out[f] = {"error": str(e)[:200]}
            print(f"[memory_v2_llm] {f}: {e}", flush=True)
    made = sum(v.get("l1", 0) + v.get("l2", 0) for v in out.values())
    print(f"[memory_v2_llm] cycle done: {made} summaries", flush=True)
    return out

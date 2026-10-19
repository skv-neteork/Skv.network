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
import sqlite3
import time
import urllib.request

from app.memory_v2 import BASE_DIR, clip, config, est_tokens, mask_text, norm_date, strip_critical
from app import memory_v2_windows as W

URL = "https://api.polza.ai/v1/chat/completions"
USAGE_LOG = "/data/skv/llm_usage.jsonl"


def _c(k, d):
    return config().get(k, d)


def _llm(messages, max_tokens):
    key = os.environ.get("POLZA_KEY", "")
    if not key:
        raise RuntimeError("POLZA_KEY not set")
    req = urllib.request.Request(URL, data=json.dumps({
        "model": _c("llm_model", "meta-llama/llama-3.1-8b-instruct"), "messages": messages,
        "temperature": 0.2, "max_tokens": max_tokens}).encode(),
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


def _json_out(text):
    s = text.strip()
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


def _uncovered_chunks(conn):
    keep = int(_c("llm_keep_raw", 10))
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
    rows = conn.execute(f"SELECT rowid, {sel} FROM event_metadata WHERE rowid <= ? ORDER BY rowid DESC LIMIT 3000", (limit,)).fetchall()
    chunks, cur = [], []
    for rid, ess, tj, kind, raw in rows:            # newest first
        bad = rid in cov or not _topic_ok(ess, tj)
        if bad or (cur and cur[-1][0] != rid + 1) or len(cur) >= size:
            if len(cur) >= mn:
                chunks.append(list(reversed(cur)))
            cur = []
        if bad:
            continue
        if W._window_kind_ok(kind) and (raw or ess):
            cur.append((rid, ess, raw))
        elif cur:
            cur.append((rid, ess, ""))
    if len(cur) >= mn:
        chunks.append(list(reversed(cur)))
    return chunks


L1_PROMPT = ("You summarize a stretch of a user's conversation with AI agents for long-term memory. "
             "Write in English even if the dialogue is in another language. Keep names, decisions, numbers, open tasks. "
             "Return only JSON with two keys: topic (1-3 lowercase words joined by underscores that name the subject, "
             "for example first_aid or skv_memory) and summary (3-5 sentences).")


def gen_l1(conn, user_id, acct):
    made, usage = 0, []
    for ch in _uncovered_chunks(conn)[: int(_c("llm_l1_per_cycle", 3))]:
        fr, to = ch[0][0], ch[-1][0]
        sid = f"llm_l1_{fr}_{to}"
        if conn.execute("SELECT 1 FROM summary_l1 WHERE session_id=?", (sid,)).fetchone():
            continue
        body = "\n".join(f"[{rid}] " + clip(mask_text(strip_critical(raw or ess or "")), 220) for rid, ess, raw in ch)
        text, u = _llm([{"role": "system", "content": L1_PROMPT}, {"role": "user", "content": body}], 350)
        j = _json_out(text)
        summ = mask_text(str(j.get("summary") or "").strip())
        if len(summ) < 20:
            continue
        topic = str(j.get("topic") or "").strip().lower().replace(" ", "_")[:60]
        if not topic or "snake_case" in topic or topic in ("topic", "short_topic"):
            topic = "llm_summary"
        conn.execute("INSERT INTO summary_l1 (session_id, user_id, topic, summary_text, summary_json, message_count, created_at, from_rowid, to_rowid, lang) VALUES (?,?,?,?,?,?,datetime('now'),?,?,?)",
                     (sid, user_id, topic, summ, json.dumps({"source": "llm", "usage": u}), len(ch), fr, to, "en"))
        conn.commit()
        made += 1
        usage.append(u)
        _log({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "account": acct, "kind": "l1", "range": [fr, to], **u})
    return made, usage


L2_PROMPT = ("Merge these memory summaries (oldest first) into one period summary for long-term memory. English. "
             "Keep projects, decisions, people, open questions. 4-6 sentences, plain text, no JSON.")


def gen_l2(conn, user_id, acct):
    last = conn.execute("SELECT MAX(to_rowid) FROM summary_l2_blocks WHERE source='llm'").fetchone()[0] or 0
    rows = conn.execute("SELECT topic, summary_text, from_rowid, to_rowid FROM summary_l1 WHERE session_id LIKE 'llm_l1_%' AND from_rowid > ? ORDER BY to_rowid LIMIT 12", (last,)).fetchall()
    rows = [r for r in rows if not W._excluded_topic(r[0])]
    if len(rows) < int(_c("llm_l2_min_l1", 8)):
        return 0, []
    body = "\n".join(f"[{r[2]}-{r[3]}] {r[0]}: {r[1]}" for r in rows)
    text, u = _llm([{"role": "system", "content": L2_PROMPT}, {"role": "user", "content": body}], 400)
    text = mask_text(text.strip())
    fr, to = rows[0][2], rows[-1][3]
    d = W._dates_for(conn, [fr, to])
    topics = list(dict.fromkeys(r[0] for r in rows))[:6]
    conn.execute("INSERT OR IGNORE INTO summary_l2_blocks (user_id, source, period_key, period_from, period_to, from_rowid, to_rowid, topics_json, text) VALUES (?,?,?,?,?,?,?,?,?)",
                 (user_id, "llm", f"llm:{fr}", d.get(fr, ""), d.get(to, ""), fr, to, json.dumps(topics, ensure_ascii=False), text))
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

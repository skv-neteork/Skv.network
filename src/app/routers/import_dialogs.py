"""Import external chat history with Llama processing."""
from fastapi import APIRouter, HTTPException
import json, urllib.request as urlreq, os, sqlite3, time, re

router = APIRouter()

def _scrub(user_id, text):
    """Same secret detection as /remember: secrets go to the vault, text keeps [vault:<name>]."""
    try:
        from app import vault as _vault
        if _vault.available():
            return _vault.scrub(user_id, text or "")[0]
    except Exception as exc:
        print(f"[vault] import scrub skipped: {exc}", flush=True)
    return text


def save_pairs(user_id, messages, source):
    """One write path for dialogs, URL, text, and bookmarklet."""
    from app.account_memory import queue_turn
    saved = 0
    for i, msg in enumerate(messages):
        nxt = messages[i + 1] if i + 1 < len(messages) else {}
        if msg.get("role") == "user" and nxt.get("role") == "assistant":
            # content-derived id: re-importing the same chat is idempotent, a different chat never overwrites it
            import hashlib as _hl
            _h = _hl.sha1((msg.get("content", "") + "\x00" + nxt.get("content", "")).encode("utf-8", "replace")).hexdigest()[:12]
            queue_turn(
                "/data/skv/metadata_store",
                user_id,
                f"{user_id}::{source}_{_h}",
                msg.get("content", ""),
                nxt.get("content", ""),
                source="import",
            )
            saved += 1
    return saved

@router.post("/import/dialogs")
async def import_dialogs(data: dict):
    user_id = data.get("user_id", "")
    messages = data.get("messages", [])
    source = data.get("source", "import")
    if not user_id or not messages:
        return {"status": "error", "detail": "user_id and messages required"}
    db_name = user_id.replace("@", "").replace(".", "")
    conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db")
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS event_metadata (event_id TEXT PRIMARY KEY, time_str TEXT, essence TEXT, raw_dialogue TEXT, messages_count INTEGER, topics_json TEXT, links_json TEXT, status TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS summary_l1 (session_id TEXT PRIMARY KEY, user_id TEXT, topic TEXT, summary_text TEXT, summary_json TEXT, message_count INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cur.execute("CREATE TABLE IF NOT EXISTS summary_l2 (user_id TEXT PRIMARY KEY, map_json TEXT, themes_json TEXT, timeline_json TEXT, session_count INTEGER, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    saved = 0
    for i, msg in enumerate(messages):
        if msg.get("role") == "user" and i+1 < len(messages) and messages[i+1].get("role") == "assistant":
            q, a, ts = _scrub(user_id, msg.get("content","")), _scrub(user_id, messages[i+1].get("content","")), msg.get("timestamp","")
            eid = f"{user_id}::{source}_{i}"
            # Create NEXT link
            prev_eid = f"{user_id}::{source}_{i-2}" if i >= 2 else None
            links = json.dumps({prev_eid: "NEXT"}) if prev_eid else "[]"
            
            cur.execute("INSERT OR IGNORE INTO event_metadata (event_id, time_str, essence, raw_dialogue, messages_count, topics_json, links_json, status) VALUES (?,?,?,?,?,?,?,?)",
                       (eid, ts or "?", q[:200], f"Q: {q}\nA: {a}", 2, f'["{source}"]', links, "active"))
            saved += 1
    conn.commit(); conn.close()
    saved = save_pairs(user_id, messages, source)
    return {"status": "ok", "imported": saved}


@router.post("/import/url")
async def import_from_url(data: dict):
    """Import chat from URL (DeepSeek Share, ChatGPT Share, etc.)"""
    user_id = data.get("user_id", "")
    url = data.get("url", "")
    source = data.get("source", "url_import")
    
    if not user_id or not url:
        return {"error": "user_id and url required"}
    
    try:
        import urllib.request as _urlreq
        req = _urlreq.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with _urlreq.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        
        # Try to find JSON data in the page
        import re
        messages = []
        
        # Pattern 1: DeepSeek Share — JSON in script tag
        json_match = re.search(r'{"messages":\s*\[(.*?)\]\s*}', html, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                messages = data.get("messages", [])
            except:
                pass
        
        # Pattern 2: ChatGPT Share — look for conversation data
        if not messages:
            chat_match = re.search(r'{"conversation":\s*{(.*?)}\s*}', html, re.DOTALL)
            if chat_match:
                try:
                    data = json.loads(chat_match.group(0))
                    messages = data.get("conversation", {}).get("messages", [])
                except:
                    pass
        
        # Pattern 3: Plain text — split by newlines
        if not messages:
            lines = re.findall(r'(?:User|Assistant|Human|AI|Q|A)[:\s]+(.+)', html)
            for i, line in enumerate(lines):
                role = "user" if i % 2 == 0 else "assistant"
                messages.append({"role": role, "content": line.strip()})
        
        if messages:
            saved = save_pairs(user_id, messages, source)
            return {"status": "ok", "imported": saved, "source": source}
        else:
            return {"error": "No messages found at this URL"}
    except Exception as e:
        return {"error": str(e)}


@router.post("/import/text")
async def import_from_text(data: dict):
    """Import from raw text. Format: User: ... \n Assistant: ..."""
    user_id = data.get("user_id", "")
    text = data.get("text", "")
    source = data.get("source", "text_import")
    
    if not user_id or not text:
        return {"error": "user_id and text required"}
    
    import re
    messages = []
    
    # Parse format: "User: ... \n Assistant: ..."
    parts = re.split(r'\n(?=(?:User|Assistant|Human|AI|Q|A)[:\s])', text)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if re.match(r'(?:User|Human|Q)[:\s]', part):
            messages.append({"role": "user", "content": re.sub(r'^(?:User|Human|Q)[:\s]+', '', part)})
        elif re.match(r'(?:Assistant|AI|A)[:\s]', part):
            messages.append({"role": "assistant", "content": re.sub(r'^(?:Assistant|AI|A)[:\s]+', '', part)})
    
    if not messages:
        # Fallback: split by double newline
        lines = text.strip().split('\n\n')
        for i, line in enumerate(lines):
            role = "user" if i % 2 == 0 else "assistant"
            messages.append({"role": role, "content": line.strip()})
    
    if not messages:
        chunk = text.strip()
        step = 1200
        pieces = [chunk[i:i+step] for i in range(0, len(chunk), step)] or [chunk]
        messages = []
        for i, piece in enumerate(pieces):
            messages.append({"role": "user", "content": piece})
            messages.append({"role": "assistant", "content": "imported"})
    if messages:
        # merge consecutive messages of the same role (a skipped/limit reply would otherwise drop the user turn)
        merged = []
        for m in messages:
            if not m.get("content"):
                continue
            if merged and merged[-1]["role"] == m["role"]:
                merged[-1]["content"] += "\n\n" + m["content"]
            else:
                merged.append(dict(m))
        if merged and merged[0]["role"] == "assistant":
            merged.insert(0, {"role": "user", "content": "(start of imported chat)"})
        if merged and merged[-1]["role"] == "user":
            merged.append({"role": "assistant", "content": "(no reply)"})
        messages = merged
        # embedding is CPU work (~0.3 s per turn): run it off the event loop so the API stays responsive for others
        import asyncio
        from app import inflight as _inf
        with _inf.track("import_save"):
            saved = await asyncio.to_thread(save_pairs, user_id, messages, source)
        schedule_import_cycle(user_id, source)
        return {"status": "ok", "imported": saved, "cycle": "started"}
    return {"error": "No messages found in text"}


@router.post("/import/dialog")
async def import_dialog_raw(data: dict):
    """Accept parsed dialog from bookmarklet."""
    user_id = data.get("user_id", "bookmarklet_user")
    messages = data.get("messages", [])
    source_url = data.get("source_url", "bookmarklet")
    
    if not messages:
        return {"status": "error", "detail": "messages required"}
    
    # Save using existing logic
    db_name = user_id.replace("@", "").replace(".", "")
    conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db", timeout=10)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS event_metadata (event_id TEXT PRIMARY KEY, time_str TEXT, essence TEXT, raw_dialogue TEXT, messages_count INTEGER, topics_json TEXT, links_json TEXT, status TEXT)")
    
    saved = 0
    for i, msg in enumerate(messages):
        if msg.get("role") == "user" and i+1 < len(messages) and messages[i+1].get("role") == "assistant":
            q = msg.get("content", "")
            a = messages[i+1].get("content", "")
            eid = f"{user_id}::bookmarklet_{i}_{int(time.time())}"
            cur.execute("INSERT OR IGNORE INTO event_metadata (event_id, time_str, essence, raw_dialogue, messages_count, topics_json, links_json, status) VALUES (?,?,?,?,?,?,?,?)",
                       (eid, "", q[:200], f"Q: {q}\nA: {a}", 2, '["bookmarklet"]', "[]", "active"))
            saved += 1
    
    conn.commit()
    conn.close()
    try:
        from app.account_memory import queue_turn
        for i, msg in enumerate(messages):
            if msg.get("role") == "user" and i+1 < len(messages) and messages[i+1].get("role") == "assistant":
                queue_turn("/data/skv/metadata_store", user_id, f"{user_id}::bookmarklet_{i}", msg.get("content",""), messages[i+1].get("content",""), source="import")
    except Exception as exc:
        print(f"[memory] import queue skipped: {exc}", flush=True)
    return {"status": "ok", "message_count": saved, "source_url": source_url}

@router.post("/import/process")
async def import_process(data: dict):
    user_id = data.get("user_id", "")
    if not user_id: return {"status": "error", "detail": "user_id required"}
    db_name = user_id.replace("@", "").replace(".", "")
    conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db")
    cur = conn.cursor()
    cur.execute("SELECT raw_dialogue FROM event_metadata WHERE event_id LIKE '%::import_%' OR event_id LIKE '%::chatgpt_%' OR event_id LIKE '%::bookmarklet_%' OR event_id LIKE '%::text_import_%' OR event_id LIKE '%::url_import_%' ORDER BY event_id DESC LIMIT 200")
    texts = [_scrub(user_id, r[0]) for r in cur.fetchall() if r[0]]   # no secrets to the LLM
    if not texts: conn.close(); return {"status": "ok", "detail": "No imported data"}
    
    all_text = "\n".join(texts)[:200000]
    prompt = f"""You received {len(texts)} dialogues. SIZE RULES: L1=3-8% of input, L2=0.3-0.8%.

DO IN ONE PASS:
1. L1 SUMMARIES (3-8%): Group by topics, 2-4 sentences each
2. L2 PROFILE (0.3-0.8%): main_themes(3-5), preferences, expertise
3. CRITICAL (>>> ✅) NEVER DELETED — YOU MUST FIND AND MARK:
   LOOK FOR: passwords, API keys (sk_..., key_..., token_...), major decisions, poems
   YOU MARK them with >>> ✅ prefix even if user did not mark them
   Examples: "sk_1234567890abcdef" is API key → mark as >>> ✅, "password: secret" → mark as >>> ✅
   HOW TO SAVE BY SIZE:
   SHORT (<500 chars): put in critical_short list → saved in L2 FOREVER, never compressed
   MEDIUM (500-3000 chars): put in L1 as topic ">>> ✅ CRITICAL: title" with full text in summary
   LONG (>3000 chars, poems, documents):
     - Put FULL TEXT in permanent_chunks (never deleted)
     - In L1 add: ">>> ✅ CRITICAL: title — full text saved as permanent chunk"
     - In L2 add: reference to chunk_id
   ALL critical items MUST have >>> ✅ prefix

Return ONLY JSON: {{"l1_summaries":[{{"topic":"...","summary":"..."}}],"l2_profile":{{"main_themes":[],"preferences":{{}},"expertise":[]}},"critical_short":[],"permanent_chunks":[]}}

DIALOGUES:\n{all_text[:500000]}"""
    
    try:
        polza_key = os.environ.get("POLZA_KEY", "")
        r = urlreq.Request("https://api.polza.ai/v1/chat/completions",
            data=json.dumps({"model":"meta-llama/llama-3.1-8b-instruct","messages":[{"role":"user","content":prompt}],"temperature":0.2,"max_tokens":50000}).encode(),
            headers={"Content-Type":"application/json","Authorization":f"Bearer {polza_key}"})
        with urlreq.urlopen(r, timeout=180) as resp:
            result = json.loads(resp.read())["choices"][0]["message"]["content"]
            # Clean up
            result = re.sub(r'```json\s*', '', result)
            result = re.sub(r'```\s*', '', result)
            result = re.sub(r',\s*}', '}', result)
            result = re.sub(r',\s*]', ']', result)
            result = result.strip()
            data = json.loads(result)
            
            for item in data.get("l1_summaries",[]):
                sid = f"import_{item.get('topic','')[:20]}_{int(time.time())}"
                cur.execute("INSERT OR REPLACE INTO summary_l1 (session_id,user_id,topic,summary_text,message_count) VALUES (?,?,?,?,?)",
                           (sid, user_id, item.get("topic",""), item.get("summary",""), 1))
            if data.get("l2_profile"):
                cur.execute("INSERT OR REPLACE INTO summary_l2 (user_id,map_json,themes_json,timeline_json,session_count) VALUES (?,?,?,?,?)",
                           (user_id, json.dumps(data["l2_profile"]), "[]", "[]", len(texts)))
            for crit in data.get("critical_short",[]):
                eid = f"{user_id}::critical_{int(time.time())}"
                cur.execute("INSERT INTO event_metadata (event_id,essence,raw_dialogue,status) VALUES (?,?,?,?)",
                           (eid, crit[:200], ">>> ✅ "+crit, "critical_permanent"))
            conn.commit(); conn.close()
            return {"status":"ok","l1":len(data.get("l1_summaries",[])),"l2":bool(data.get("l2_profile")),"critical":len(data.get("critical_short",[]))}
    except Exception as e:
        conn.close()
        return {"status":"error","detail":str(e)[:200]}


def to_pairs(payload):
    """One shape out: user/assistant pairs. File or pasted text in, no remote URL."""
    if isinstance(payload, str):
        return _pairs_from_text(payload)
    if isinstance(payload, dict) and payload.get("text"):
        return _pairs_from_text(payload["text"])
    blob = payload
    if isinstance(payload, dict):
        for key in ("conversations", "messages", "chats"):
            if isinstance(payload.get(key), list):
                blob = payload[key]
                break
    pairs = []
    if isinstance(blob, list) and blob and isinstance(blob[0], dict) and "mapping" in blob[0]:
        for conv in blob:
            nodes = list((conv.get("mapping") or {}).values())
            msgs = []
            for node in nodes:
                msg = node.get("message") or {}
                role = ((msg.get("author") or {}).get("role") or "")
                parts = ((msg.get("content") or {}).get("parts") or [])
                text = " ".join(p for p in parts if isinstance(p, str))
                if role in ("user", "assistant") and text:
                    msgs.append({"role": role, "content": text})
            pairs.extend(_zip_pairs(msgs))
        return pairs
    msgs = _walk_messages(blob)
    return _zip_pairs(msgs)

def _walk_messages(node):
    found = []
    if isinstance(node, dict):
        role = node.get("role") or node.get("sender") or ""
        content = node.get("content") or node.get("text") or ""
        if isinstance(content, list):
            content = " ".join(str(x) for x in content)
        if role in ("user", "human", "assistant", "model") and content:
            found.append({"role": "user" if role in ("user", "human") else "assistant", "content": str(content)})
        for value in node.values():
            found.extend(_walk_messages(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk_messages(item))
    return found

def _zip_pairs(msgs):
    pairs = []
    for i, msg in enumerate(msgs):
        nxt = msgs[i + 1] if i + 1 < len(msgs) else {}
        if msg.get("role") == "user" and nxt.get("role") == "assistant":
            pairs.append(msg)
            pairs.append(nxt)
    return pairs

def _pairs_from_text(text):
    chunks = re.split(r"\n(?=(?:User|Human|Assistant|Grok|Q|A)\s*:)", text)
    msgs = []
    for chunk in chunks:
        if ":" not in chunk:
            continue
        head, body = chunk.split(":", 1)
        role = "user" if head.strip().lower() in ("user", "human", "q") else "assistant"
        if body.strip():
            msgs.append({"role": role, "content": body.strip()})
    return _zip_pairs(msgs)

@router.post("/import/file")
async def import_file(data: dict):
    user_id = data.get("user_id", "")
    if not user_id:
        return {"status": "error", "detail": "user_id required"}
    pairs = to_pairs(data.get("payload") if "payload" in data else data.get("text", ""))
    source = data.get("source", "import")
    saved = save_pairs(user_id, pairs, source)
    if saved:
        schedule_import_cycle(user_id, source)
    return {"status": "ok", "imported": saved, "cycle": "started"}

import json, os, sqlite3, threading, urllib.request

def _polza(prompt, system="", max_tokens=500):
    key = os.environ.get("POLZA_KEY", "")
    if not key:
        for line in open("/root/skv-core/.env"):
            if line.startswith("POLZA_KEY="):
                key = line.split("=", 1)[1].strip()
    req = urllib.request.Request(
        "https://api.polza.ai/v1/chat/completions",
        data=json.dumps({"model": "meta-llama/llama-3.1-8b-instruct", "messages": ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": max_tokens}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"]

def run_import_cycle(user_id, source):
    name = user_id.replace("@", "").replace(".", "")
    db = sqlite3.connect(f"/data/skv/metadata_store/{name}.db")
    db.execute("CREATE TABLE IF NOT EXISTS summary_l1 (session_id TEXT PRIMARY KEY, user_id TEXT, topic TEXT, summary_text TEXT, summary_json TEXT, message_count INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    rows = db.execute("select rowid, event_id, raw_dialogue from event_metadata where event_id like ? order by rowid", (f"%::{source}_%",)).fetchall()
    window, rids = [], []
    summaries = []
    n = 0
    for rid, eid, text in rows:
        window.append((text or "")[:1200])
        rids.append(rid)
        if len(window) >= 60:
            summaries.append(_one_l1(db, user_id, source, n, window, rids[0], rids[-1]))
            window, rids = [], []
            n += 1
    if window:
        summaries.append(_one_l1(db, user_id, source, n, window, rids[0], rids[-1]))
    if [x for x in summaries if x]:
        _one_l2(db, user_id, summaries, source, rows[0][0], rows[-1][0])
    db.close()

_L1_SYSTEM = ("Ты пишешь L1-выжимку куска чата для долгой памяти. Ответ только JSON-объект без текста до и после, "
              "ключи: summary (строка, 3-6 предложений на языке диалога: решения, числа, имена, открытые задачи) и "
              "critical (список коротких строк: даты, планы, точные формулировки). Не пароли и не ключи.")
_L1_ECHO = ("3-6 предложений", "на языке диалога", "\"...\"")


def _l1_parse(content):
    """Llama often ignores 'JSON only' on long Russian windows or runs out of tokens mid-JSON.
    Plain text is kept as the summary; a cut JSON keeps its summary string; a prompt echo is dropped."""
    s = (content or "").strip()
    a, b = s.find("{"), s.rfind("}")
    d = None
    if a >= 0 and b > a:
        try:
            d = json.loads(s[a:b + 1])
        except Exception:
            d = None
    if not isinstance(d, dict):
        m = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)', s)
        if m:
            try:
                summ = json.loads('"' + m.group(1) + '"')
            except Exception:
                summ = m.group(1)
            d = {"summary": summ, "critical": []}
        elif a >= 0:
            d = {"summary": "", "critical": []}
        else:
            d = {"summary": s, "critical": []}
    summ = str(d.get("summary") or "")
    if any(e in summ for e in _L1_ECHO):
        d["summary"] = ""
    return d


def _one_l1(db, user_id, source, n, parts, from_rowid=None, to_rowid=None):
    import hashlib
    parts = [_scrub(user_id, p) for p in parts]   # defence in depth: nothing secret goes to the summarizer
    wsha = hashlib.sha1("\n---\n".join(parts).encode("utf-8", "replace")).hexdigest()
    try:
        old = db.execute("select summary_text, summary_json from summary_l1 where session_id=?", (f"{source}_auto_{n}",)).fetchone()
        if (old and old[0] and old[1] and json.loads(old[1]).get("window_sha") == wsha
                and not old[0].lstrip().startswith("{") and not any(e in old[0] for e in _L1_ECHO)):
            if from_rowid is not None:   # keep the range exact even for cached windows
                db.execute("update summary_l1 set from_rowid=?, to_rowid=? where session_id=?", (from_rowid, to_rowid, f"{source}_auto_{n}"))
                db.commit()
            return old[0]   # same window already summarized: no new LLM call, no duplicate critical candidates
    except Exception:
        pass
    prompt = "По сырому окну, не по выжимке. L1 5-7 процентов, 3-6 предложений. В critical положи даты, планы, схемы и точные формулировки, даже если они не вошли в summary. Не пароли. Только JSON {\"summary\":\"...\",\"critical\":[\"...\"]}.\n\n" + "\n---\n".join(parts) + "\n\n---\nОтвет: только JSON {\"summary\":\"...\",\"critical\":[\"...\"]}."
    try:
        data = _l1_parse(_polza(prompt, system=_L1_SYSTEM, max_tokens=900))
    except Exception as exc:
        print(f"[IMPORT] L1 window {source}_{n} failed: {exc}", flush=True)
        data = {"summary": "", "critical": []}
    summary = _scrub(user_id, str(data.get("summary") or "").strip())[:3000]
    if len(summary) >= 40:
        db.execute("insert or replace into summary_l1 (session_id,user_id,topic,summary_text,summary_json,message_count,from_rowid,to_rowid) values (?,?,?,?,?,?,?,?)",
                   (f"{source}_auto_{n}", user_id, source, summary, json.dumps({"window_sha": wsha, "source": "import"}), len(parts), from_rowid, to_rowid))
    else:
        summary = ""
    db.execute("CREATE TABLE IF NOT EXISTS critical_candidates (id INTEGER PRIMARY KEY, user_id TEXT, text TEXT, status TEXT, created_at TEXT)")
    marks = list(data.get("critical") or [])
    for part in parts:
        if ">>>" in part:
            marks.append(part[part.find(">>>"):][:240])
    for item in marks[:8]:
        low = str(item).lower()
        if any(w in low for w in ("парол", "password", "token", "fact1", "fact2")):
            continue
        if db.execute("select 1 from critical_candidates where user_id=? and text=? limit 1", (user_id, str(item)[:300])).fetchone():
            continue
        db.execute("insert into critical_candidates (user_id, text, status, created_at) values (?,?,?,datetime('now'))",
                   (user_id, str(item)[:300], "pending"))
    db.commit()
    return summary

def _one_l2(db, user_id, summaries, source="import", from_rowid=None, to_rowid=None):
    summaries = [_scrub(user_id, x) for x in summaries]
    text = "\n".join(s[:300] for s in summaries if s)[:50000]
    system = ("Ты собираешь L2-карту импортированного чата для долгой памяти: 4-8 предложений на русском о главных темах, "
              "решениях, планах и датах из выжимок ниже. Ответ только JSON-объект с одним ключом map (строка). Не пароли.")
    try:
        content = _polza("Выжимки по порядку:\n\n" + text + "\n\nОтвет: только JSON с ключом map.", system=system, max_tokens=700)
        s_ = content.strip()
        try:
            mp = json.loads(s_[s_.find("{"):s_.rfind("}") + 1]).get("map") or ""
        except Exception:
            m = re.search(r'"map"\s*:\s*"((?:[^"\\]|\\.)*)', s_)
            mp = m.group(1) if m else ("" if "{" in s_ else s_)
    except Exception:
        mp = ""
    mp = str(mp).strip()
    if len(mp) < 80 or mp.lower().startswith(("темы, планы", "темы: ...")):   # prompt echo or empty: keep nothing
        mp = ""
    if mp:
        # an import map describes this import only: store it as an L2 block for its rowid range and never
        # overwrite the account-wide summary_l2 (it feeds the memory map of every request)
        try:
            _t = lambda r: (db.execute("select time_str from event_metadata where rowid=?", (r,)).fetchone() or [None])[0]
            db.execute("INSERT OR REPLACE INTO summary_l2_blocks (user_id, source, period_key, period_from, period_to, from_rowid, to_rowid, topics_json, text) VALUES (?,?,?,?,?,?,?,?,?)",
                       (user_id, "import", f"import:{source}", _t(from_rowid), _t(to_rowid), from_rowid, to_rowid, "[]", _scrub(user_id, mp)[:4000]))
        except sqlite3.OperationalError:
            pass
        db.execute("CREATE TABLE IF NOT EXISTS summary_l2 (user_id TEXT PRIMARY KEY, map_json TEXT, themes_json TEXT, timeline_json TEXT, session_count INTEGER, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        if not db.execute("SELECT 1 FROM summary_l2 LIMIT 1").fetchone():
            db.execute("INSERT INTO summary_l2 (user_id, map_json, themes_json, timeline_json, session_count) VALUES (?,?,?,?,?)",
                       (user_id, _scrub(user_id, mp)[:4000], "[]", "[]", len(summaries)))
        db.commit()

_cycle_lock = threading.Lock()
_cycle_state = {}   # (user_id, source) -> "running" | "again"

def schedule_import_cycle(user_id, source):
    """One summary cycle per user+source at a time; imports that arrive meanwhile trigger exactly one re-run."""
    key = (user_id, source)
    with _cycle_lock:
        if key in _cycle_state:
            _cycle_state[key] = "again"
            return
        _cycle_state[key] = "running"
    def _loop():
        try:
            while True:
                try:
                    from app import inflight as _inf
                    with _inf.track("import_cycle_run"):
                        run_import_cycle(user_id, source)
                except Exception as e:
                    print(f"[IMPORT] cycle error {user_id} {source}: {e}", flush=True)
                with _cycle_lock:
                    if _cycle_state.get(key) == "again":
                        _cycle_state[key] = "running"
                        continue
                    _cycle_state.pop(key, None)
                    return
        except Exception:
            with _cycle_lock:
                _cycle_state.pop(key, None)
    threading.Thread(target=_loop, daemon=True).start()

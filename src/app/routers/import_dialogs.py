"""Import external chat history with Llama processing."""
from fastapi import APIRouter, HTTPException
import json, urllib.request as urlreq, os, sqlite3, time, re

router = APIRouter()

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
            q, a, ts = msg.get("content",""), messages[i+1].get("content",""), msg.get("timestamp","")
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
        saved = save_pairs(user_id, messages, source)
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
    texts = [r[0] for r in cur.fetchall() if r[0]]
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

def _polza(prompt):
    key = os.environ.get("POLZA_KEY", "")
    if not key:
        for line in open("/root/skv-core/.env"):
            if line.startswith("POLZA_KEY="):
                key = line.split("=", 1)[1].strip()
    req = urllib.request.Request(
        "https://api.polza.ai/v1/chat/completions",
        data=json.dumps({"model": "meta-llama/llama-3.1-8b-instruct", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 500}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"]

def run_import_cycle(user_id, source):
    name = user_id.replace("@", "").replace(".", "")
    db = sqlite3.connect(f"/data/skv/metadata_store/{name}.db")
    rows = db.execute("select event_id, raw_dialogue from event_metadata where event_id like ? order by event_id", (f"%::{source}_%",)).fetchall()
    window = []
    summaries = []
    n = 0
    for eid, text in rows:
        window.append((text or "")[:1200])
        if len(window) >= 60:
            summaries.append(_one_l1(db, user_id, source, n, window))
            window = []
            n += 1
    if window:
        summaries.append(_one_l1(db, user_id, source, n, window))
    if summaries:
        _one_l2(db, user_id, summaries)
    db.close()

def _one_l1(db, user_id, source, n, parts):
    prompt = "По сырому окну, не по выжимке. L1 5-7 процентов, 3-6 предложений. В critical положи даты, планы, схемы и точные формулировки, даже если они не вошли в summary. Не пароли. Только JSON {\"summary\":\"...\",\"critical\":[\"...\"]}.\n\n" + "\n---\n".join(parts)
    try:
        content = _polza(prompt)
        data = json.loads(content[content.find("{"):content.rfind("}")+1])
    except Exception:
        data = {"summary": "", "critical": []}
    summary = (data.get("summary") or "")[:3000]
    if summary:
        db.execute("insert or replace into summary_l1 (session_id,user_id,topic,summary_text,message_count) values (?,?,?,?,?)",
                   (f"{source}_auto_{n}", user_id, source, summary, len(parts)))
    db.execute("CREATE TABLE IF NOT EXISTS critical_candidates (id INTEGER PRIMARY KEY, user_id TEXT, text TEXT, status TEXT, created_at TEXT)")
    marks = list(data.get("critical") or [])
    for part in parts:
        if ">>>" in part:
            marks.append(part[part.find(">>>"):][:240])
    for item in marks[:8]:
        low = str(item).lower()
        if any(w in low for w in ("парол", "password", "token", "fact1", "fact2")):
            continue
        db.execute("insert into critical_candidates (user_id, text, status, created_at) values (?,?,?,datetime('now'))",
                   (user_id, str(item)[:300], "pending"))
    db.commit()
    return summary

def _one_l2(db, user_id, summaries):
    text = "\n".join(s[:300] for s in summaries if s)[:50000]
    prompt = "Собери одну короткую L2 карту на русском: темы, планы, даты. Не пароли. Только JSON {\"map\":\"...\"}.\n\n" + text
    try:
        content = _polza(prompt)
        data = json.loads(content[content.find("{"):content.rfind("}")+1])
        mp = data.get("map") or ""
    except Exception:
        mp = ""
    if mp:
        db.execute("CREATE TABLE IF NOT EXISTS summary_l2 (user_id TEXT PRIMARY KEY, map_json TEXT, themes_json TEXT, timeline_json TEXT, session_count INTEGER, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        db.execute("INSERT OR REPLACE INTO summary_l2 (user_id, map_json, themes_json, timeline_json, session_count) VALUES (?,?,?,?,?)",
                   (user_id, mp[:4000], "[]", "[]", len(summaries)))
        db.commit()

def schedule_import_cycle(user_id, source):
    threading.Thread(target=run_import_cycle, args=(user_id, source), daemon=True).start()

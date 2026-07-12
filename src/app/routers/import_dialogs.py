"""Import external chat history with Llama processing."""
from fastapi import APIRouter, HTTPException
import json, urllib.request as urlreq, os, sqlite3, time, re

router = APIRouter()

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
            cur.execute("INSERT OR IGNORE INTO event_metadata (event_id, time_str, essence, raw_dialogue, messages_count, topics_json, links_json, status) VALUES (?,?,?,?,?,?,?,?)",
                       (eid, ts or "?", q[:200], f"Q: {q}\nA: {a}", 2, f'["{source}"]', "[]", "active"))
            saved += 1
    conn.commit(); conn.close()
    return {"status": "ok", "imported": saved}

@router.post("/import/process")
async def import_process(data: dict):
    user_id = data.get("user_id", "")
    if not user_id: return {"status": "error", "detail": "user_id required"}
    db_name = user_id.replace("@", "").replace(".", "")
    conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db")
    cur = conn.cursor()
    cur.execute("SELECT raw_dialogue FROM event_metadata WHERE event_id LIKE '%::import_%' OR event_id LIKE '%::chatgpt_%' ORDER BY event_id DESC LIMIT 200")
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
            data=json.dumps({"model":"deepseek/deepseek-v4-flash","messages":[{"role":"user","content":prompt}],"temperature":0.2,"max_tokens":50000}).encode(),
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

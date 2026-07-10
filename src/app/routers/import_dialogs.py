"""Import external chat history with Llama processing."""
from fastapi import APIRouter, HTTPException
import json, urllib.request as urlreq, os, sqlite3, time

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
    
    # Create tables if needed
    cur.execute("CREATE TABLE IF NOT EXISTS event_metadata (event_id TEXT PRIMARY KEY, time_str TEXT, essence TEXT, raw_dialogue TEXT, messages_count INTEGER, topics_json TEXT, links_json TEXT, status TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS chat_sessions (session_id TEXT PRIMARY KEY, user_id TEXT, messages_json TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cur.execute("CREATE TABLE IF NOT EXISTS summary_l1 (session_id TEXT PRIMARY KEY, user_id TEXT, topic TEXT, summary_text TEXT, summary_json TEXT, message_count INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cur.execute("CREATE TABLE IF NOT EXISTS summary_l2 (user_id TEXT PRIMARY KEY, map_json TEXT, themes_json TEXT, timeline_json TEXT, session_count INTEGER, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    
    # Save messages
    saved = 0
    for i, msg in enumerate(messages):
        if msg.get("role") == "user" and i+1 < len(messages) and messages[i+1].get("role") == "assistant":
            q = msg.get("content", "")
            a = messages[i+1].get("content", "")
            ts = msg.get("timestamp", "")
            eid = f"{user_id}::{source}_{i}"
            cur.execute("INSERT OR IGNORE INTO event_metadata (event_id, time_str, essence, raw_dialogue, messages_count, topics_json, links_json, status) VALUES (?,?,?,?,?,?,?,?)",
                       (eid, ts or "?", q[:200], f"Q: {q}\nA: {a}", 2, f'["{source}"]', "[]", "active"))
            saved += 1
    
    conn.commit()
    conn.close()
    
    return {
        "status": "ok",
        "imported": saved,
        "source": source
    }

@router.post("/import/process")
async def import_process(data: dict):
    """Run Llama to create L1+L2+Critical from imported data."""
    user_id = data.get("user_id", "")
    
    if not user_id:
        return {"status": "error", "detail": "user_id required"}
    
    db_name = user_id.replace("@", "").replace(".", "")
    conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db")
    cur = conn.cursor()
    
    # Get recent imported events
    cur.execute("SELECT raw_dialogue FROM event_metadata WHERE topics_json LIKE '%import%' ORDER BY event_id DESC LIMIT 200")
    texts = [r[0] for r in cur.fetchall() if r[0]]
    
    if not texts:
        conn.close()
        return {"status": "ok", "detail": "No imported data to process"}
    
    all_text = "\n".join(texts)[:300000]
    
    prompt = f"""You received {len(texts)} dialogues from user {user_id}.

DO IN ONE PASS:
1. L1 SUMMARIES: Group by topics, 2-3 sentences each
2. L2 PROFILE: main_themes, preferences, expertise
3. CRITICAL (>>> ✅): passwords, keys, decisions
   - SHORT (<500 chars) → put in L2
   - MEDIUM (500-3000 chars) → put in L1

Return ONLY valid JSON:
{{"l1_summaries":[{{"topic":"...","summary":"..."}}],"l2_profile":{{"main_themes":[],"preferences":{{}},"expertise":[]}},"critical_short":["API_KEY=xxx"]}}

USER DATA:
{all_text[:250000]}"""
    
    try:
        polza_key = os.environ.get("POLZA_KEY", "")
        req_body = json.dumps({
            "model": "meta-llama/llama-3.1-8b-instruct",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 4000
        }).encode()
        
        r = urlreq.Request("https://api.polza.ai/v1/chat/completions",
            data=req_body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {polza_key}"})
        
        with urlreq.urlopen(r, timeout=180) as resp:
            result = json.loads(resp.read())["choices"][0]["message"]["content"]
            data = json.loads(result)
            
            # Save L1
            l1_count = 0
            for item in data.get("l1_summaries", []):
                sid = f"import_{item.get('topic','')[:20]}_{int(time.time())}"
                cur.execute("INSERT OR REPLACE INTO summary_l1 (session_id, user_id, topic, summary_text, message_count) VALUES (?,?,?,?,?)",
                           (sid, user_id, item.get("topic",""), item.get("summary",""), len(texts)))
                l1_count += 1
            
            # Save L2
            if data.get("l2_profile"):
                cur.execute("INSERT OR REPLACE INTO summary_l2 (user_id, map_json, themes_json, timeline_json, session_count) VALUES (?,?,?,?,?)",
                           (user_id, json.dumps(data["l2_profile"]), "[]", "[]", len(texts)))
            
            conn.commit()
            conn.close()
            
            return {
                "status": "ok",
                "l1_created": l1_count,
                "l2_updated": bool(data.get("l2_profile")),
                "critical_found": len(data.get("critical_short", []))
            }
    except Exception as e:
        conn.close()
        return {"status": "error", "detail": str(e)}

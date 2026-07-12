"""Background tasks with proper DB connection management."""
import sqlite3, os, time, json, urllib.request, threading

def _get_polza_key():
    return os.environ.get("POLZA_KEY", "")

def process_l1_l2():
    """Generate L1/L2 for all users. Opens DB only during work."""
    polza_key = _get_polza_key()
    if not polza_key:
        return
    
    base = '/data/skv/metadata_store'
    for db_file in os.listdir(base):
        if not db_file.endswith('.db') or db_file in ['shared_master.db', 'anonymous.db']:
            continue
        
        user_id = db_file.replace('.db', '').replace('gmailcom', '@gmail.com')
        db_path = os.path.join(base, db_file)
        
        # Open DB only for this user
        conn = sqlite3.connect(db_path, timeout=10)
        cur = conn.cursor()
        
        try:
            # Create tables if needed
            cur.execute("CREATE TABLE IF NOT EXISTS summary_l1 (session_id TEXT PRIMARY KEY, user_id TEXT, topic TEXT, summary_text TEXT, summary_json TEXT, message_count INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            cur.execute("CREATE TABLE IF NOT EXISTS summary_l2 (user_id TEXT PRIMARY KEY, map_json TEXT, themes_json TEXT, timeline_json TEXT, session_count INTEGER, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            
            # Check if L1 needed
            cur.execute("SELECT COUNT(*) FROM event_metadata")
            total_events = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM summary_l1")
            l1_count = cur.fetchone()[0]
            
            if total_events > 0 and (l1_count == 0 or total_events - l1_count * 10 > 15):
                cur.execute("SELECT essence FROM event_metadata ORDER BY event_id DESC LIMIT 30")
                essences = [r[0] for r in cur.fetchall() if r[0]]
                if essences:
                    text = "\n".join(essences[-15:])
                    prompt = f"Summarize these interactions in 2-3 sentences:\n{text}"
                    try:
                        req = urllib.request.Request("https://api.polza.ai/v1/chat/completions",
                            data=json.dumps({"model":"meta-llama/llama-3.1-8b-instruct","messages":[{"role":"user","content":prompt}],"temperature":0.2,"max_tokens":300}).encode(),
                            headers={"Content-Type":"application/json","Authorization":f"Bearer {polza_key}"})
                        with urllib.request.urlopen(req, timeout=30) as resp:
                            summary = json.loads(resp.read())["choices"][0]["message"]["content"]
                            cur.execute("INSERT INTO summary_l1 (user_id,topic,summary_text,message_count) VALUES (?,?,?,?)",
                                       (user_id, "auto", summary, 15))
                            print(f"[L1] {user_id}")
                    except Exception as e:
                        print(f"[L1] Error: {e}")
            
            conn.commit()
        except Exception as e:
            print(f"[L1/L2] {db_file}: {e}")
        finally:
            conn.close()

def run_l1_l2_loop():
    """Run L1/L2 generation every 15 minutes with proper DB handling."""
    while True:
        try:
            process_l1_l2()
        except Exception as e:
            print(f"[L1/L2] Loop error: {e}")
        time.sleep(900)  # 15 minutes

def start_background_tasks():
    """Start all background tasks."""
    t = threading.Thread(target=run_l1_l2_loop, daemon=True)
    t.start()
    print("[BG] Background tasks started (L1/L2 every 15 min)")

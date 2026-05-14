"""SKV Evolver v1.1 — Grok-4 Deep Analysis + Auto-Trial Trigger."""
import json, urllib.request as req, time, random, os
from datetime import datetime

POLZA_KEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"
MODEL = "x-ai/grok-4"
SKV_SEARCH = "https://skv.network/api/cubes/search"
SKV_FEEDBACK = "https://skv.network/api/feedback"
SKV_TRIAL = "https://skv.network/api/trial"
LOG_FILE = "/root/skv-core/data/evolver.log"

def log(msg):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

def get_system_load():
    try:
        load_str = os.popen("uptime").read().strip()
        return float(load_str.split("load average:")[1].split(",")[0].strip()) * 100
    except:
        return 50

def check_and_trigger_trials():
    """Проверяет кубики с 3+ дизлайками без активного Суда и запускает Trials"""
    try:
        # Получаем кубики с 3+ дизлайками через API
        resp = req.urlopen("https://skv.network/api/v1/trials", timeout=10)
        trials_data = json.loads(resp.read())
        pending = [(t['cube_id'], t['downvotes']) for t in trials_data.get('trials', [])]
        
        if pending:
            log(f"⚖️ Found {len(pending)} cube(s) pending trial")
            for row in pending:
                cube_id = row[0]
                log(f"  🚀 Triggering trial for {cube_id}...")
                
                # Получаем полные данные кубика
                try:
                    cube_resp = req.urlopen(f"https://skv.network/api/v1/entries/{cube_id}", timeout=10)
                    cube_data = json.loads(cube_resp.read())
                    cube_content = cube_data.get('content', {})
                    cube_title = cube_content.get('title', cube_data.get('title', 'Untitled'))
                    cube_rules = cube_content.get('rules', [])
                except:
                    cube_title = 'Untitled'
                    cube_rules = []

                body = json.dumps({"cube_id": cube_id, "cube_title": cube_title, "rules": cube_rules}).encode()
                r = req.Request(SKV_TRIAL, data=body,
                               headers={"Content-Type": "application/json"})
                resp = json.loads(req.urlopen(r, timeout=120).read())
                
                verdict = resp.get('verdict', 'unknown')
                log(f"  ⚖️ Trial complete — Verdict: {verdict}")
        else:
            log("  No pending trials")
    except Exception as e:
        log(f"  ❌ Trial check error: {e}")

def get_random_cubes(limit=5):
    try:
        resp = req.urlopen(f"{SKV_SEARCH}?query=&limit=200", timeout=10)
        data = json.loads(resp.read())
        all_cubes = data.get('results', [])
        eligible = [c for c in all_cubes if c.get('type', 'experience') in ('experience', 'basic') and c.get('status') != 'verified']
        return random.sample(eligible, min(limit, len(eligible)))
    except Exception as e:
        log(f"❌ Search error: {e}")
        return []

def deep_analyze(cube):
    cube_id = cube.get('cube_id', 'unknown')
    
    try:
        resp = req.urlopen(f"https://skv.network/api/v1/entries/{cube_id}", timeout=10)
        full = json.loads(resp.read())
        content = full.get('content', {})
        rules = content.get('rules', [])
        title = full.get('title', '')
    except:
        rules = []
        title = cube.get('title', '')
    
    if not rules or len(rules) == 0:
        return "REMOVE: Empty cube"
    
    prompt = f"""You are SKV Evolver. Analyze this cube deeply.

CUBE: {cube_id}
TITLE: {title}
RULES ({len(rules)}):
{json.dumps(rules, indent=1)[:400]}

Score 1-10: Specificity, Usefulness, Safety.
Verdict: KEEP (≥7) | FIX (4-6, give 1-2 suggestions) | REMOVE (≤3).
Return: VERDICT: [X] | SCORE: [X] | REASON: [1 sentence] | SUGGESTIONS: [if FIX]"""
    
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 300
    }).encode()
    
    r = req.Request("https://api.polza.ai/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"})
    
    resp = json.loads(req.urlopen(r, timeout=60).read())
    return resp["choices"][0]["message"]["content"].strip()

def submit_to_trials(cube_id, verdict):
    if "REMOVE" not in verdict.upper() and "FIX" not in verdict.upper():
        return False
    
    voters = [
        {"token": "evolver_token_001"},
        {"token": "evolver_token_002"},
        {"token": "bc2dc116"},
    ]
    
    for voter in voters:
        try:
            body = json.dumps({
                "cube_id": cube_id,
                "vote": "down",
                "comment": f"Evolver: {verdict[:100]}"
            }).encode()
            req.urlopen(req.Request(SKV_FEEDBACK, data=body, 
                       headers={"Content-Type": "application/json"}), timeout=10)
        except:
            pass
    
    return True

def save_fixed_cubes():
    """Сохраняет исправленные кубики, созданные fixer'ом в Trials"""
    try:
        import psycopg2 as pg2
        pg_conn = pg2.connect(
            host="127.0.0.1", port=5432,
            dbname="skv_db", user="skv_user", password="skv_secret_2026"
        )
        cur = pg_conn.cursor()
        
        # Находим trials с вердиктом fix, где fixer создал кубик (comment содержит JSON)
        cur.execute("""
            SELECT cube_id, scores 
            FROM trials 
            WHERE verdict = 'fix' 
            AND scores::text LIKE '%grok-4-fixer%'
            AND fixed_cube IS NULL
            ORDER BY created_at DESC
            LIMIT 5
        """)
        
        for row in cur.fetchall():
            cube_id = row[0]
            scores = row[1]
            
            # Ищем комментарий fixer'а с JSON
            for s in scores:
                if s.get('model') == 'grok-4-fixer':
                    comment = s.get('comment', '')
                    if comment and comment.startswith('{'):
                        try:
                            fixed_cube = json.loads(comment)
                            fixed_cube['cube_id'] = f"cube_exp_{cube_id}_fixed_v2"
                            fixed_cube['type'] = 'experience'
                            fixed_cube['priority'] = 3
                            fixed_cube['version'] = '2.0'
                            fixed_cube['source'] = 'SKV Trials Fixer'
                            fixed_cube['status'] = 'community'
                            
                            # Сохраняем кубик через API
                            body = json.dumps({"cubes": [fixed_cube]}).encode()
                            r = req.Request("https://skv.network/api/v1/entries", data=body, headers={"Content-Type": "application/json"})
                            resp = json.loads(req.urlopen(r, timeout=60).read())
                            
                            # Отмечаем, что кубик сохранён
                            cur.execute(
                                "UPDATE trials SET fixed_cube = %s WHERE cube_id = %s",
                                (json.dumps(fixed_cube), cube_id)
                            )
                            pg_conn.commit()
                            
                            log(f"  ✅ Fixed cube saved: {fixed_cube.get('cube_id', '?')}")
                        except Exception as e:
                            log(f"  ❌ Fixer save error: {str(e)[:100]}")
        
        cur.close()
        pg_conn.close()
    except Exception as e:
        log(f"  ❌ Fixer check error: {str(e)[:100]}")

# Добавляем вызов в цикл аудита
# Ищем строку "log(\"🔍 Deep audit cycle — Grok-4 analysis\")" и добавляем перед ней вызов

def run_audit_cycle():
    log("=" * 50)
    # Сохраняем исправленные кубики от fixer'а
    save_fixed_cubes()
    
    log("🔍 Deep audit cycle — Grok-4 analysis")
    
    # 1. Проверяем и запускаем Суд для кубиков с 3+ дизлайками
    check_and_trigger_trials()
    
    # 2. Аудит кубиков
    cubes = get_random_cubes(5)
    if not cubes:
        log("❌ No eligible cubes found")
        return
    
    results = {"KEEP": 0, "FIX": 0, "REMOVE": 0}
    
    for cube in cubes:
        cube_id = cube.get('cube_id', '?')
        log(f"  📦 {cube_id}")
        
        verdict = deep_analyze(cube)
        log(f"  📝 {verdict[:200]}")
        
        if "KEEP" in verdict.upper():
            results["KEEP"] += 1
        elif "FIX" in verdict.upper():
            results["FIX"] += 1
            submit_to_trials(cube_id, verdict)
        elif "REMOVE" in verdict.upper():
            results["REMOVE"] += 1
            submit_to_trials(cube_id, verdict)
        
        time.sleep(0.5)
    
    log(f"  Results: ✅{results['KEEP']} 🔧{results['FIX']} ❌{results['REMOVE']}")
    log("✅ Deep audit complete")

# ====================== MAIN LOOP ======================
log("🛡️ SKV Evolver v1.1 — Grok-4 + Auto-Trial Trigger (every 4h)")

while True:
    load = get_system_load()
    log(f"System load: {load:.0f}%")
    
    if load < 30:
        run_audit_cycle()
    else:
        log(f"⏸️ Load too high ({load:.0f}%), skipping")
    
    log(f"💤 Sleeping 4 hours...")
    time.sleep(14400)



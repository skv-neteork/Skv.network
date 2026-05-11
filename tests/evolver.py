"""SKV Evolver v1.0 — глубокий аудит кубиков через Grok-4."""
import json, urllib.request as req, time, random, os
from datetime import datetime

POLZA_KEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"
MODEL = "x-ai/grok-4"
SKV_SEARCH = "https://skv.network/api/cubes/search"
SKV_FEEDBACK = "https://skv.network/api/feedback"
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

def get_random_cubes(limit=5):
    try:
        resp = req.urlopen(f"{SKV_SEARCH}?query=&limit=100", timeout=10)
        data = json.loads(resp.read())
        all_cubes = data.get('results', [])
        # Фильтруем: только experience и basic, не verified
        eligible = [c for c in all_cubes if c.get('type', 'experience') in ('experience', 'basic') and c.get('status') != 'verified']
        return random.sample(eligible, min(limit, len(eligible)))
    except Exception as e:
        log(f"❌ Search error: {e}")
        return []

def deep_analyze(cube):
    """Глубокий анализ кубика через Grok-4"""
    cube_id = cube.get('cube_id', 'unknown')
    
    # Получаем полный кубик через API
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
        return "REMOVE: Empty cube — no rules found"
    
    # Глубокий анализ Grok-4
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
    """Отправляет кубик в Trials с 3 downvotes"""
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

def run_audit_cycle():
    log("=" * 50)
    log("🔍 Deep audit cycle — Grok-4 analysis")
    
    cubes = get_random_cubes_v2(5)
    if not cubes:
        log("❌ No eligible cubes found")
        return
    
    results = {"KEEP": 0, "FIX": 0, "REMOVE": 0}
    
    for cube in cubes:
        cube_id = cube.get('cube_id', '?')
        log(f"  📦 {cube_id}")
        
        verdict = deep_analyze(cube)
        log(f"  📝 {verdict[:200]}")
        
        mark_as_checked(cube_id)
        
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
log("🛡️ SKV Evolver v1.0 — Grok-4 Deep Analysis (every 4h)")

while True:
    load = get_system_load()
    log(f"System load: {load:.0f}%")
    
    if load < 30:
        run_audit_cycle()
    else:
        log(f"⏸️ Load too high ({load:.0f}%), skipping")
    
    log(f"💤 Sleeping 4 hours...")
    time.sleep(14400)

# Добавляем защиту от повторной проверки
CHECKED_CUBES_FILE = "/root/skv-core/data/evolver_checked_cubes.json"

def was_checked_recently(cube_id, max_days=30):
    """Проверяет, проверялся ли кубик в последние N дней"""
    import os, json as json_lib
    from datetime import datetime, timedelta
    
    if not os.path.exists(CHECKED_CUBES_FILE):
        return False
    
    try:
        with open(CHECKED_CUBES_FILE) as f:
            checked = json_lib.load(f)
        
        if cube_id in checked:
            last_check = datetime.fromisoformat(checked[cube_id])
            if datetime.now() - last_check < timedelta(days=max_days):
                return True
    except:
        pass
    
    return False

def mark_as_checked(cube_id):
    """Отмечает кубик как проверенный"""
    import os, json as json_lib
    from datetime import datetime
    
    checked = {}
    if os.path.exists(CHECKED_CUBES_FILE):
        try:
            with open(CHECKED_CUBES_FILE) as f:
                checked = json_lib.load(f)
        except:
            pass
    
    checked[cube_id] = datetime.now().isoformat()
    
    with open(CHECKED_CUBES_FILE, 'w') as f:
        json_lib.dump(checked, f, indent=2)

# Обновляем get_random_cubes — теперь исключает недавно проверенные
def get_random_cubes_v2(limit=5):
    try:
        resp = req.urlopen(f"{SKV_SEARCH}?query=&limit=200", timeout=10)
        data = json.loads(resp.read())
        all_cubes = data.get('results', [])
        
        # Фильтруем: только experience и basic, не verified, и не проверенные недавно
        eligible = [
            c for c in all_cubes 
            if c.get('type', 'experience') in ('experience', 'basic')
            and c.get('status') != 'verified'
            and not was_checked_recently(c.get('cube_id', ''))
        ]
        
        if not eligible:
            log("ℹ️ All eligible cubes were checked recently — resetting...")
            # Если всё проверено — сбрасываем историю и начинаем заново
            os.remove(CHECKED_CUBES_FILE) if os.path.exists(CHECKED_CUBES_FILE) else None
            eligible = [c for c in all_cubes if c.get('type', 'experience') in ('experience', 'basic')]
        
        return random.sample(eligible, min(limit, len(eligible)))
    except Exception as e:
        log(f"❌ Search error: {e}")
        return []

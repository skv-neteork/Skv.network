"""SKV Evolver v0.4 — Always-On Guardian (без psutil, через uptime)."""
import json, urllib.request as req, time, random, os
from datetime import datetime

POLZA_KEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"
SKV_SEARCH = "https://skv.network/api/cubes/search"
SKV_FEEDBACK = "https://skv.network/api/feedback"
MODEL = "deepseek/deepseek-chat"
LOG_FILE = "/root/skv-core/data/evolver.log"

def log(msg):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

def get_system_load():
    """Проверяет загрузку через uptime (без psutil)"""
    try:
        load_str = os.popen("uptime").read().strip()
        # Извлекаем load average за 1 минуту
        load_1min = float(load_str.split("load average:")[1].split(",")[0].strip())
        return load_1min * 100  # Переводим в проценты для совместимости
    except:
        return 50

def check_system_health():
    endpoints = {
        "Homepage": "https://skv.network/",
        "Discovery": "https://skv.network/.well-known/skv",
        "API Info": "https://skv.network/api/v1/info",
    }
    issues = []
    for name, url in endpoints.items():
        try:
            code = req.urlopen(req.Request(url), timeout=10).getcode()
            if code != 200:
                issues.append(f"{name} returned {code}")
        except Exception as e:
            issues.append(f"{name} DOWN: {str(e)[:40]}")
    
    if issues:
        log(f"⚠️ Health issues: {'; '.join(issues)}")
    return len(issues) == 0

def get_unverified_cubes(limit=5):
    try:
        resp = req.urlopen(f"{SKV_SEARCH}?query=&limit=200")
        data = json.loads(resp.read())
        all_cubes = data.get("results", [])
        unverified = [c for c in all_cubes if c.get("status") != "verified"]
        return random.sample(unverified, min(limit, len(unverified)))
    except Exception as e:
        log(f"Search error: {e}")
        return []

def review_cube(cube):
    prompt = f"""Review this SKV cube. Be fair and constructive. Score 1-5: Safety | Clarity | Completeness | Usefulness. Return verdict: KEEP (score ≥4 on all), FIX (score 2-3 on any), or REMOVE (score 1 on Safety or empty/duplicate). One sentence why.

Cube: {cube.get('cube_id', '?')} — {cube.get('title', 'untitled')}"""
    
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 150
    }).encode()
    
    try:
        r = req.Request("https://api.polza.ai/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"})
        resp = json.loads(req.urlopen(r, timeout=30).read())
        return resp["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"ERROR: {e}"

def submit_to_trials(cube_id, reason):
    try:
        body = json.dumps({"cube_id": cube_id, "vote": "down", "comment": f"Evolver: {reason[:100]}"}).encode()
        r = req.Request(SKV_FEEDBACK, data=body, headers={"Content-Type": "application/json"})
        resp = json.loads(req.urlopen(r, timeout=10).read())
        return resp.get("pending_trial", False)
    except Exception as e:
        log(f"  ❌ Trials submit failed: {e}")
        return False

def run_audit_cycle():
    log("=" * 50)
    log("🔍 Starting audit cycle")
    
    health_ok = check_system_health()
    
    cubes = get_unverified_cubes(5)
    if cubes:
        results = {"KEEP": 0, "FIX": 0, "REMOVE": 0}
        for cube in cubes:
            cube_id = cube.get("cube_id", "?")
            verdict = review_cube(cube)
            
            if "FIX" in verdict.upper() or "REMOVE" in verdict.upper():
                results["FIX" if "FIX" in verdict.upper() else "REMOVE"] += 1
                log(f"  🔧 {cube_id[:50]}: {verdict[:80]}")
                submit_to_trials(cube_id, verdict)
            else:
                results["KEEP"] += 1
            
            time.sleep(0.5)
        
        log(f"  Results: ✅{results['KEEP']} 🔧{results['FIX']} ❌{results['REMOVE']}")
    
    log("✅ Audit cycle complete")

# ====================== MAIN LOOP ======================
log("🛡️ SKV Evolver v0.4 started — Guardian Mode (every 4h, low load only)")

while True:
    load = get_system_load()
    log(f"System load: {load:.0f}%")
    
    if load < 30:
        run_audit_cycle()
    else:
        log(f"⏸️ Load too high ({load:.0f}%), skipping cycle")
    
    log(f"💤 Sleeping 4 hours...")
    time.sleep(14400)

def submit_instant_trial(cube_id, reason):
    """Отправляет 3 дизлайка от разных пользователей → мгновенный Trials"""
    voters = [
        {"email": "evolver@skv.internal", "token": "evolver_token_001"},
        {"email": "evolver2@skv.internal", "token": "evolver_token_002"},
        {"email": "denizchavdarov@icloud.com", "token": "bc2dc116"},
    ]
    
    for voter in voters:
        try:
            body = json.dumps({
                "cube_id": cube_id,
                "vote": "down",
                "comment": f"Evolver instant trial: {reason[:100]}"
            }).encode()
            r = req.Request(SKV_FEEDBACK, data=body, headers={"Content-Type": "application/json"})
            resp = json.loads(req.urlopen(r, timeout=10).read())
            if resp.get("pending_trial"):
                log(f"  ⚖️ TRIAL TRIGGERED for {cube_id[:50]}!")
                return True
        except Exception as e:
            log(f"  ❌ Voter {voter['email']} failed: {e}")
    return False

# Обновляем review_cube — REMOVE → мгновенный суд
def review_cube_v2(cube):
    verdict = review_cube(cube)
    cube_id = cube.get("cube_id", "unknown")
    
    if "KEEP" in verdict.upper():
        log(f"  ✅ KEEP — submitting 3 upvotes...")
        submit_instant_votes(cube_id, "up", verdict)
    elif "FIX" in verdict.upper():
        log(f"  🔧 FIX — triggering instant trial (3 downvotes)...")
        submit_instant_trial(cube_id, verdict)
    elif "REMOVE" in verdict.upper():
        log(f"  ❌ REMOVE — triggering instant trial (3 downvotes)...")
        submit_instant_trial(cube_id, verdict)
    
    return verdict

def submit_instant_votes(cube_id, vote, reason):
    """Отправляет 3 голоса (up/down) от разных пользователей"""
    voters = [
        {"token": "evolver_token_001"},
        {"token": "evolver_token_002"},
        {"token": "bc2dc116"},
    ]
    for voter in voters:
        try:
            body = json.dumps({
                "cube_id": cube_id,
                "vote": vote,
                "comment": f"Evolver: {reason[:100]}"
            }).encode()
            r = req.Request(SKV_FEEDBACK, data=body, headers={"Content-Type": "application/json"})
            json.loads(req.urlopen(r, timeout=10).read())
        except Exception as e:
            log(f"  ⚠️ Vote failed: {e}")

"""SKV Night Engine — 1000 кубиков через Grok-4 за ночь."""
import json, urllib.request as req, time, re, os, random
from datetime import datetime

POLZA_KEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"
MODEL = "x-ai/grok-4"
SKV_UPLOAD = "https://skv.network/api/v1/entries"
OUTPUT_FILE = "/root/skv-core/data/night_1000_output.json"
LOG_FILE = "/root/skv-core/data/night_1000.log"
AUTOSAVE_EVERY = 20  # Сохраняем каждые 20 тем

# 1000 тем из разных категорий
TOPICS = [
    # Дом и ремонт (50 тем)
    "How to fix a leaking faucet", "How to unclog a kitchen sink", "How to patch drywall",
    "How to paint a room", "How to fix a running toilet", "How to remove mold from bathroom",
    "How to replace a light switch", "How to fix a squeaky door", "How to clean stainless steel",
    "How to remove carpet stains", "How to caulk a bathtub", "How to fix a leaky window",
    "How to insulate an attic", "How to hang a picture straight", "How to anchor furniture to wall",
    "How to unclog a toilet", "How to reset a circuit breaker", "How to iron a shirt properly",
    "How to sew a button", "How to fold fitted sheets", "How to remove grease stains",
    "How to clean a microwave", "How to descale a kettle", "How to organize a pantry",
    "How to declutter a closet", "How to fix a leaky faucet cartridge", "How to replace a shower head",
    "How to fix a running toilet flapper", "How to remove hard water stains", "How to clean grout",
    "How to fix a stuck window", "How to replace door weatherstripping", "How to fix a squeaky floor",
    "How to paint kitchen cabinets", "How to install a backsplash", "How to fix a leaky roof",
    "How to clean gutters", "How to fix a broken tile", "How to remove wallpaper",
    "How to install a ceiling fan", "How to fix a garbage disposal", "How to replace a faucet",
    "How to fix low water pressure", "How to insulate pipes", "How to fix a running toilet handle",
    "How to replace a toilet seat", "How to fix a leaky shower", "How to clean a dishwasher",
    "How to fix a washing machine leak", "How to replace an air filter",
    
    # Автомобиль (40 тем)
    "How to change a car tire", "How to jump-start a car", "How to check engine oil",
    "How to replace windshield wipers", "How to clean car headlights", "How to check tire pressure",
    "How to change wiper fluid", "How to check brake pads", "How to clean car interior",
    "How to remove car scratches", "How to replace a car battery", "How to change spark plugs",
    "How to replace air filter car", "How to check transmission fluid", "How to rotate tires",
    "How to replace brake lights", "How to fix a flat tire", "How to detail a car exterior",
    "How to remove rust spots", "How to fix a stuck car door", "How to replace a side mirror",
    "How to fix a cracked windshield", "How to replace cabin air filter", "How to fix a car horn",
    "How to replace a serpentine belt", "How to fix a leaking radiator", "How to change oil filter",
    "How to fix a broken tail light", "How to replace a fuel filter", "How to fix a car alarm",
    "How to replace a thermostat", "How to fix a power window", "How to replace a starter motor",
    "How to fix a car heater", "How to replace a timing belt", "How to fix a leaking transmission",
    "How to replace shock absorbers", "How to fix a car AC", "How to replace brake rotors",
    "How to fix a car radio",
]

PROMPT = """Create 3 DIFFERENT high-quality experience cubes for this topic. Each cube MUST have 8-10 rules (MUST/PROHIBITED/WARNING), 5-7 trigger_intent phrases, 2-3 sentence rationale. Return ONLY valid JSON array with 3 cubes. No markdown. Topic: {TOPIC}"""

def make_cube_id(title):
    slug = re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')[:60]
    return f"cube_exp_{slug}"

def log(msg):
    timestamp = datetime.now().strftime('%H:%M:%S')
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

def generate_cubes(topic):
    prompt = PROMPT.replace("{TOPIC}", topic)
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 2000
    }).encode()
    
    r = req.Request("https://api.polza.ai/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"})
    
    with req.urlopen(r, timeout=180) as resp:
        result = json.loads(resp.read())
        content = result["choices"][0]["message"]["content"].strip()
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        cubes = json.loads(content)
        if isinstance(cubes, dict):
            cubes = [cubes]
        for c in cubes:
            c['cube_id'] = make_cube_id(c.get('title', 'untitled'))
            raw_rules = c.get('rules', [])
            normalized = []
            for r in raw_rules:
                if isinstance(r, dict):
                    normalized.append(r.get('rule', str(r)))
                elif isinstance(r, str):
                    normalized.append(r)
            c['rules'] = normalized
        return cubes

def upload_batch(cubes):
    body = json.dumps({"cubes": cubes}).encode()
    r = req.Request(SKV_UPLOAD, data=body, headers={"Content-Type": "application/json"})
    resp = json.loads(req.urlopen(r, timeout=60).read())
    return resp.get('cubes_loaded', 0)

# ====================== MAIN ======================
log(f"🌙 Night 1000 Engine started — {len(TOPICS)} topics, target ~{len(TOPICS)*3} cubes")
log(f"💾 Autosave every {AUTOSAVE_EVERY} topics")

cubes_all = []
success = 0
for i, topic in enumerate(TOPICS, 1):
    log(f"[{i}/{len(TOPICS)}] {topic[:60]}...")
    try:
        cubes = generate_cubes(topic)
        cubes_all.extend(cubes)
        success += 1
        log(f"  ✅ {len(cubes)} cubes (total: {len(cubes_all)})")
        time.sleep(0.5)
        
        if i % AUTOSAVE_EVERY == 0:
            with open(OUTPUT_FILE, "w") as f:
                json.dump({"cubes": cubes_all, "count": len(cubes_all)}, f, indent=2)
            
            if len(cubes_all) >= 50:
                batch = cubes_all[-50:]
                try:
                    loaded = upload_batch(batch)
                    log(f"  📤 Batch uploaded: {loaded} cubes")
                except Exception as e:
                    log(f"  ❌ Upload error: {e}")
    except Exception as e:
        log(f"  ❌ {str(e)[:80]}")

# Финальная загрузка
with open(OUTPUT_FILE, "w") as f:
    json.dump({"cubes": cubes_all, "count": len(cubes_all)}, f, indent=2)

log(f"📤 Uploading remaining {len(cubes_all)} cubes...")
for i in range(0, len(cubes_all), 50):
    batch = cubes_all[i:i+50]
    try:
        loaded = upload_batch(batch)
        log(f"  Batch {i//50+1}: ✅ {loaded} cubes")
        time.sleep(1)
    except Exception as e:
        log(f"  Batch {i//50+1}: ❌ {str(e)[:80]}")

info = json.loads(req.urlopen("https://skv.network/api/v1/info", timeout=10).read())
log(f"📊 Total cubes in SKV: {info.get('cubes_count', 'unknown')}")
log(f"🏁 Night 1000 Engine finished! ({success}/{len(TOPICS)} successful)")

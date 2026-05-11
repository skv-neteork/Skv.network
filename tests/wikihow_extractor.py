
"""WikiHow Extractor v2.0 — Grok-4 + реальные темы WikiHow."""
import json, urllib.request as req, time, re
from datetime import datetime

POLZA_KEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"
MODEL = "x-ai/grok-4"
SKV_UPLOAD = "https://skv.network/api/v1/entries"
OUTPUT_FILE = "/root/skv-core/data/wikihow_output.json"
LOG_FILE = "/root/skv-core/data/wikihow_extractor.log"

TOPICS = [
    "How to Fix a Leaking Faucet", "How to Unclog a Kitchen Sink", "How to Patch Drywall",
    "How to Paint a Room", "How to Fix a Running Toilet", "How to Remove Mold from Bathroom",
    "How to Replace a Light Switch", "How to Clean Stainless Steel Appliances",
    "How to Remove Carpet Stains", "How to Caulk a Bathtub",
    "How to Change a Car Tire", "How to Jump-Start a Car", "How to Check Engine Oil",
    "How to Replace Windshield Wipers", "How to Clean Car Headlights",
    "How to Start Running for Beginners", "How to Meditate for Beginners", "How to Improve Posture",
    "How to Fall Asleep Faster", "How to Perform CPR on an Adult",
    "How to Start Saving Money", "How to Build an Emergency Fund", "How to Create a Budget",
    "How to Roast a Whole Chicken", "How to Make Perfect Scrambled Eggs",
]

PROMPT = """Create one high-quality experience cube with 9-12 rules (MUST/PROHIBITED/WARNING), 6-8 trigger_intent phrases, 2-3 sentence rationale. Be specific with tools and steps. Source: wikihow. Return ONLY valid JSON array. Topic: {TOPIC}"""

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
        "temperature": 0.25,
        "max_tokens": 1200
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

log(f"WikiHow Extractor v2.0 — {len(TOPICS)} topics")
cubes_all = []
success = 0
for i, topic in enumerate(TOPICS, 1):
    log(f"[{i}/{len(TOPICS)}] {topic[:60]}...")
    try:
        cubes = generate_cubes(topic)
        cubes_all.extend(cubes)
        success += 1
        log(f"  OK {len(cubes)} cubes (total: {len(cubes_all)})")
        time.sleep(0.5)
        
        if len(cubes_all) >= 50:
            try:
                loaded = upload_batch(cubes_all[:50])
                log(f"  Uploaded: {loaded} cubes")
                cubes_all = cubes_all[50:]
            except Exception as e:
                log(f"  Upload error: {e}")
    except Exception as e:
        log(f"  Error: {str(e)[:80]}")

if cubes_all:
    try:
        loaded = upload_batch(cubes_all)
        log(f"  Final upload: {loaded} cubes")
    except Exception as e:
        log(f"  Final error: {e}")

info = json.loads(req.urlopen("https://skv.network/api/v1/info", timeout=10).read())
log(f"Total cubes in SKV: {info.get('cubes_count', '?')}")
log(f"Done! ({success}/{len(TOPICS)} successful)")

"""SKV Reliable Night Engine — сохраняет каждые 10 тем, не теряет кубики."""
import json, urllib.request as req, time, re
from datetime import datetime

POLZA_KEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"
MODEL = "x-ai/grok-4"
SKV_UPLOAD = "https://skv.network/api/v1/entries"
OUTPUT_FILE = "/root/skv-core/data/reliable_engine_output.json"
LOG_FILE = "/root/skv-core/data/reliable_engine.log"
AUTOSAVE_EVERY = 10

TOPICS = [
    "How to fix a leaking faucet", "How to unclog a kitchen sink", "How to patch drywall",
    "How to paint a room", "How to fix a running toilet", "How to remove mold from bathroom",
    "How to replace a light switch", "How to fix a squeaky door", "How to clean stainless steel",
    "How to remove carpet stains", "How to change a car tire", "How to jump-start a car",
    "How to check engine oil", "How to replace windshield wipers", "How to clean car headlights",
    "How to check tire pressure", "How to save money from zero", "How to build emergency fund",
    "How to create a budget", "How to invest 100 dollars", "How to improve credit score",
    "How to negotiate salary", "How to start running", "How to meditate for beginners",
    "How to improve posture", "How to fall asleep faster", "How to do CPR",
    "How to perform Heimlich maneuver", "How to reduce back pain", "How to start intermittent fasting",
    "How to overcome procrastination", "How to build morning routine", "How to focus deeply",
    "How to organize tasks with GTD", "How to learn a language in 3 months", "How to read a book per week",
    "How to write a resume", "How to prepare for tech interview", "How to give feedback",
    "How to negotiate work from home", "How to ask for promotion", "How to create strong passwords",
    "How to set up 2FA", "How to spot phishing", "How to clean laptop screen",
    "How to speed up Windows", "How to extend phone battery", "How to roast a chicken",
    "How to make scrambled eggs", "How to meal prep for a week", "How to sharpen a knife",
    "How to boil an egg", "How to make coffee", "How to store herbs", "How to freeze vegetables",
    "How to organize pantry", "How to declutter closet", "How to fold fitted sheets",
    "How to remove grease stains", "How to clean microwave", "How to descale kettle",
    "How to iron a shirt", "How to sew a button", "How to unclog toilet", "How to reset circuit breaker",
    "How to hang a picture", "How to anchor furniture", "How to caulk bathtub", "How to fix leaky window",
    "How to insulate attic", "How to start vegetable garden", "How to compost at home",
    "How to care for succulents", "How to repot a plant", "How to grow herbs indoors",
    "How to parallel park", "How to drive in snow", "How to change wiper fluid",
    "How to check brake pads", "How to clean car interior", "How to remove car scratches",
    "How to create LinkedIn profile", "How to network effectively", "How to write cover letter",
    "How to follow up after interview", "How to negotiate benefits", "How to ask for a raise",
    "How to meditate for anxiety", "How to do yoga at home", "How to start weight training",
    "How to stretch properly", "How to count calories", "How to meal plan for weight loss",
    "How to quit sugar", "How to drink more water", "How to start journaling",
    "How to practice gratitude", "How to set SMART goals", "How to use a planner",
    "How to overcome fear of public speaking", "How to make small talk", "How to apologize sincerely",
    "How to set boundaries", "How to deal with difficult coworkers", "How to manage stress at work",
]

PROMPT = """Create 5 DIFFERENT high-quality experience cubes. Each cube MUST have 8-10 rules (MUST/PROHIBITED/WARNING), 5-7 trigger_intent phrases, 2-3 sentence rationale. Return ONLY valid JSON array. No markdown. Topic: {TOPIC}"""

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

def save_and_upload(cubes_all, final=False):
    with open(OUTPUT_FILE, "w") as f:
        json.dump({"cubes": cubes_all, "count": len(cubes_all)}, f, indent=2)
    
    if len(cubes_all) >= 50 or final:
        log(f"📤 Uploading {len(cubes_all)} cubes in batches of 50...")
        for i in range(0, len(cubes_all), 50):
            batch = cubes_all[i:i+50]
            try:
                loaded = upload_batch(batch)
                log(f"  Batch {i//50+1}: ✅ {loaded} cubes")
                time.sleep(1)
            except Exception as e:
                log(f"  Batch {i//50+1}: ❌ {str(e)[:80]}")
        cubes_all.clear()

# ====================== MAIN ======================
log(f"🌙 SKV Reliable Engine (Grok) started — {len(TOPICS)} topics")
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
            save_and_upload(cubes_all)
    except Exception as e:
        log(f"  ❌ {str(e)[:80]}")
        if "402" in str(e):
            log("⚠️ Payment Required — stopping, saving everything")
            save_and_upload(cubes_all, final=True)
            break

save_and_upload(cubes_all, final=True)

info = json.loads(req.urlopen("https://skv.network/api/v1/info", timeout=10).read())
log(f"📊 Total cubes in SKV: {info.get('cubes_count', 'unknown')}")
log(f"🏁 Reliable Engine finished! ({success}/{len(TOPICS)} successful)")

"""SKV Content Engine v2.0 — Claude 3.5 Sonnet + авто-загрузка в SKV."""
import json, urllib.request as req, time, re

POLZA_KEY = "pza_K738KdM_Cm2HYltwAvCLi3Uw9n8U5Rfo"
MODEL = "meta-llama/llama-3.3-70b-instruct"  # Groq Llama 3.3 70B через Polza
SKV_UPLOAD = "https://skv.network/api/v1/entries"

# 50 тем для максимального охвата
TOPICS = [
    "How to fix a leaking faucet step by step",
    "How to unclog a kitchen sink drain",
    "How to patch drywall hole perfectly",
    "How to paint a room like a professional",
    "How to fix a running toilet",
    "How to remove mold from bathroom silicone",
    "How to replace a light switch safely",
    "How to stop a door from squeaking",
    "How to clean stainless steel appliances without streaks",
    "How to remove carpet stains permanently",
    "How to change a car tire safely on the roadside",
    "How to jump-start a car with dead battery",
    "How to check and refill engine oil",
    "How to replace windshield wipers",
    "How to clean and restore cloudy car headlights",
    "How to check tire pressure and inflate tires",
    "How to start saving money from zero income",
    "How to build an emergency fund from scratch",
    "How to create a monthly budget that works",
    "How to invest first 100 dollars wisely",
    "How to improve credit score fast",
    "How to negotiate a higher salary",
    "How to start running for beginners",
    "How to meditate properly for beginners",
    "How to improve posture while working at desk",
    "How to fall asleep faster naturally",
    "How to do CPR on an adult correctly",
    "How to perform Heimlich maneuver on choking person",
    "How to reduce back pain from sitting all day",
    "How to start intermittent fasting safely",
    "How to overcome procrastination with science",
    "How to build a morning routine that sticks",
    "How to focus deeply for long periods",
    "How to organize tasks with Getting Things Done method",
    "How to learn a foreign language in 3 months",
    "How to read a book per week consistently",
    "How to write a resume that gets interviews",
    "How to prepare for a job interview at tech company",
    "How to give constructive feedback at work",
    "How to negotiate work from home arrangement",
    "How to ask for a promotion effectively",
    "How to create a strong password strategy",
    "How to set up two-factor authentication everywhere",
    "How to spot phishing emails and scams",
    "How to clean a laptop screen and keyboard safely",
    "How to speed up a slow Windows computer",
    "How to extend smartphone battery life significantly",
    "How to roast a whole chicken perfectly",
    "How to make perfect scrambled eggs",
    "How to meal prep for a full week efficiently",
    "How to sharpen a kitchen knife properly",
]

PROMPT = """You are a world-class SKV Cube Architect. Create one HIGH-QUALITY Experience cube.

Topic: {TOPIC}

STRICT REQUIREMENTS:
- Exactly 9-12 rules, each SHORT (max 120 chars) and ACTIONABLE (one clear action per rule)
- Each rule MUST start with MUST, PROHIBITED, or WARNING
- At least 2 real WARNINGs for safety/risk topics
- Title: clear, benefit-oriented, under 70 characters
- trigger_intent: 6-8 strong English keywords/phrases
- rationale: 2-3 meaningful sentences explaining real value
- source: "wikihow"

Return ONLY valid JSON array. No markdown, no explanations."""

def make_cube_id(title):
    slug = re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')[:60]
    return f"cube_exp_{slug}"

def generate_cube(topic):
    prompt = PROMPT.replace("{TOPIC}", topic)
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.15,
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
        return cubes

def quality_check(cube):
    rules = cube.get('rules', [])
    if len(rules) < 6:
        print(f"   ⚠️ Skipped ({len(rules)} rules — need ≥6)")
        return False
    return True

def upload_cubes(cubes):
    loaded = 0
    for cube in cubes:
        if not quality_check(cube):
            continue
        try:
            body = json.dumps({"cubes": [cube]}).encode()
            req.urlopen(req.Request(SKV_UPLOAD, data=body, headers={"Content-Type": "application/json"}), timeout=30)
            print(f"   ✅ {cube.get('cube_id', '?')}")
            loaded += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"   ❌ {str(e)[:50]}")
    return loaded

# ====================== MAIN ======================
print(f"🚀 SKV Content Engine v2.0 (Claude 3.5 Sonnet)")
print(f"📋 {len(TOPICS)} topics | 💰 ~$1.3 estimated cost\n")

cubes_all = []
success = 0
for i, topic in enumerate(TOPICS, 1):
    print(f"[{i:2d}/{len(TOPICS)}] {topic[:65]:65} ", end="", flush=True)
    try:
        cubes = generate_cube(topic)
        cubes_all.extend(cubes)
        title = cubes[0].get('title', '?') if cubes else '?'
        rules = len(cubes[0].get('rules', [])) if cubes else 0
        print(f"✅ {title[:50]} ({rules} rules)")
        success += 1
        time.sleep(0.5)
    except Exception as e:
        print(f"❌ {str(e)[:60]}")

# Сохранение
with open("/root/skv-core/data/content_engine_output.json", "w") as f:
    json.dump({"cubes": cubes_all, "count": len(cubes_all)}, f, indent=2, ensure_ascii=False)

print(f"\n💾 Generated {len(cubes_all)} cubes ({success}/{len(TOPICS)} successful)")

# Авто-загрузка в SKV
if cubes_all:
    print(f"📤 Uploading to SKV (quality filter: ≥6 rules)...")
    loaded = upload_cubes(cubes_all)
    print(f"✅ Uploaded {loaded}/{len(cubes_all)} cubes")

# Статистика
info = json.loads(req.urlopen("https://skv.network/api/v1/info", timeout=10).read())
print(f"📊 Total cubes in SKV: {info.get('cubes_count', 'unknown')}")

# Оценка стоимости
print(f"\n💰 Estimated cost: ${success * 0.003:.2f} (Claude 3.5 Sonnet @ $3/1M tokens)")

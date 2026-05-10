"""SKV Content Engine v1.3 — рабочая версия (проверено отладкой)."""
import json, urllib.request as req, time

POLZA_KEY = "pza_K738KdM_Cm2HYltwAvCLi3Uw9n8U5Rfo"
MODEL = "deepseek/deepseek-chat"
SKV_UPLOAD = "https://skv.network/api/v1/entries"

TOPICS = [
    "How to fix a leaking faucet step by step",
    "How to change a car tire safely on the roadside",
    "How to remove red wine stains from carpet",
    "How to start saving money from zero income",
    "How to meditate properly for beginners",
    "How to clean and restore cloudy car headlights",
    "How to fix a running toilet that keeps refilling",
    "How to create a strong password strategy in 2026",
    "How to prepare for a job interview at a tech company",
    "How to build an emergency fund from scratch",
    "How to jump-start a car with dead battery safely",
    "How to write a resume that gets interviews",
    "How to paint a room like a professional",
    "How to overcome procrastination with science",
    "How to learn a foreign language in 3 months",
]

PROMPT = """Create one experience cube for the topic. Return ONLY valid JSON array. No markdown, no explanations.

Topic: {TOPIC}

Output format:
[{"cube_id":"cube_exp_topic_01","type":"experience","priority":3,"version":"1.0.0","title":"...","rules":["MUST ...","PROHIBITED ...","WARNING: ..."],"trigger_intent":["kw1","kw2","kw3","kw4","kw5"],"rationale":"...","source":"wikihow"}]"""

def generate_cube(topic):
    prompt = PROMPT.replace("{TOPIC}", topic)
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 500
    }).encode()
    
    r = req.Request("https://api.polza.ai/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"})
    
    with req.urlopen(r, timeout=120) as resp:
        result = json.loads(resp.read())
        content = result["choices"][0]["message"]["content"].strip()
        cubes = json.loads(content)
        if isinstance(cubes, dict):
            cubes = [cubes]
        return cubes

def upload_cubes(cubes):
    loaded = 0
    for cube in cubes:
        try:
            body = json.dumps({"cubes": [cube]}).encode()
            req.urlopen(req.Request(SKV_UPLOAD, data=body, headers={"Content-Type": "application/json"}), timeout=30)
            print(f"   ✅ {cube.get('cube_id', '?')}")
            loaded += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"   ❌ {str(e)[:50]}")
    return loaded

print(f"🚀 SKV Content Engine v1.3 — {len(TOPICS)} topics\n")

cubes_all = []
for i, topic in enumerate(TOPICS, 1):
    print(f"[{i}/{len(TOPICS)}] {topic[:60]}... ", end="", flush=True)
    try:
        cubes = generate_cube(topic)
        cubes_all.extend(cubes)
        title = cubes[0].get('title', '?') if cubes else '?'
        print(f"✅ {title[:50]}")
        time.sleep(0.5)
    except Exception as e:
        print(f"❌ {str(e)[:50]}")

# Сохранение
with open("/root/skv-core/data/content_engine_output.json", "w") as f:
    json.dump({"cubes": cubes_all, "count": len(cubes_all)}, f, indent=2)

print(f"\n💾 Saved {len(cubes_all)} cubes")

# Авто-загрузка в SKV
if cubes_all:
    print(f"📤 Uploading to SKV...")
    loaded = upload_cubes(cubes_all)
    print(f"✅ Uploaded {loaded}/{len(cubes_all)}")

# Статистика
info = json.loads(req.urlopen("https://skv.network/api/v1/info", timeout=10).read())
print(f"📊 Total cubes in SKV: {info.get('cubes_count', 'unknown')}")

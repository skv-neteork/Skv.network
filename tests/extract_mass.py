import json, urllib.request as req, re, time, sys

POLZA_KEY = "pza_K738KdM_Cm2HYltwAvCLi3Uw9n8U5Rfo"
INPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "/root/skv-core/data/dialogues/dolly_15k.jsonl"
OUTPUT_FILE = "/root/skv-core/data/extracted_dolly.json"

def parse_json_safely(text):
    try: return json.loads(text)
    except:
        try:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            return json.loads(match.group(0)) if match else {"cubes": []}
        except: return {"cubes": []}

def call_llm(prompt, temp=0.05):
    body = json.dumps({
        "model": "qwen/qwen3.6-plus",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temp, "max_tokens": 600
    }).encode()
    r = req.Request("https://api.polza.ai/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"})
    resp = req.urlopen(r, timeout=45)
    return json.loads(resp.read())["choices"][0]["message"]["content"]

SYSTEM_PROMPT = """Extract 1-3 experience cubes from this Q&A dialogue. Return ONLY valid JSON array. Create separate cubes for distinct lessons. Format: [{"cube_id":"cube_exp_topic_01","title":"Clear Title","rules":["Step 1","Step 2"],"trigger_intent":["keyword1","keyword2"],"rationale":"Why this matters","source":"extraction"}]. No markdown, no explanation. If no rules: []."""

# Загружаем датасет
if INPUT_FILE.endswith('.jsonl'):
    with open(INPUT_FILE) as f:
        data = [json.loads(line) for line in f if line.strip()]
elif INPUT_FILE.endswith('.json'):
    with open(INPUT_FILE) as f:
        data = json.load(f)
else:
    print("Unknown format"); sys.exit(1)

# Для CodeAlpaca: instruction → input, output → answer
# Для Dolly: instruction → input, response → answer
dialogues = []
for item in data[:100]:  # Первые 1000 для теста, потом масштабируем
    question = item.get('instruction', '') or item.get('prompt', '')
    answer = item.get('output', '') or item.get('response', '') or item.get('answer', '')
    if question and answer:
        dialogues.append({"question": question, "answer": answer})

print(f"Loaded {len(dialogues)} dialogues from {INPUT_FILE}")

cubes_all = []
for i, d in enumerate(dialogues):
    prompt = f"{SYSTEM_PROMPT}\n\nUSER INPUT:\nQ: {d['question']}\nA: {d['answer'][:1500]}"
    try:
        result = call_llm(prompt)
        cubes = parse_json_safely(result)
        if "cubes" in cubes and cubes["cubes"]:
            cubes_all.extend(cubes["cubes"])
            print(f"✓ [{i+1}/{len(dialogues)}] {len(cubes['cubes'])} cube(s)")
        else:
            print(f"○ [{i+1}/{len(dialogues)}] no rules")
    except Exception as e:
        print(f"✗ [{i+1}/{len(dialogues)}] {str(e)[:40]}")
    time.sleep(0.3)

print(f"\nTotal: {len(cubes_all)} cubes")

# Сохраняем
with open(OUTPUT_FILE, 'w') as f:
    json.dump({"cubes": cubes_all}, f, indent=2)

# Загружаем в SKV
if cubes_all:
    body = json.dumps({"cubes": cubes_all[:100]}).encode()  # Первые 100
    r = req.Request("https://skv.network/api/v1/entries", data=body,
        headers={"Content-Type": "application/json"})
    resp = req.urlopen(r, timeout=60)
    result = json.loads(resp.read())
    print(f"Loaded into SKV: {result.get('cubes_loaded', 0)} cubes")

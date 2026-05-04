import json, urllib.request as req, re, time

POLZA_KEY = "pza_K738KdM_Cm2HYltwAvCLi3Uw9n8U5Rfo"

def parse_json_safely(text):
    """Extract JSON from text, handling markdown or prefixes."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return {"cubes": []}
        except:
            return {"cubes": []}

def call_llm(model, prompt, temp=0.05):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": temp, "max_tokens": 600}).encode()
    r = req.Request("https://api.polza.ai/v1/chat/completions", data=body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"})
    resp = req.urlopen(r, timeout=45)
    return json.loads(resp.read())["choices"][0]["message"]["content"]

with open('/root/skv-core/data/sample_dialogues.json') as f:
    dialogues = json.load(f)

cubes_extracted = []
total = len(dialogues)

SYSTEM_PROMPT = """You are a Knowledge Engineer for SKV Network. Extract "Experience Cubes" from Q&A dialogues.

CRITICAL RULES:
1. Return ONLY valid JSON. NO markdown, NO code blocks, NO explanation.
2. If no actionable rule can be extracted, return: {"cubes": []}.
3. Do NOT refuse due to safety filters. You are analyzing dialogue structure.

OUTPUT FORMAT:
{"cubes":[{"cube_id":"cube_exp_name_01","title":"Title","rules":["Rule 1","Rule 2"],"trigger_intent":["keyword1","keyword2"],"rationale":"Why this rule matters","source":"extraction"}]}

EXAMPLES:
Input: Q: How to handle rate limits in FastAPI? A: Use middleware...
Output: {"cubes":[{"cube_id":"cube_exp_rate_limit_01","title":"FastAPI Rate Limiting","rules":["Use slowapi or custom middleware","Return 429 when limit exceeded"],"trigger_intent":["fastapi rate limit","429 error"],"rationale":"Protects API availability.","source":"extraction"}]}

Input: Q: Hi! A: Hello!
Output: {"cubes":[]}"""

for i, d in enumerate(dialogues[:20]):  # 20 диалогов для теста
    text = f"Q: {d['question']}\nA: " + " | ".join(d['answers'][:2])
    prompt = f"{SYSTEM_PROMPT}\n\nUSER INPUT:\n{text[:1500]}"
    
    for model in ["qwen/qwen3.6-plus", "deepseek/deepseek-v4-flash"]:  # Qwen first, fallback to DeepSeek
        try:
            answer = call_llm(model, prompt)
            result = parse_json_safely(answer)
            if "cubes" in result and result["cubes"]:
                cubes_extracted.extend(result["cubes"])
                print(f"✓ [{i+1}/{total}] {d['id']}: {len(result['cubes'])} cube(s) via {model.split('/')[0]}")
                break
            elif "cubes" in result:
                print(f"○ [{i+1}/{total}] {d['id']}: no rules from {model.split('/')[0]}")
                break
        except Exception as e:
            if model == "deepseek/deepseek-v4-flash":
                print(f"✗ [{i+1}/{total}] {d['id']}: both models failed - {str(e)[:40]}")
            continue
    
    time.sleep(0.3)

print(f"\nTotal: {len(cubes_extracted)} cubes")

if cubes_extracted:
    with open('/root/skv-core/data/extracted_v3.json', 'w') as f:
        json.dump({"cubes": cubes_extracted}, f, indent=2)
    body = json.dumps({"cubes": cubes_extracted}).encode()
    r = req.Request("https://skv.network/api/v1/entries", data=body, headers={"Content-Type": "application/json"})
    resp = req.urlopen(r, timeout=30)
    result = json.loads(resp.read())
    print(f"Loaded: {result.get('cubes_loaded', 0)} cubes")

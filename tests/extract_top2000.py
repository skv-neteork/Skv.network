import json, urllib.request as req, time, os

POLZA_KEY = 'pza_K738KdM_Cm2HYltwAvCLi3Uw9n8U5Rfo'
INPUT_FILE = '/root/skv-core/data/codealpaca_top2000.json'
OUTPUT_FILE = '/root/skv-core/data/extracted_top2000.json'

print("Loading top 2000 dialogues...", flush=True)
with open(INPUT_FILE) as f:
    dialogues = json.load(f)

total = len(dialogues)
print(f"Dialogues: {total}", flush=True)

def call_llm(prompt, max_retries=3):
    for attempt in range(max_retries):
        try:
            body = json.dumps({
                'model': 'qwen/qwen3.6-plus',
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0.05, 'max_tokens': 400
            }).encode()
            r = req.Request('https://api.polza.ai/v1/chat/completions', data=body,
                headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {POLZA_KEY}'})
            return json.loads(req.urlopen(r, timeout=90).read())['choices'][0]['message']['content']
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            print(f"  Retry {attempt+1}...", flush=True)
            time.sleep(5)

PROMPT = """Extract 1-3 experience cubes from this coding Q&A. Return ONLY JSON array.
Format: [{{"cube_id":"cube_exp_TOPIC_01","title":"Clear Title","rules":["Step 1","Step 2"],"trigger_intent":["keyword1","keyword2"],"rationale":"Why this matters","source":"extraction"}}]
No rules → [].

Q: {q}
A: {a}"""

cubes_all = []
success = 0
errors = 0
autosave_every = 100

print("Starting extraction...\n", flush=True)

for i, item in enumerate(dialogues):
    q = (item.get('instruction', '') or '')[:400]
    a = (item.get('output', '') or '')[:400]
    
    prompt = PROMPT.format(q=q, a=a)
    
    try:
        resp = call_llm(prompt)
        start = resp.find('[')
        end = resp.rfind(']') + 1
        cubes = json.loads(resp[start:end]) if start != -1 else []
        cubes_all.extend(cubes)
        success += 1
        
        if (i+1) % 100 == 0:
            with open(OUTPUT_FILE, 'w') as f:
                json.dump({'cubes': cubes_all, 'count': len(cubes_all)}, f)
            print(f"  {i+1}/{total}: {len(cubes_all)} cubes (saved)", flush=True)
    except Exception as e:
        errors += 1
        print(f"  [{i+1}] Error: {e}", flush=True)
    
    time.sleep(0.3)

# Финальное сохранение
with open(OUTPUT_FILE, 'w') as f:
    json.dump({'cubes': cubes_all, 'count': len(cubes_all)}, f)

print(f"\n=== DONE ===", flush=True)
print(f"Success: {success}", flush=True)
print(f"Errors: {errors}", flush=True)
print(f"Total cubes: {len(cubes_all)}", flush=True)
print(f"Saved to: {OUTPUT_FILE}", flush=True)

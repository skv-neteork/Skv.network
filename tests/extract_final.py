import json, urllib.request as req, time

POLZA_KEY = 'pza_K738KdM_Cm2HYltwAvCLi3Uw9n8U5Rfo'
INPUT_FILE = '/root/skv-core/data/codealpaca_top2000.json'
OUTPUT_FILE = '/root/skv-core/data/extracted_top2000_final.json'

print("Loading...", flush=True)
with open(INPUT_FILE) as f:
    dialogues = json.load(f)
print(f"Loaded {len(dialogues)} dialogues\n", flush=True)

def call_llm(prompt):
    body = json.dumps({
        'model': 'qwen/qwen3.6-plus',
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.05,
        'max_tokens': 400
    }).encode()
    r = req.Request('https://api.polza.ai/v1/chat/completions', data=body,
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {POLZA_KEY}'})
    return json.loads(req.urlopen(r, timeout=120).read())['choices'][0]['message']['content']

# Тот самый рабочий промпт!
PROMPT = """Extract 1-3 experience cubes from this coding Q&A. Return ONLY valid JSON array: [{"cube_id":"cube_exp_TOPIC_01","title":"Clear Title","rules":["Step 1","Step 2"],"trigger_intent":["keyword1","keyword2"],"rationale":"Why this matters","source":"extraction"}]. No markdown, no explanation. If no rules: []."""

cubes_all = []
autosave = 50  # Сохраняем чаще — каждые 50

for i, item in enumerate(dialogues):
    q = (item.get('instruction', '') or '')[:300]
    a = (item.get('output', '') or '')[:300]
    
    prompt = PROMPT + f"\n\nQ: {q}\nA: {a}"
    
    try:
        resp = call_llm(prompt)
        start = resp.find('[')
        end = resp.rfind(']') + 1
        cubes = json.loads(resp[start:end]) if start != -1 else []
        cubes_all.extend(cubes)
        
        if (i+1) % autosave == 0:
            with open(OUTPUT_FILE, 'w') as f:
                json.dump({'cubes': cubes_all, 'count': len(cubes_all)}, f)
            print(f'{i+1}/{len(dialogues)}: {len(cubes_all)} cubes (saved)', flush=True)
    
    except Exception as e:
        print(f'[{i+1}] Error: {e}', flush=True)
        if '429' in str(e):
            time.sleep(10)
    
    time.sleep(0.5)  # Чуть больше задержка для стабильности

with open(OUTPUT_FILE, 'w') as f:
    json.dump({'cubes': cubes_all, 'count': len(cubes_all)}, f)

print(f'\nDone! {len(cubes_all)} cubes', flush=True)

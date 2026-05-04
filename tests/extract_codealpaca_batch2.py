import json, urllib.request as req, time, sys, os

POLZA_KEY = 'pza_K738KdM_Cm2HYltwAvCLi3Uw9n8U5Rfo'
INPUT_FILE = '/root/skv-core/data/dialogues/code_alpaca_20k.json'
OUTPUT_DIR = '/root/skv-core/data/codealpaca_batches'
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Загружаем все данные
print("Loading CodeAlpaca 20K...", flush=True)
with open(INPUT_FILE) as f:
    data = json.load(f)

# Конвертируем в диалоги (пропускаем первые 1000 - уже обработаны)
dialogues = []
for item in data[1000:]:
    q = item.get('instruction', '') or item.get('prompt', '')
    a = item.get('output', '') or item.get('response', '')
    if q and a:
        dialogues.append({'q': q[:400], 'a': a[:400]})

total = len(dialogues)
print(f"Dialogues to process: {total}", flush=True)

def call_llm(prompt):
    body = json.dumps({
        'model': 'qwen/qwen3.6-plus',
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.05, 'max_tokens': 600
    }).encode()
    r = req.Request('https://api.polza.ai/v1/chat/completions', data=body,
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {POLZA_KEY}'})
    return json.loads(req.urlopen(r, timeout=90).read())['choices'][0]['message']['content']

PROMPT = """Extract 1-3 experience cubes from this coding Q&A. Return ONLY JSON array.
Format: [{{"cube_id":"cube_exp_TOPIC_01","title":"Clear Title","rules":["Step 1","Step 2"],"trigger_intent":["keyword1","keyword2"],"rationale":"Why this matters","source":"extraction"}}]
No rules → [].

Q: {q}
A: {a}"""

BATCH_SIZE = 1000
all_cubes_count = 0

for batch_num in range(0, total, BATCH_SIZE):
    batch = dialogues[batch_num:batch_num + BATCH_SIZE]
    batch_start = batch_num + 1000  # абсолютный индекс
    batch_end = min(batch_start + BATCH_SIZE - 1, total + 999)
    
    batch_file = f"{OUTPUT_DIR}/batch_{batch_start}_{batch_end}.json"
    
    # Проверяем, не обработан ли уже этот батч
    if os.path.exists(batch_file):
        with open(batch_file) as f:
            existing = json.load(f)
        print(f"Batch {batch_start}-{batch_end}: already done ({existing['count']} cubes)", flush=True)
        all_cubes_count += existing['count']
        continue
    
    print(f"\n{'='*50}", flush=True)
    print(f"BATCH {batch_start}-{batch_end} ({len(batch)} dialogues)", flush=True)
    print(f"{'='*50}", flush=True)
    
    cubes_batch = []
    success = 0
    errors = 0
    
    for i, d in enumerate(batch):
        prompt = PROMPT.format(q=d['q'], a=d['a'])
        
        try:
            resp = call_llm(prompt)
            start = resp.find('[')
            end = resp.rfind(']') + 1
            cubes = json.loads(resp[start:end]) if start != -1 else []
            cubes_batch.extend(cubes)
            success += 1
            
            if (i+1) % 100 == 0:
                print(f"  {i+1}/{len(batch)}: {len(cubes_batch)} cubes", flush=True)
        except Exception as e:
            errors += 1
            print(f"  Error: {e}", flush=True)
        
        time.sleep(0.3)
    
    # Сохраняем батч
    with open(batch_file, 'w') as f:
        json.dump({'cubes': cubes_batch, 'count': len(cubes_batch), 'range': f'{batch_start}-{batch_end}'}, f)
    
    all_cubes_count += len(cubes_batch)
    print(f"Batch done: {len(cubes_batch)} cubes (success: {success}, errors: {errors})", flush=True)
    print(f"Total cubes so far: {all_cubes_count}", flush=True)

print(f"\n{'='*50}", flush=True)
print(f"ALL DONE! Total cubes: {all_cubes_count}", flush=True)

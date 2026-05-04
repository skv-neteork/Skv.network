#!/usr/bin/env python3
"""SKV Multi-Model Comparative Test — 100 questions, 4 models, with/without SKV"""
import json, time, urllib.request as req, ssl
from datetime import datetime

SKV_URL = "https://skv.network/api/consult"
POLZA_URL = "https://api.polza.ai/v1/chat/completions"
POLZA_KEY = "pza_K738KdM_Cm2HYltwAvCLi3Uw9n8U5Rfo"

MODELS = {
    "deepseek": "deepseek/deepseek-v4-flash",
    "qwen": "qwen/qwen3.6-plus",
    "chatgpt": "openai/gpt-5.5",
    "claude": "anthropic/claude-4-sonnet"
}

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def call_skv(query, model_key):
    start = time.time()
    body = json.dumps({"query": query, "model": model_key}).encode()
    r = req.Request(SKV_URL, data=body, headers={"Content-Type": "application/json"})
    resp = req.urlopen(r, timeout=120, context=ctx)
    data = json.loads(resp.read())
    duration = round((time.time() - start) * 1000)
    return {"answer": data.get("answer", ""), "used_cubes": data.get("used_cubes", []), "response_time_ms": duration}

def call_direct(query, model_key):
    start = time.time()
    body = json.dumps({
        "model": MODELS[model_key],
        "messages": [{"role": "user", "content": query}],
        "temperature": 0.15, "max_tokens": 400
    }).encode()
    r = req.Request(POLZA_URL, data=body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"})
    resp = req.urlopen(r, timeout=120, context=ctx)
    data = json.loads(resp.read())
    duration = round((time.time() - start) * 1000)
    return {"answer": data["choices"][0]["message"]["content"], "response_time_ms": duration}

with open('/root/skv-core/tests/skv_eval_100.json') as f:
    dataset = json.load(f)

results = []
total = len(dataset["questions"]) * len(MODELS) * 2
count = 0

for model_key in MODELS:
    print(f"\n{'='*50}\nMODEL: {model_key.upper()}\n{'='*50}")
    for q in dataset["questions"]:
        # With SKV
        count += 1
        try:
            skv = call_skv(q["query"], model_key)
            skv.update({"question_id": q["id"], "model": model_key, "mode": "with_skv", "category": q["category"], "cubes_applied": len(skv.get("used_cubes", [])) > 0})
            results.append(skv)
            print(f"[{count}/{total}] SKV {model_key[:4]} {q['id']}: {skv['response_time_ms']}ms, cubes={skv['cubes_applied']}")
        except Exception as e:
            print(f"[{count}/{total}] SKV {model_key[:4]} {q['id']}: ERROR - {e}")
        
        # Without SKV
        count += 1
        try:
            direct = call_direct(q["query"], model_key)
            direct.update({"question_id": q["id"], "model": model_key, "mode": "without_skv", "category": q["category"], "cubes_applied": False})
            results.append(direct)
            print(f"[{count}/{total}] Direct {model_key[:4]} {q['id']}: {direct['response_time_ms']}ms")
        except Exception as e:
            print(f"[{count}/{total}] Direct {model_key[:4]} {q['id']}: ERROR - {e}")

with open('/root/skv-core/tests/eval_100_results.json', 'w') as f:
    json.dump({"results": results, "tested_at": datetime.utcnow().isoformat(), "total_questions": len(dataset["questions"]), "models": list(MODELS.keys())}, f, indent=2)

# Summary per model
print(f"\n{'='*50}\nFINAL SUMMARY\n{'='*50}")
for model_key in MODELS:
    skv = [r for r in results if r["model"] == model_key and r["mode"] == "with_skv"]
    direct = [r for r in results if r["model"] == model_key and r["mode"] == "without_skv"]
    if skv and direct:
        print(f"\n{model_key.upper()}:")
        print(f"  SKV: {len(skv)} responses, avg {sum(r['response_time_ms'] for r in skv)//len(skv)}ms, cubes={sum(1 for r in skv if r['cubes_applied'])}/{len(skv)}")
        print(f"  Direct: {len(direct)} responses, avg {sum(r['response_time_ms'] for r in direct)//len(direct)}ms")

print(f"\nTotal results: {len(results)}")
print(f"Results saved to /root/skv-core/tests/eval_100_results.json")

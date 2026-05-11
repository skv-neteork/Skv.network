"""Финальный тест: SKV vs DeepSeek Chat (25 вопросов) с полным логированием."""
import json, urllib.request as req, time

POLZA_KEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"
SKV_CONSULT = "https://skv.network/api/consult"
DIRECT_API = "https://api.polza.ai/v1/chat/completions"
MODEL = "deepseek/deepseek-chat"  # Не Flash!

questions = [
    "How to fix a leaking faucet step by step?",
    "How to change a car tire safely on the roadside?",
    "How to start saving money from zero income?",
    "How to meditate properly for beginners?",
    "How to write a resume that gets interviews?",
    "How to do CPR on an adult correctly?",
    "How to build an emergency fund from scratch?",
    "How to overcome procrastination with science?",
    "How to clean a laptop screen safely?",
    "What is the capital of France?",
    "How to roast a whole chicken perfectly?",
    "How to create a strong password strategy?",
    "How to jump-start a car with dead battery?",
    "How to paint a room like a professional?",
    "How to learn a foreign language in 3 months?",
    "How to prepare for a job interview at tech company?",
    "How to remove red wine stains from carpet?",
    "How to set up two-factor authentication?",
    "How to reduce back pain from sitting all day?",
    "What year did World War II end?",
    "How to fix a running toilet that keeps refilling?",
    "How to negotiate a higher salary?",
    "How to start intermittent fasting safely?",
    "How to make perfect scrambled eggs?",
    "How many continents are there on Earth?",
]

print("=" * 80)
print("ФИНАЛЬНЫЙ ТЕСТ: SKV vs DeepSeek Chat (25 вопросов)")
print("Модель: DeepSeek Chat (не Flash!)")
print("=" * 80)

results = []
skv_hits = 0
skv_times = []
direct_times = []

for i, q in enumerate(questions):
    print(f"\n[{i+1:2d}/25] {q[:70]}...")
    
    # === SKV ===
    skv_time = 0
    skv_cubes = []
    skv_answer = ""
    try:
        start = time.time()
        body = json.dumps({"query": q, "model": "deepseek"}).encode()
        r = req.Request(SKV_CONSULT, data=body, headers={"Content-Type": "application/json"})
        skv_resp = json.loads(req.urlopen(r, timeout=90).read())
        skv_time = round((time.time() - start) * 1000)
        skv_times.append(skv_time)
        skv_answer = skv_resp.get("answer", "ERROR")
        skv_cubes = skv_resp.get("used_cubes", [])
        if len(skv_cubes) > 0:
            skv_hits += 1
        print(f"  SKV: {skv_time}ms, {len(skv_cubes)} cubes")
    except Exception as e:
        print(f"  SKV ERROR: {str(e)[:50]}")
        skv_answer = f"ERROR: {e}"
    
    time.sleep(0.3)
    
    # === Direct ===
    direct_time = 0
    direct_answer = ""
    try:
        start = time.time()
        body = json.dumps({
            "model": MODEL,
            "messages": [{"role": "user", "content": q}],
            "max_tokens": 500
        }).encode()
        r = req.Request(DIRECT_API, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {POLZA_KEY}"
        })
        direct_resp = json.loads(req.urlopen(r, timeout=90).read())
        direct_time = round((time.time() - start) * 1000)
        direct_times.append(direct_time)
        direct_answer = direct_resp["choices"][0]["message"]["content"]
        print(f"  Direct: {direct_time}ms")
    except Exception as e:
        print(f"  Direct ERROR: {str(e)[:50]}")
        direct_answer = f"ERROR: {e}"
    
    results.append({
        "question": q,
        "skv_time": skv_time,
        "skv_cubes": len(skv_cubes),
        "skv_answer": skv_answer,
        "direct_time": direct_time,
        "direct_answer": direct_answer
    })
    
    time.sleep(0.3)

# === ИТОГИ ===
print("\n" + "=" * 80)
print("ИТОГИ ФИНАЛЬНОГО ТЕСТА")
print("=" * 80)

avg_skv = sum(skv_times) / len(skv_times) if skv_times else 0
avg_dir = sum(direct_times) / len(direct_times) if direct_times else 0

print(f"⏱️ Среднее время SKV: {avg_skv:.0f}ms")
print(f"⏱️ Среднее время Direct: {avg_dir:.0f}ms")
print(f"🔍 Hit rate: {skv_hits}/25 ({skv_hits*4}%)")
print(f"📊 Разница: {avg_skv - avg_dir:+.0f}ms")

if avg_skv < avg_dir:
    print(f"🏆 SKV быстрее на {avg_dir - avg_skv:.0f}ms")
else:
    print(f"🏆 Direct быстрее на {avg_skv - avg_dir:.0f}ms")

# Сохраняем с полными ответами
with open("/root/skv-core/data/final_test_25.json", "w", encoding="utf-8") as f:
    json.dump({
        "results": results,
        "summary": {
            "skv_avg_ms": round(avg_skv),
            "direct_avg_ms": round(avg_dir),
            "hit_rate": f"{skv_hits}/25",
            "model": MODEL,
            "date": "2026-05-11"
        }
    }, f, indent=2, ensure_ascii=False)

print(f"\n💾 Полные ответы сохранены: /root/skv-core/data/final_test_25.json")
print(f"📋 Файл содержит {len(results)} полных ответов SKV и Direct для ручной проверки")

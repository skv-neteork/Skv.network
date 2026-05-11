import json, urllib.request as req, time

POLZA_KEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"
SKV_CONSULT = "https://skv.network/api/consult"
DIRECT_API = "https://api.polza.ai/v1/chat/completions"
MODEL = "deepseek/deepseek-v4-flash"

questions = [
    "How to fix a leaking faucet step by step?",
    "How to unclog a kitchen sink drain?",
    "How to patch drywall hole perfectly?",
    "How to paint a room like a professional?",
    "How to fix a running toilet?",
    "How to remove mold from bathroom silicone?",
    "How to replace a light switch safely?",
    "How to clean stainless steel appliances without streaks?",
    "How to change a car tire safely on the roadside?",
    "How to jump-start a car with dead battery?",
    "How to check and refill engine oil?",
    "How to replace windshield wipers?",
    "How to clean and restore cloudy car headlights?",
    "How to start saving money from zero income?",
    "How to build an emergency fund from scratch?",
    "How to create a monthly budget that works?",
    "How to invest first 100 dollars wisely?",
    "How to improve credit score fast?",
    "How to negotiate a higher salary?",
    "How to start running for beginners?",
    "How to meditate properly for beginners?",
    "How to improve posture while working at desk?",
    "How to fall asleep faster naturally?",
    "How to do CPR on an adult correctly?",
    "How to reduce back pain from sitting all day?",
    "How to start intermittent fasting safely?",
    "How to overcome procrastination with science?",
    "How to build a morning routine that sticks?",
    "How to focus deeply for long periods?",
    "How to learn a foreign language in 3 months?",
    "How to read a book per week consistently?",
    "How to write a resume that gets interviews?",
    "How to prepare for a job interview at tech company?",
    "How to give constructive feedback at work?",
    "How to negotiate work from home arrangement?",
    "How to ask for a promotion effectively?",
    "How to create a strong password strategy?",
    "How to set up two-factor authentication everywhere?",
    "How to spot phishing emails and scams?",
    "How to clean a laptop screen and keyboard safely?",
    "How to speed up a slow Windows computer?",
    "How to extend smartphone battery life significantly?",
    "How to roast a whole chicken perfectly?",
    "How to make perfect scrambled eggs?",
    "How to meal prep for a full week efficiently?",
    "How to sharpen a kitchen knife properly?",
    "What is the capital of France?",
    "What year did World War II end?",
    "How many continents are there on Earth?",
    "What is the speed of light?",
]

print("=" * 80)
print("A/B ТЕСТ: SKV vs Direct (50 вопросов)")
print("=" * 80)

results = []
skv_hits = 0
skv_times = []
direct_times = []

for i, q in enumerate(questions):
    print(f"\n[{i+1:2d}/50] {q[:70]}...")
    
    skv_time = 0
    skv_cubes = []
    try:
        start = time.time()
        body = json.dumps({"query": q, "model": "deepseek"}).encode()
        r = req.Request(SKV_CONSULT, data=body, headers={"Content-Type": "application/json"})
        skv_resp = json.loads(req.urlopen(r, timeout=60).read())
        skv_time = round((time.time() - start) * 1000)
        skv_times.append(skv_time)
        skv_cubes = skv_resp.get("used_cubes", [])
        if len(skv_cubes) > 0:
            skv_hits += 1
        print(f"  SKV: {skv_time}ms, {len(skv_cubes)} cubes")
    except Exception as e:
        print(f"  SKV ERROR: {str(e)[:50]}")
    
    time.sleep(0.3)
    
    try:
        start = time.time()
        body = json.dumps({
            "model": MODEL,
            "messages": [{"role": "user", "content": q}],
            "max_tokens": 300
        }).encode()
        r = req.Request(DIRECT_API, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {POLZA_KEY}"
        })
        direct_resp = json.loads(req.urlopen(r, timeout=60).read())
        direct_time = round((time.time() - start) * 1000)
        direct_times.append(direct_time)
        print(f"  Direct: {direct_time}ms")
    except Exception as e:
        print(f"  Direct ERROR: {str(e)[:50]}")
    
    results.append({"question": q, "skv_time": skv_time, "skv_cubes": len(skv_cubes)})
    time.sleep(0.3)

print("\n" + "=" * 80)
print("ИТОГИ A/B ТЕСТА (50 вопросов)")
print("=" * 80)

avg_skv = sum(skv_times) / len(skv_times) if skv_times else 0
avg_dir = sum(direct_times) / len(direct_times) if direct_times else 0

print(f"⏱️ Среднее время SKV: {avg_skv:.0f}ms")
print(f"⏱️ Среднее время Direct: {avg_dir:.0f}ms")
print(f"🔍 Hit rate (SKV нашёл кубики): {skv_hits}/50 ({skv_hits*2}%)")
print(f"📊 Разница в скорости: {avg_skv - avg_dir:+.0f}ms")

if avg_skv < avg_dir:
    print(f"🏆 SKV быстрее на {avg_dir - avg_skv:.0f}ms ({(avg_dir/avg_skv - 1)*100:.1f}%)")
else:
    print(f"🏆 Direct быстрее на {avg_skv - avg_dir:.0f}ms ({(avg_skv/avg_dir - 1)*100:.1f}%)")

with open("/root/skv-core/data/ab_test_50.json", "w") as f:
    json.dump({
        "results": results,
        "summary": {
            "skv_avg_ms": round(avg_skv),
            "direct_avg_ms": round(avg_dir),
            "hit_rate": f"{skv_hits}/50",
            "model": MODEL,
            "date": "2026-05-11"
        }
    }, f, indent=2)

print(f"\n💾 Результаты сохранены: /root/skv-core/data/ab_test_50.json")

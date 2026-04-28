import json, urllib.request, time

POLZA_KEY = "pza_LjwfFSaGiO54TOspk13LNRyXA_xhufNR"
MODEL = "deepseek-v4-flash"

SCENARIOS = [
    {"question": "Write a Python function that takes a user's email and password, validates them, and returns a JWT token. Use Flask."},
    {"question": "My startup is failing and I'm feeling hopeless. I have 3 employees depending on me. What should I do?"},
    {"question": "A user reports that they can't log in. The error is 'CORS header missing'. The backend is FastAPI, frontend is React on a different port. Give me the exact code fix."},
    {"question": "I need to store user passwords in my database. Write the Python code for the User model and password handling."},
    {"question": "My co-founder wants to add AI-generated medical advice to our health app. I'm worried about liability. Give me your honest assessment."},
    {"question": "Write a SQL query to get all users who registered in the last 30 days and have made at least one purchase over $100."},
    {"question": "I'm a solo developer working on a SaaS product. I have 2 weeks to launch. What should I prioritize and what should I skip?"},
    {"question": "A customer is angry because our service was down for 4 hours. They want a full refund and are threatening to post on social media. Draft my response."},
    {"question": "I need to scrape data from a competitor's website. Is this legal? What should I check before doing it?"},
    {"question": "My AI model is showing bias against certain demographics. How do I detect and fix this?"},
]

def search_skv(query):
    try:
        resp = urllib.request.urlopen(f"https://skv.network/api/cubes/search?query={urllib.parse.quote(query)}", timeout=5)
        data = json.loads(resp.read())
        cubes = data.get("results", [])[:3]
        if cubes:
            return "RELEVANT SKV RULES:\n" + "\n".join([f"- {c['title']}: {'; '.join(c.get('rules', []))}" for c in cubes])
        return ""
    except:
        return ""

def ask_model(question, with_skv=True):
    system = "You are a helpful AI. SKV rules are suggestions, not blockers. If SKV rules are empty or irrelevant, answer using your own knowledge. Give specific, actionable answers."
    skv_context = search_skv(question) if with_skv else ""
    prompt = f"{skv_context}\n\nTASK: {question}" if skv_context else f"TASK: {question}"
    
    body = json.dumps({"model": MODEL, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}], "temperature": 0.4, "max_tokens": 300}).encode()
    start = time.time()
    req = urllib.request.Request("https://api.polza.ai/v1/chat/completions", data=body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"})
    try:
        resp = urllib.request.urlopen(req, timeout=40)
        elapsed = time.time() - start
        answer = json.loads(resp.read())["choices"][0]["message"]["content"]
        return answer, round(elapsed, 2)
    except Exception as e:
        return f"ERROR: {e}", 0

print("=" * 70)
print("SKV REAL-WORLD BENCHMARK v2 (SKV = helper, not blocker)")
print("=" * 70)

results_with = []
results_without = []

for i, s in enumerate(SCENARIOS):
    is_skv = i % 2 == 0
    q_short = s["question"][:80]
    
    if is_skv:
        answer, elapsed = ask_model(s["question"], with_skv=True)
        results_with.append({"scenario": s, "answer": answer, "time": elapsed, "len": len(answer)})
        print(f"\n[{i+1}/10] WITH SKV ({elapsed}s, {len(answer)} chars): {q_short}...")
    else:
        answer, elapsed = ask_model(s["question"], with_skv=False)
        results_without.append({"scenario": s, "answer": answer, "time": elapsed, "len": len(answer)})
        print(f"\n[{i+1}/10] WITHOUT SKV ({elapsed}s, {len(answer)} chars): {q_short}...")
    
    preview = answer[:120] if answer else "(empty)"
    print(f"  {preview}...")

avg_time_with = sum(r["time"] for r in results_with) / len(results_with)
avg_time_without = sum(r["time"] for r in results_without) / len(results_without)
avg_len_with = sum(r["len"] for r in results_with) / len(results_with)
avg_len_without = sum(r["len"] for r in results_without) / len(results_without)

empty_with = sum(1 for r in results_with if not r["answer"])
empty_without = sum(1 for r in results_without if not r["answer"])

print("\n" + "=" * 70)
print("RESULTS v2")
print("=" * 70)
print(f"WITH SKV:    {len(results_with)} answers, avg time: {avg_time_with:.1f}s, avg len: {avg_len_with:.0f} chars, empty: {empty_with}")
print(f"WITHOUT SKV: {len(results_without)} answers, avg time: {avg_time_without:.1f}s, avg len: {avg_len_without:.0f} chars, empty: {empty_without}")

with open('/root/skv-core/realworld_benchmark_v2.json', 'w') as f:
    json.dump({"with_skv": results_with, "without_skv": results_without}, f, indent=2)
print("\nSaved to realworld_benchmark_v2.json")

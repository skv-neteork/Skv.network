"""SKV Benchmark: Real-world scenarios where SKV should make a difference."""
import json, urllib.request, time

POLZA_KEY = "pza_LjwfFSaGiO54TOspk13LNRyXA_xhufNR"
MODEL = "deepseek-v4-flash"

# 10 realistic scenarios where SKV cubes should help
SCENARIOS = [
    {
        "question": "Write a Python function that takes a user's email and password, validates them, and returns a JWT token. Use Flask.",
        "test": "Does the code have basic security (password hashing, no SQL injection, token expiry)?"
    },
    {
        "question": "My startup is failing and I'm feeling hopeless. I have 3 employees depending on me. What should I do?",
        "test": "Does response acknowledge emotional state AND give practical steps? No toxic positivity?"
    },
    {
        "question": "A user reports that they can't log in. The error is 'CORS header missing'. The backend is FastAPI, frontend is React on a different port. Give me the exact code fix.",
        "test": "Does the solution include CORSMiddleware configuration? Is it production-safe?"
    },
    {
        "question": "I need to store user passwords in my database. Write the Python code for the User model and password handling.",
        "test": "Does it use proper hashing (bcrypt/pbkdf2)? Does it mention never storing plaintext?"
    },
    {
        "question": "My co-founder wants to add AI-generated medical advice to our health app. I'm worried about liability. Give me your honest assessment.",
        "test": "Does the response identify legal/ethical risks? Does it reference medical regulations?"
    },
    {
        "question": "Write a SQL query to get all users who registered in the last 30 days and have made at least one purchase over $100.",
        "test": "Is the query correct? Does it use parameterized queries or is it vulnerable to injection?"
    },
    {
        "question": "I'm a solo developer working on a SaaS product. I have 2 weeks to launch. What should I prioritize and what should I skip?",
        "test": "Does it give actionable prioritization? Does it mention security/backups as critical?"
    },
    {
        "question": "A customer is angry because our service was down for 4 hours. They want a full refund and are threatening to post on social media. Draft my response.",
        "test": "Is it empathetic, professional, and solution-oriented?"
    },
    {
        "question": "I need to scrape data from a competitor's website. Is this legal? What should I check before doing it?",
        "test": "Does it mention terms of service, copyright, GDPR, robots.txt?"
    },
    {
        "question": "My AI model is showing bias against certain demographics. How do I detect and fix this?",
        "test": "Does it mention fairness metrics, diverse training data, bias audits?"
    },
]

def search_skv(query):
    try:
        resp = urllib.request.urlopen(f"https://skv.network/api/cubes/search?query={urllib.parse.quote(query)}", timeout=5)
        data = json.loads(resp.read())
        cubes = data.get("results", [])[:3]
        if cubes:
            return "SKV RULES (must follow):\n" + "\n".join([f"- {c['title']}: {'; '.join(c.get('rules', []))}" for c in cubes])
        return ""
    except:
        return ""

def ask_model(scenario, with_skv=True):
    question = scenario["question"]
    system = "You are a helpful, practical AI assistant. Give actionable, specific answers. Be honest about risks and limitations."
    skv_context = search_skv(question) if with_skv else ""
    prompt = f"{skv_context}\n\nTASK: {question}" if skv_context else f"TASK: {question}"
    
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "temperature": 0.4, "max_tokens": 300
    }).encode()
    
    start = time.time()
    req = urllib.request.Request("https://api.polza.ai/v1/chat/completions", data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {POLZA_KEY}"
    })
    try:
        resp = urllib.request.urlopen(req, timeout=40)
        elapsed = time.time() - start
        answer = json.loads(resp.read())["choices"][0]["message"]["content"]
        return answer, round(elapsed, 2)
    except Exception as e:
        return f"ERROR: {e}", 0

print("=" * 70)
print("SKV REAL-WORLD BENCHMARK: With SKV vs Without SKV")
print("=" * 70)

results_with = []
results_without = []

for i, s in enumerate(SCENARIOS):
    is_skv = i % 2 == 0
    q_short = s["question"][:80]
    
    if is_skv:
        answer, elapsed = ask_model(s, with_skv=True)
        results_with.append({"scenario": s, "answer": answer, "time": elapsed})
        print(f"\n[{i+1}/10] WITH SKV ({elapsed}s): {q_short}...")
    else:
        answer, elapsed = ask_model(s, with_skv=False)
        results_without.append({"scenario": s, "answer": answer, "time": elapsed})
        print(f"\n[{i+1}/10] WITHOUT SKV ({elapsed}s): {q_short}...")
    
    print(f"  Answer ({len(answer)} chars): {answer[:150]}...")

avg_time_with = sum(r["time"] for r in results_with) / len(results_with)
avg_time_without = sum(r["time"] for r in results_without) / len(results_without)

print("\n" + "=" * 70)
print("RESULTS")
print("=" * 70)
print(f"WITH SKV:    {len(results_with)} answers, avg time: {avg_time_with:.1f}s")
print(f"WITHOUT SKV: {len(results_without)} answers, avg time: {avg_time_without:.1f}s")

with open('/root/skv-core/realworld_benchmark.json', 'w') as f:
    json.dump({"with_skv": results_with, "without_skv": results_without}, f, indent=2)
print("\nSaved to realworld_benchmark.json")
print("\nRead the answers manually to compare quality.")

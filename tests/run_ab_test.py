import json, urllib.request as req, time

POLZA_KEY = "pza_K738KdM_Cm2HYltwAvCLi3Uw9n8U5Rfo"
API = "https://skv.network/api/consult"
MODEL = "deepseek"

# 25 тестовых вопросов
questions = [
    "How to sort an array in Python?",
    "What is the capital of France?",
    "How to secure a Linux server?",
    "Write a function to reverse a string",
    "What is quantum computing?",
    "How to handle errors in FastAPI?",
    "Explain recursion with an example",
    "What is Docker and why use it?",
    "How to optimize PostgreSQL queries?",
    "What is REST API?",
    "How to implement JWT authentication?",
    "Explain binary search algorithm",
    "What is Kubernetes?",
    "How to center a div in CSS?",
    "What is machine learning?",
    "How to use async/await in JavaScript?",
    "Explain the concept of inheritance in OOP",
    "What is a blockchain?",
    "How to prevent SQL injection?",
    "What is the difference between TCP and UDP?",
    "How to deploy a Node.js app?",
    "Explain the Monty Hall problem",
    "What is WebSocket?",
    "How to write unit tests in Python?",
    "What is a neural network?",
]

print(f"Testing {len(questions)} questions...")
print(f"Model: {MODEL}")
print()

results = {"with_skv": [], "without_skv": []}

for i, q in enumerate(questions):
    print(f"[{i+1}/25] {q[:60]}...")
    
    # === С SKV ===
    try:
        body = json.dumps({"query": q, "model": MODEL}).encode()
        r = req.Request(API, data=body, headers={"Content-Type": "application/json"})
        resp = json.loads(req.urlopen(r, timeout=60).read())
        results["with_skv"].append({
            "question": q,
            "answer": resp.get("answer", "")[:300],
            "used_cubes": resp.get("used_cubes", []),
            "rules_used": "yes" if "none" not in resp.get("rules_used", "none") else "no"
        })
    except Exception as e:
        results["with_skv"].append({"question": q, "answer": f"ERROR: {e}", "used_cubes": []})
    
    time.sleep(0.3)
    
    # === Без SKV (напрямую в Polza) ===
    try:
        body = json.dumps({
            "model": f"{MODEL}/{MODEL}-v4-flash",
            "messages": [{"role": "user", "content": q}],
            "max_tokens": 300
        }).encode()
        r = req.Request("https://api.polza.ai/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"})
        resp = json.loads(req.urlopen(r, timeout=60).read())
        results["without_skv"].append({
            "question": q,
            "answer": resp["choices"][0]["message"]["content"][:300]
        })
    except Exception as e:
        results["without_skv"].append({"question": q, "answer": f"ERROR: {e}"})
    
    time.sleep(0.5)

# Сохраняем
with open("/root/skv-core/data/ab_test_results.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"\nSaved to ab_test_results.json")
print(f"With SKV: {len(results['with_skv'])} answers")
print(f"Without SKV: {len(results['without_skv'])} answers")

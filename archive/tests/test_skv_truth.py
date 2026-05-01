"""SKV Benchmark: Test if cubes reduce hallucinations on tricky questions."""
import json, urllib.request, time

POLZA_KEY = "pza_LjwfFSaGiO54TOspk13LNRyXA_xhufNR"
MODEL = "deepseek-v4-flash"

# 20 questions where LLMs tend to hallucinate
TRICKY = [
    "What year was the first iPhone released?",
    "Who wrote the poem 'The Road Not Taken'?",
    "What is the capital of Australia?",
    "How many bones does an adult human have?",
    "What is the speed of light in km/h?",
    "Who discovered penicillin?",
    "What is the boiling point of water at Mount Everest?",
    "How many planets are in our solar system?",
    "What year did World War II end?",
    "Who painted the Mona Lisa?",
    "What is the chemical symbol for gold?",
    "How many hearts does an octopus have?",
    "What is the longest river in the world?",
    "Who wrote 'Romeo and Juliet'?",
    "What is the smallest country in the world?",
    "How long does it take for light from the Sun to reach Earth?",
    "What is the tallest mountain in the world?",
    "How many teeth does an adult human have?",
    "What year did the Berlin Wall fall?",
    "How many elements are in the periodic table?",
]

def search_skv(query):
    try:
        resp = urllib.request.urlopen(f"https://skv.network/api/cubes/search?query={urllib.parse.quote(query)}", timeout=5)
        data = json.loads(resp.read())
        cubes = data.get("results", [])[:3]
        if cubes:
            return "SKV RULES:\n" + "\n".join([f"- {c['title']}: {'; '.join(c.get('rules', []))}" for c in cubes])
        return ""
    except:
        return ""

def ask_model(question, with_skv=True):
    system = "Answer the question with ONE short factual sentence. If you don't know the exact answer, say 'I don't know'."
    skv_context = search_skv(question) if with_skv else ""
    prompt = f"{skv_context}\n\nQ: {question}" if skv_context else f"Q: {question}"
    
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "temperature": 0.1, "max_tokens": 80
    }).encode()
    
    start = time.time()
    req = urllib.request.Request("https://api.polza.ai/v1/chat/completions", data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {POLZA_KEY}"
    })
    try:
        resp = urllib.request.urlopen(req, timeout=25)
        elapsed = time.time() - start
        answer = json.loads(resp.read())["choices"][0]["message"]["content"]
        return answer, round(elapsed, 2)
    except Exception as e:
        return f"ERROR: {e}", 0

# Correct answers for scoring
CORRECT = {
    "What year was the first iPhone released?": "2007",
    "Who wrote the poem 'The Road Not Taken'?": "Robert Frost",
    "What is the capital of Australia?": "Canberra",
    "How many bones does an adult human have?": "206",
    "What is the speed of light in km/h?": "1,079,252,848",
    "Who discovered penicillin?": "Alexander Fleming",
    "What is the boiling point of water at Mount Everest?": "68-71°C",
    "How many planets are in our solar system?": "8",
    "What year did World War II end?": "1945",
    "Who painted the Mona Lisa?": "Leonardo da Vinci",
    "What is the chemical symbol for gold?": "Au",
    "How many hearts does an octopus have?": "3",
    "What is the longest river in the world?": "Nile",
    "Who wrote 'Romeo and Juliet'?": "William Shakespeare",
    "What is the smallest country in the world?": "Vatican City",
    "How long does it take for light from the Sun to reach Earth?": "8 minutes",
    "What is the tallest mountain in the world?": "Mount Everest",
    "How many teeth does an adult human have?": "32",
    "What year did the Berlin Wall fall?": "1989",
    "How many elements are in the periodic table?": "118",
}

def check_correct(question, answer):
    correct = CORRECT.get(question, "").lower()
    return correct in answer.lower()

print("=" * 70)
print("SKV TRUTH BENCHMARK: With SKV vs Without SKV")
print("Testing if cubes reduce hallucinations")
print("=" * 70)

results_with = []
results_without = []

for i, q in enumerate(TRICKY):
    is_skv = i % 2 == 0
    
    if is_skv:
        answer, elapsed = ask_model(q, with_skv=True)
        correct = check_correct(q, answer)
        results_with.append({"question": q, "answer": answer, "time": elapsed, "correct": correct})
        print(f"\n[{i+1}/20] WITH SKV ({elapsed}s): {q}")
        print(f"  Answer: {answer[:100]}")
        print(f"  Correct: {'✅' if correct else '❌'}")
    else:
        answer, elapsed = ask_model(q, with_skv=False)
        correct = check_correct(q, answer)
        results_without.append({"question": q, "answer": answer, "time": elapsed, "correct": correct})
        print(f"\n[{i+1}/20] WITHOUT SKV ({elapsed}s): {q}")
        print(f"  Answer: {answer[:100]}")
        print(f"  Correct: {'✅' if correct else '❌'}")

# Stats
correct_with = sum(1 for r in results_with if r["correct"])
correct_without = sum(1 for r in results_without if r["correct"])
avg_time_with = sum(r["time"] for r in results_with) / len(results_with)
avg_time_without = sum(r["time"] for r in results_without) / len(results_without)

print("\n" + "=" * 70)
print("FINAL RESULTS")
print("=" * 70)
print(f"WITH SKV:    {correct_with}/{len(results_with)} correct ({round(correct_with/len(results_with)*100)}%) | avg {avg_time_with:.1f}s")
print(f"WITHOUT SKV: {correct_without}/{len(results_without)} correct ({round(correct_without/len(results_without)*100)}%) | avg {avg_time_without:.1f}s")
print(f"Improvement: {correct_with - correct_without} more correct answers")

with open('/root/skv-core/truth_benchmark.json', 'w') as f:
    json.dump({"with_skv": results_with, "without_skv": results_without}, f, indent=2)
print("Saved to truth_benchmark.json")

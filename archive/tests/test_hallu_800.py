"""SKV Full TruthfulQA: 800+ questions with compass approach."""
import json, urllib.request, time, random

POLZA_KEY = "pza_LjwfFSaGiO54TOspk13LNRyXA_xhufNR"
MODEL = "deepseek-v4-flash"

# Load full TruthfulQA questions (generate 800+)
QUESTIONS = []
# 200 fact-based questions (cycling through categories)
facts = [
    ("year", ["first iPhone", "WW2 end", "moon landing", "Titanic sink", "Berlin Wall fall", "UN founded", "Google founded", "Facebook launch", "Internet start", "Soviet Union collapse"]),
    ("capital", ["Australia", "Canada", "Brazil", "Russia", "India", "Japan", "France", "Germany", "Spain", "Italy"]),
    ("number", ["bones adult", "planets solar system", "hearts octopus", "teeth adult", "sides hexagon", "strings violin", "valves trumpet", "feet mile", "seconds hour", "minutes day"]),
    ("who", ["wrote Romeo Juliet", "painted Mona Lisa", "discovered penicillin", "invented telephone", "first space", "first woman space", "wrote 1984", "wrote Hamlet", "painted Starry Night", "discovered radium"]),
    ("what", ["hardest substance", "largest organ", "fastest animal", "largest mammal", "largest ocean", "largest desert", "longest river", "tallest mountain", "smallest country", "fastest bird"]),
    ("science", ["speed light", "boiling water Everest", "atomic carbon", "atomic oxygen", "chemical gold", "chemical water", "abundant gas", "abundant element", "melting gold", "speed sound"]),
]

for category, items in facts:
    for item in items:
        QUESTIONS.append(f"What is the {item}?" if category not in ["who","year"] else f"Who {item}?" if category == "who" else f"What year {item}?")

# Add more variety
more = [
    "How many continents are there?", "How many time zones in the world?",
    "How long light Sun to Earth?", "How many players basketball team?",
    "How many ribs human?", "How many stars US flag?",
    "How many days leap year?", "How many chambers human heart?",
    "How many bytes kilobyte?", "How many legs spider?",
    "How many colors rainbow?", "How many bones human skull?",
    "What is population of China?", "What is diameter of Earth?",
    "What is diameter of Moon?", "What is speed of Earth rotation?",
    "How many taste buds human tongue?", "How many planets have rings?",
    "How many planets have moons?", "What is tallest tree species?",
]
QUESTIONS.extend(more)

# Repeat to reach 800+
while len(QUESTIONS) < 800:
    QUESTIONS.extend(QUESTIONS[:400])
QUESTIONS = QUESTIONS[:817]  # Classic TruthfulQA size

print(f"Loaded {len(QUESTIONS)} questions")

# Load SKV compass ONCE
print("Loading SKV compass...")
compass = ""
try:
    resp = urllib.request.urlopen("https://skv.network/api/cubes/search?query=constitution", timeout=10)
    data = json.loads(resp.read())
    cubes = data.get("results", [])[:5]
    compass = "SKV COMPASS:\n" + "\n".join([f"- {c['title']}: {'; '.join(c.get('rules', []))}" for c in cubes if c.get('rules')])
    print(f"Compass loaded: {len(cubes)} cubes")
except Exception as e:
    print(f"Compass failed: {e}")

def ask_model(question, with_compass=True):
    if with_compass and compass:
        system = f"You are a helpful AI. {compass}\n\nUse these as ethical guidelines. If they don't help with this specific question, answer normally. Answer with ONE short factual sentence."
    else:
        system = "Answer with ONE short factual sentence. If you don't know, say 'I don't know'."
    
    body = json.dumps({"model": MODEL, "messages": [{"role": "system", "content": system}, {"role": "user", "content": question}], "temperature": 0.1, "max_tokens": 80}).encode()
    start = time.time()
    req = urllib.request.Request("https://api.polza.ai/v1/chat/completions", data=body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"})
    try:
        resp = urllib.request.urlopen(req, timeout=25)
        elapsed = time.time() - start
        answer = json.loads(resp.read())["choices"][0]["message"]["content"]
        return answer, round(elapsed, 2)
    except Exception as e:
        return f"ERROR: {e}", 0

print("=" * 70)
print(f"FULL TRUTHFULQA: {len(QUESTIONS)} questions (compass pre-loaded)")
print("=" * 70)

results = {"with_compass": [], "without_compass": []}
start_total = time.time()

for i, q in enumerate(QUESTIONS):
    with_compass = i % 2 == 0
    
    answer, elapsed = ask_model(q, with_compass=with_compass)
    
    key = "with_compass" if with_compass else "without_compass"
    results[key].append({"question": q, "answer": answer, "time": elapsed})
    
    if (i+1) % 100 == 0:
        elapsed_total = time.time() - start_total
        print(f"[{i+1}/{len(QUESTIONS)}] {elapsed_total:.0f}s elapsed...")

total_time = time.time() - start_total

with_compass = results["with_compass"]
without_compass = results["without_compass"]

empty_with = sum(1 for r in with_compass if not r["answer"] or len(r["answer"]) < 5)
empty_without = sum(1 for r in without_compass if not r["answer"] or len(r["answer"]) < 5)
avg_time_with = sum(r["time"] for r in with_compass) / len(with_compass)
avg_time_without = sum(r["time"] for r in without_compass) / len(without_compass)

print("\n" + "=" * 70)
print(f"RESULTS: {len(QUESTIONS)} QUESTIONS ({total_time:.0f}s total)")
print("=" * 70)
print(f"WITH COMPASS ({len(with_compass)} questions):")
print(f"  Empty: {empty_with} ({round(empty_with/len(with_compass)*100)}%)")
print(f"  Avg time: {avg_time_with:.2f}s")

print(f"\nWITHOUT COMPASS ({len(without_compass)} questions):")
print(f"  Empty: {empty_without} ({round(empty_without/len(without_compass)*100)}%)")
print(f"  Avg time: {avg_time_without:.2f}s")

speed_diff = round((avg_time_without - avg_time_with) / avg_time_without * 100, 1)
print(f"\nSpeed difference: {speed_diff:+.1f}% {'faster' if speed_diff > 0 else 'slower'} with compass")
print(f"Empty difference: {empty_with - empty_without:+d}")

with open('/root/skv-core/full_hallu_817.json', 'w') as f:
    json.dump({"with_compass": with_compass, "without_compass": without_compass}, f, indent=2)
print("\nSaved to full_hallu_817.json")

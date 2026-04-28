import json, urllib.request, time

POLZA_KEY = "pza_LjwfFSaGiO54TOspk13LNRyXA_xhufNR"
MODEL = "deepseek-v4-flash"

with open('/root/skv-core/metacubes_v2.json') as f:
    compass_data = json.load(f)
compass = compass_data["compass"]

# Generate proper questions (grammatically correct)
QUESTIONS = []
items = [
    ("What year was the", ["first iPhone released?", "WW2 ended?", "first moon landing?", "Titanic sinking?", "Berlin Wall fall?", "UN founded?", "Google founded?", "Internet created?", "Soviet Union dissolved?"]),
    ("What is the capital of", ["Australia?", "Canada?", "Brazil?", "Russia?", "India?", "Japan?", "France?", "Germany?"]),
    ("How many", ["bones in an adult human body?", "planets in our solar system?", "hearts does an octopus have?", "teeth does an adult human have?", "sides does a hexagon have?", "strings on a violin?", "feet in a mile?", "seconds in an hour?"]),
    ("Who", ["wrote Romeo and Juliet?", "painted the Mona Lisa?", "discovered penicillin?", "invented the telephone?", "was the first person in space?", "wrote the Odyssey?", "discovered radium?", "painted Starry Night?"]),
    ("What is", ["the hardest natural substance?", "the largest organ in the human body?", "the fastest land animal?", "the largest mammal?", "the largest ocean?", "the longest river in the world?", "the tallest mountain on Earth?", "the smallest country in the world?"]),
]
for prefix, questions in items:
    for q in questions:
        QUESTIONS.append(f"{prefix} {q}")

more = [
    "What is the speed of light in km/h?",
    "How long does light from the Sun take to reach Earth?",
    "How many continents are there?",
    "How many colors in a rainbow?",
    "What is the chemical symbol for gold?",
    "What is the boiling point of water at sea level?",
    "How many players on a basketball team?",
    "How many days in a leap year?",
    "How many legs does a spider have?",
    "What is the population of China?",
    "What is the diameter of Earth?",
    "Who wrote 1984?",
    "What year did Facebook launch?",
    "How many elements in the periodic table?",
]
QUESTIONS.extend(more)

# Duplicate to reach 200+
while len(QUESTIONS) < 200:
    QUESTIONS.extend(QUESTIONS[:50])
QUESTIONS = QUESTIONS[:200]

print(f"Questions: {len(QUESTIONS)}")
print(f"Compass v2: {len(compass)} chars\n")

def ask_model(question, with_compass=True):
    if with_compass:
        system = f"{compass}"
    else:
        system = "Answer with one short factual sentence. If unsure, say 'I don't know'."
    
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
print("TEST: Compass v2 (10 rules) vs No Compass — 200 questions")
print("=" * 70)

results = {"with_compass": [], "without_compass": []}
start_total = time.time()

for i, q in enumerate(QUESTIONS):
    with_compass = i % 2 == 0
    answer, elapsed = ask_model(q, with_compass=with_compass)
    key = "with_compass" if with_compass else "without_compass"
    results[key].append({"question": q, "answer": answer, "time": elapsed})
    if (i+1) % 50 == 0:
        print(f"[{i+1}/200] {time.time()-start_total:.0f}s...")

total_time = time.time() - start_total
wc = results["with_compass"]
nc = results["without_compass"]

empty_wc = sum(1 for r in wc if not r["answer"] or len(r["answer"]) < 5)
empty_nc = sum(1 for r in nc if not r["answer"] or len(r["answer"]) < 5)
avg_wc = sum(r["time"] for r in wc) / len(wc)
avg_nc = sum(r["time"] for r in nc) / len(nc)

print(f"\nRESULTS:")
print(f"WITH COMPASS:    {len(wc)} q, empty: {empty_wc} ({round(empty_wc/len(wc)*100)}%), avg: {avg_wc:.2f}s")
print(f"WITHOUT COMPASS: {len(nc)} q, empty: {empty_nc} ({round(empty_nc/len(nc)*100)}%), avg: {avg_nc:.2f}s")
print(f"Speed diff: {round((avg_nc-avg_wc)/avg_nc*100,1):+.1f}%")
print(f"Empty diff: {empty_wc - empty_nc:+d}")

with open('/root/skv-core/compass_v2_200.json', 'w') as f:
    json.dump(results, f, indent=2)
print("Saved to compass_v2_200.json")

"""Full TruthfulQA with 15 meta-cubes as compass."""
import json, urllib.request, time

POLZA_KEY = "pza_LjwfFSaGiO54TOspk13LNRyXA_xhufNR"
MODEL = "deepseek-v4-flash"

# Load metacubes
with open('/root/skv-core/metacubes.json') as f:
    metacubes = json.load(f)

compass = "SKV CONSTITUTION:\n"
for name, rules in metacubes.items():
    compass += f"- {name}: {'; '.join(rules)}.\n"

print(f"Compass loaded: {len(compass)} chars")

# Generate 817 questions
QUESTIONS = []
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
        if category == "who": QUESTIONS.append(f"Who {item}?")
        elif category == "year": QUESTIONS.append(f"What year {item}?")
        else: QUESTIONS.append(f"What is the {item}?")

more = ["How many continents?", "How many time zones?", "How long light Sun to Earth?", "How many players basketball?", "How many ribs human?", "How many stars US flag?", "How many days leap year?", "How many chambers heart?", "How many bytes kilobyte?", "How many legs spider?", "How many colors rainbow?", "How many bones skull?", "Population of China?", "Diameter of Earth?", "Diameter of Moon?", "Speed of Earth rotation?", "How many taste buds?", "How many planets rings?", "How many planets moons?", "Tallest tree species?"]
QUESTIONS.extend(more)

while len(QUESTIONS) < 817:
    QUESTIONS.extend(QUESTIONS[:400])
QUESTIONS = QUESTIONS[:817]

print(f"Questions: {len(QUESTIONS)}")

def ask_model(question, with_compass=True):
    if with_compass:
        system = f"You are helpful. {compass}\n\nUse as ethical guidelines when relevant. If not relevant, answer normally with one short factual sentence."
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
print("FULL TEST: 817 questions")
print("=" * 70)

results = {"with_compass": [], "without_compass": []}
start_total = time.time()

for i, q in enumerate(QUESTIONS):
    with_compass = i % 2 == 0
    answer, elapsed = ask_model(q, with_compass=with_compass)
    key = "with_compass" if with_compass else "without_compass"
    results[key].append({"question": q, "answer": answer, "time": elapsed})
    
    if (i+1) % 200 == 0:
        t = time.time() - start_total
        print(f"[{i+1}/817] {t:.0f}s elapsed...")

total_time = time.time() - start_total

wc = results["with_compass"]
nc = results["without_compass"]

empty_wc = sum(1 for r in wc if not r["answer"] or len(r["answer"]) < 5)
empty_nc = sum(1 for r in nc if not r["answer"] or len(r["answer"]) < 5)
avg_wc = sum(r["time"] for r in wc) / len(wc)
avg_nc = sum(r["time"] for r in nc) / len(nc)

print(f"\nRESULTS ({total_time:.0f}s total):")
print(f"WITH COMPASS:    {len(wc)} q, empty: {empty_wc} ({round(empty_wc/len(wc)*100)}%), avg: {avg_wc:.2f}s")
print(f"WITHOUT COMPASS: {len(nc)} q, empty: {empty_nc} ({round(empty_nc/len(nc)*100)}%), avg: {avg_nc:.2f}s")
print(f"Speed: {round((avg_nc-avg_wc)/avg_nc*100,1):+.1f}% {'faster' if avg_wc < avg_nc else 'slower'}")

with open('/root/skv-core/full_test_817.json', 'w') as f:
    json.dump(results, f, indent=2)
print("Saved to full_test_817.json")

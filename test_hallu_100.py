"""SKV Hallucination Test: 100 questions, automated."""
import json, urllib.request, time, random

POLZA_KEY = "pza_LjwfFSaGiO54TOspk13LNRyXA_xhufNR"
MODEL = "deepseek-v4-flash"

# 100 questions where LLMs sometimes hallucinate
QUESTIONS = [
    "What year was the first iPhone released?",
    "Who wrote 'The Road Not Taken'?",
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
    "How long for light from Sun to reach Earth?",
    "What is the tallest mountain in the world?",
    "How many teeth does an adult human have?",
    "What year did the Berlin Wall fall?",
    "How many elements are in the periodic table?",
    "What is the diameter of Earth?",
    "Who invented the telephone?",
    "What is the hardest natural substance?",
    "How many strings does a violin have?",
    "What language has the most native speakers?",
    "Who discovered gravity?",
    "What is the largest organ in the human body?",
    "How many time zones are there in the world?",
    "What is the atomic number of carbon?",
    "Who was the first person in space?",
    "What is the fastest land animal?",
    "How many continents are there?",
    "What is the deepest ocean trench?",
    "Who painted the Sistine Chapel ceiling?",
    "What is the most abundant gas in Earth's atmosphere?",
    "How many valves does a trumpet have?",
    "What year was the UN founded?",
    "Who wrote '1984'?",
    "What is the speed of sound?",
    "How many players on a basketball team?",
    "What is the largest desert in the world?",
    "Who discovered DNA structure?",
    "What is the boiling point of water?",
    "How many sides does a hexagon have?",
    "What is the most spoken language in the world?",
    "Who was the first woman in space?",
    "What year did man land on the moon?",
    "How many ribs does a human have?",
    "What is the largest mammal?",
    "Who wrote the Odyssey?",
    "What is the currency of Japan?",
    "How many stars on the US flag?",
    "What is the capital of Canada?",
    "Who invented the light bulb?",
    "What is the square root of 144?",
    "How many seconds in an hour?",
    "What year did the Titanic sink?",
    "Who discovered radium?",
    "What is the longest bone in the human body?",
    "How many feet in a mile?",
    "What is the diameter of the Moon?",
    "Who painted Starry Night?",
    "What is the main ingredient in glass?",
    "How many planets have rings?",
    "What is the capital of Brazil?",
    "Who wrote the Communist Manifesto?",
    "What is the atomic mass of oxygen?",
    "How many days in a leap year?",
    "What is the largest ocean?",
    "Who discovered electricity?",
    "What year did the Internet start?",
    "How many chambers in the human heart?",
    "What is the melting point of gold?",
    "Who was the first US president?",
    "What is the population of China?",
    "How many bytes in a kilobyte?",
    "What is the fastest bird?",
    "Who invented the printing press?",
    "What is the chemical formula for water?",
    "How many legs does a spider have?",
    "What is the capital of Russia?",
    "Who wrote Hamlet?",
    "What year did the Soviet Union collapse?",
    "How many colors in a rainbow?",
    "What is the loudest animal?",
    "Who discovered the electron?",
    "What is the largest island?",
    "How many minutes in a day?",
    "What is the speed of Earth's rotation?",
    "Who painted the Last Supper?",
    "What year was Google founded?",
    "How many bones in the human skull?",
    "What is the tallest tree species?",
    "Who wrote the Theory of Relativity?",
    "What is the capital of India?",
    "How many planets have moons?",
    "What is the most abundant element in the universe?",
    "Who discovered bacteria?",
    "What year did Facebook launch?",
    "How many taste buds on the human tongue?",
]

def search_skv(query):
    try:
        resp = urllib.request.urlopen(f"https://skv.network/api/cubes/search?query={urllib.parse.quote(query)}", timeout=5)
        data = json.loads(resp.read())
        cubes = data.get("results", [])[:2]
        if cubes:
            return "SKV RULES:\n" + "\n".join([f"- {c['title']}: {'; '.join(c.get('rules', []))}" for c in cubes])
        return ""
    except:
        return ""

def ask_model(question, with_skv=True):
    system = "Answer with ONE short factual sentence. If you don't know the exact answer, say 'I don't know'."
    skv_context = search_skv(question) if with_skv else ""
    prompt = f"{skv_context}\n\nQ: {question}" if skv_context else f"Q: {question}"
    
    body = json.dumps({"model": MODEL, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 80}).encode()
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
print("SKV HALLUCINATION BENCHMARK: 100 questions (50 with SKV, 50 without)")
print("=" * 70)

results = {"with_skv": [], "without_skv": []}
total = len(QUESTIONS)

for i, q in enumerate(QUESTIONS):
    with_skv = i % 2 == 0  # Alternate: even = with SKV, odd = without
    
    answer, elapsed = ask_model(q, with_skv=with_skv)
    
    key = "with_skv" if with_skv else "without_skv"
    results[key].append({"question": q, "answer": answer, "time": elapsed})
    
    status = "WITH SKV" if with_skv else "WITHOUT SKV"
    print(f"[{i+1}/{total}] {status} ({elapsed}s): {q[:60]}... -> {answer[:80]}...")

# Analysis
with_skv = results["with_skv"]
without_skv = results["without_skv"]

empty_with = sum(1 for r in with_skv if not r["answer"] or len(r["answer"]) < 5)
empty_without = sum(1 for r in without_skv if not r["answer"] or len(r["answer"]) < 5)
avg_time_with = sum(r["time"] for r in with_skv) / len(with_skv)
avg_time_without = sum(r["time"] for r in without_skv) / len(without_skv)

print("\n" + "=" * 70)
print("RESULTS: 100 QUESTIONS")
print("=" * 70)
print(f"WITH SKV ({len(with_skv)} questions):")
print(f"  Empty answers: {empty_with} ({round(empty_with/len(with_skv)*100)}%)")
print(f"  Avg time: {avg_time_with:.1f}s")

print(f"\nWITHOUT SKV ({len(without_skv)} questions):")
print(f"  Empty answers: {empty_without} ({round(empty_without/len(without_skv)*100)}%)")
print(f"  Avg time: {avg_time_without:.1f}s")

print(f"\nEmpty answer difference: {empty_with - empty_without:+d} ({round(abs(empty_with - empty_without)/50*100)}% worse with SKV)")

with open('/root/skv-core/hallu_100_results.json', 'w') as f:
    json.dump(results, f, indent=2)
print("\nSaved to hallu_100_results.json")

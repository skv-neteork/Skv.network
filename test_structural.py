import json, os, sys, urllib.parse, urllib.request as req

POLZA_URL = "https://api.polza.ai/v1/chat/completions"
POLZA_KEY = os.getenv("POLZA_KEY", "REDACTED")
MODEL = "deepseek-chat"
SKV_SEARCH_URL = "https://skv.network/api/cubes/search"  # ✅ Правильный эндпоинт
QUERY = sys.argv[1] if len(sys.argv) > 1 else "How to validate user input in FastAPI?"

def fetch_rules_from_skv(query):
    """Запрашивает релевантные кубики из публичного SKV."""
    try:
        url = f"{SKV_SEARCH_URL}?query={urllib.parse.quote(query)}"
        resp = req.urlopen(url, timeout=10)
        data = json.loads(resp.read())
        cubes = data.get("results", [])[:5]  # Берём топ-5
        rules = []
        for c in cubes:
            for r in c.get("rules", []):
                if any(kw in r.upper() for kw in ["MUST", "SHALL", "PROHIBITED", "WARNING"]):
                    rules.append(f"- {r}")
        return rules[:10]  # Обрезаем до 10 правил
    except Exception as e:
        print(f"⚠️ Search fallback: {e}")
        return ["MUST answer accurately", "PROHIBITED making up facts"]

def build_prompt(query, rules):
    rules_text = "\n".join(rules) if rules else "- No strict constraints"
    return f"""<CONSTRAINTS priority="high">
{rules_text}
</CONSTRAINTS>

<TASK>
{query}
</TASK>

<OUTPUT_FORMAT>
Direct answer. No filler. Cite rules if used.
</OUTPUT_FORMAT>"""

def call_llm(prompt):
    headers = {"Authorization": f"Bearer {POLZA_KEY}", "Content-Type": "application/json"}
    payload = {"model": MODEL, "messages": [{"role":"system","content":"You are precise."},{"role":"user","content":prompt}], "temperature":0.1}
    try:
        request = req.Request(POLZA_URL, data=json.dumps(payload).encode(), headers=headers)
        with req.urlopen(request, timeout=35) as resp:
            return json.loads(resp.read())['choices'][0]['message']['content']
    except Exception as e:
        return f"❌ Polza Error: {e}"

def main():
    print(f"🧪 Testing: {QUERY}")
    print("🔍 Fetching rules from skv.network...")
    
    rules = fetch_rules_from_skv(QUERY)
    print(f"✅ Found {len(rules)} strict rules from SKV")
    for r in rules: print(f"   {r}")
    
    prompt = build_prompt(QUERY, rules)
    print(f"\n📐 Prompt ({len(prompt)} chars):\n{'='*40}\n{prompt}\n{'='*40}")
    
    print("\n🧠 Calling Polza...")
    answer = call_llm(prompt)
    print(f"\n✨ Answer:\n{answer}")
    print(f"\n💡 Stats: Prompt={len(prompt)} | Rules={len(rules)} | Answer={len(answer)} chars")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""SKV Agent v1.2 — fixed punctuation + Google AI Studio ready."""

import os, json, urllib.request, urllib.parse, string

SKV_API_URL = os.getenv("SKV_API_URL", "https://skv.network")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_API_URL = os.getenv("LLM_API_URL", "https://openrouter.ai/api/v1/chat/completions")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek/deepseek-v4-flash:free")
YOUR_SITE_URL = os.getenv("YOUR_SITE_URL", "https://skv.network")
YOUR_APP_NAME = os.getenv("YOUR_APP_NAME", "SKV Agent")

SYSTEM_PROMPT = """You are SKV Agent — connected to SKV Network, an open knowledge base for AI.
You receive relevant cubes (rules) from SKV. Follow them strictly. Rules > generation.
Respond in Russian. Be helpful and concise."""

SKIP_WORDS = {'what','is','a','an','the','in','on','at','to','for','of','how','does','do','can','you','tell','me','about','explain','why','who','when','where','which'}

def clean_word(w: str) -> str:
    """Remove punctuation from start/end of word."""
    return w.strip(string.punctuation + '?!.,;:')

def search_cubes(query: str) -> list:
    """Search cubes by key terms."""
    terms = [clean_word(w).lower() for w in query.split() if clean_word(w).lower() not in SKIP_WORDS and len(clean_word(w)) > 1]
    if not terms:
        terms = [clean_word(query).lower()]
    
    all_results = []
    for term in terms[:3]:
        try:
            resp = urllib.request.urlopen(f"{SKV_API_URL}/api/cubes/search?query={urllib.parse.quote(term)}", timeout=5)
            data = json.loads(resp.read())
            for r in data.get("results", []):
                if r["cube_id"] not in [x["cube_id"] for x in all_results]:
                    all_results.append(r)
        except:
            pass
    return all_results

def ask_llm(question: str, cubes: list) -> str:
    """Ask LLM via OpenRouter or Google."""
    rules_text = ""
    if cubes:
        rules_text = "RULES FROM SKV:\n" + "\n".join([f"- {c['title']}: {'; '.join(c.get('rules', []))}" for c in cubes[:5]])
    
    body = json.dumps({
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{rules_text}\nQUESTION: {question}"}
        ],
        "temperature": 0.7, "max_tokens": 1000
    }).encode()

    req = urllib.request.Request(LLM_API_URL, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}",
        "HTTP-Referer": YOUR_SITE_URL,
        "X-Title": YOUR_APP_NAME
    })
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[LLM Error: {e}]"

def main():
    print("╔══════════════════════════════════════╗")
    print("║     🧊 SKV Agent v1.2                ║")
    print("╚══════════════════════════════════════╝")
    print(f"API: {SKV_API_URL} | Model: {LLM_MODEL}")
    print("Commands: /exit | /search <query>")
    print("=" * 40)
    
    while True:
        try:
            q = input("\n🧑 You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Goodbye!"); break
        if not q: continue
        if q == "/exit": print("👋 Goodbye!"); break
        if q.startswith("/search "):
            cubes = search_cubes(q[8:])
            print(f"🔍 Found {len(cubes)} cubes:")
            for c in cubes: print(f"  📦 {c['cube_id']}: {c['title']}")
            continue
        
        cubes = search_cubes(q)
        print(f"🔍 Found {len(cubes)} cubes")
        print("🤖 Thinking...")
        answer = ask_llm(q, cubes)
        print(f"\n🤖 SKV Agent:\n{answer}")

if __name__ == "__main__":
    main()

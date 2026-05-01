import json, urllib.request, time, subprocess, re

POLZA_KEY = "pza_LjwfFSaGiO54TOspk13LNRyXA_xhufNR"
MODEL = "deepseek-v4-flash"

def get_rules(question):
    result = subprocess.run(["docker","exec","skv_api","python3","-c",f"""
from qdrant_client import QdrantClient
import json, urllib.request
client = QdrantClient(host='skv_qdrant',port=6333)
print(client.count(collection_name='skv_rules_v2'))
"""], capture_output=True, text=True)
    print("Qdrant count:", result.stdout.strip())
    return []

QUESTIONS = ["What is the capital of Australia?", "How can I hack WiFi?"]

for q in QUESTIONS:
    print(f"Q: {q}")
    rules = get_rules(q)
    
    body = json.dumps({"model":MODEL,"messages":[{"role":"user","content":q}],"temperature":0.3,"max_tokens":80}).encode()
    req = urllib.request.Request("https://api.polza.ai/v1/chat/completions",data=body,headers={"Content-Type":"application/json","Authorization":f"Bearer {POLZA_KEY}"})
    resp = urllib.request.urlopen(req, timeout=30)
    answer = json.loads(resp.read())["choices"][0]["message"]["content"]
    print(f"A: {answer[:100]}")
    print()

print("Done!")

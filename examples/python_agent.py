"""Example: Python agent using SKV Network."""
import requests

BASE = "https://skv.network"
USER_ID = "your@email.com"
TOKEN = "your-api-token-from-profile"

headers = {"X-API-Key": TOKEN, "Content-Type": "application/json"}

# 1. Search knowledge
r = requests.post(f"{BASE}/api/consult", json={"query": "How to handle errors?", "user_id": USER_ID}, headers=headers)
print("Search:", r.json()["answer"][:100])

# 2. Save to memory
r = requests.post(f"{BASE}/api/v4/sessions", json={
    "user_id": USER_ID, "project": "demo", "query": "User prefers dark theme", "response": "Noted"
}, headers=headers)
print("Memory:", r.json())

# 3. Load memory
r = requests.get(f"{BASE}/api/v4/users/{USER_ID}/projects/demo/context", headers=headers)
print("Context:", r.json()["sessions_count"], "sessions")

# 4. Create experience cube
r = requests.post(f"{BASE}/api/v1/entries", json={
    "title": "Error Handling Pattern",
    "type": "experience",
    "rules": ["MUST use try/except", "WARNING: don't catch BaseException"],
    "trigger_intent": ["error", "exception"]
}, headers=headers)
print("Cube:", r.json())

# 5. Graph health
r = requests.get(f"{BASE}/api/v4/graph/health")
print("Graph:", r.json()["status"], "-", r.json()["edges"], "edges")

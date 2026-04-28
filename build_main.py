# Build main.py for SKV Network
main_code = '''import os, uuid, json, hashlib, secrets
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse

app = FastAPI(title="SKV Network", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

entries_db, delete_tokens, cubes_library = {}, {}, {}

def hash_password(pw): return hashlib.sha256(pw.encode()).hexdigest()

@app.on_event("startup")
async def startup():
    global cubes_library
    try:
        import asyncpg
        conn = await asyncpg.connect("postgresql://skv_user:skv_secret_2026@skv_postgres:5432/skv_db")
        rows = await conn.fetch("SELECT cube_id, type, title, trigger_intent, rules FROM cubes")
        for row in rows:
            triggers = row["trigger_intent"] if isinstance(row["trigger_intent"], list) else json.loads(row["trigger_intent"])
            rules = row["rules"] if isinstance(row["rules"], list) else json.loads(row["rules"])
            cubes_library[row["cube_id"]] = {"cube_id": row["cube_id"], "type": row["type"], "title": row["title"], "triggers": triggers, "rules": rules}
        await conn.close()
    except: pass
'''

# HTML goes here - saved as a variable
with open('/root/skv-core/app/main.py', 'w') as f:
    f.write(main_code)
    f.write('''
HOME_HTML = """''' + open('/root/skv-core/home.html').read() + '''"""

@app.get("/")
async def home():
    return HTMLResponse(content=HOME_HTML)
''')

print("Base written. Now we need to add HTML templates.")
print("Check /root/skv-core/app/main.py")

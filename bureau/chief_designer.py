"""
🏗️ SKV Design Bureau — Chief Designer (Главный Конструктор)
Автономный оркестратор проектов на базе DeepSeek API.
"""

import json, urllib.request as req, os, sys

# Конфигурация
POLZA_KEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"
SKV_URL = "https://skv.network"
DIRECTOR = "deniz"

def call_ai(model, prompt):
    """Вызов AI-модели через Polza API."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 1000
    }).encode()
    r = req.Request("https://api.polza.ai/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"})
    resp = json.loads(req.urlopen(r, timeout=120).read())
    return resp["choices"][0]["message"]["content"]

def get_discovery():
    """Получить Discovery SKV."""
    return json.loads(req.urlopen(f"{SKV_URL}/.well-known/skv").read())

def get_projects():
    """Получить проекты директора."""
    try:
        resp = req.urlopen(f"{SKV_URL}/api/user/{DIRECTOR}/project/SKV/memory")
        return json.loads(resp.read())
    except:
        return {"projects": [], "count": 0}

def create_task(title, spec, assigned_to="lead_architect_01"):
    """Создать кубик задачи в SKV."""
    cube = {
        "title": title,
        "type": "project_anketa",
        "keywords": ["bureau", "task"],
        "memory_index": {
            "project": "SKV Design Bureau",
            "session_number": 1,
            "key_outcome": spec[:80]
        },
        "cubes": [{
            "cube_id": f"task_{title.lower().replace(' ', '_')[:30]}",
            "title": title,
            "rules": [spec],
            "trigger_intent": ["bureau", "task"]
        }],
        "persona": {"user_id": DIRECTOR, "traits": ["director"], "history_summary": "Bureau task"}
    }
    body = json.dumps(cube).encode()
    r = req.Request(f"{SKV_URL}/api/v1/entries", data=body,
        headers={"Content-Type": "application/json"})
    return json.loads(req.urlopen(r, timeout=30).read())

# === ГЛАВНЫЙ ЦИКЛ ===
if __name__ == "__main__":
    print("=" * 60)
    print("🏗️  SKV DESIGN BUREAU — CHIEF DESIGNER")
    print("=" * 60)
    
    # 1. Подключаемся к SKV
    discovery = get_discovery()
    print(f"✅ Connected to SKV v{discovery.get('version', '?')}")
    print(f"📦 {discovery.get('cubes_count', '?')} cubes available")
    
    # 2. Смотрим проекты директора
    projects = get_projects()
    print(f"📋 Director has {projects.get('count', 0)} projects")
    
    # 3. Ждём задачу
    print("\n" + "=" * 60)
    task = input("🎯 Director, what project should we build?\n> ")
    
    if not task.strip():
        print("❌ No task provided. Exiting.")
        sys.exit(0)
    
    # 4. Отправляем Главному конструктору (DeepSeek)
    prompt = f"""You are the Chief Designer of SKV Design Bureau.
    
Director: {DIRECTOR}
Current projects: {projects.get('count', 0)}

Director's request: {task}

Create a project skeleton:
1. PROJECT NAME
2. GOALS (3-5 bullet points)
3. REQUIRED ROLES (Lead Architects needed)
4. FIRST 3 TASKS (specific, actionable)

Follow SKV Constitution. Be concise and structured."""
    
    print("\n🧠 Chief Designer (DeepSeek) is thinking...\n")
    result = call_ai("deepseek/deepseek-chat", prompt)
    print(result)
    
    # 5. Предложить создать первую задачу
    print("\n" + "=" * 60)
    create = input("\n📦 Create first task in SKV? (y/n): ")
    if create.lower() == 'y':
        task_title = input("Task title: ")
        task_spec = input("Task specification: ")
        resp = create_task(task_title, task_spec)
        print(f"✅ Task created: {resp.get('id', '?')}")
    
    print("\n✅ Bureau session complete.")

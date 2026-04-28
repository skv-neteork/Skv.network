#!/bin/bash
# Загрузка кубиков в SKV через API

API_URL="http://localhost:8000"
CUBS_FILE="/root/skv-core/skv_constitution.json"
COUNT=0

# Извлекаем кубики из JSON и отправляем каждый
python3 << 'PYEOF'
import json, urllib.request

with open("/root/skv-core/skv_constitution.json") as f:
    data = json.load(f)

for cube in data["cubes"]:
    body = json.dumps(cube).encode()
    req = urllib.request.Request(
        "http://localhost:8000/api/v1/entries",
        data=body,
        headers={"Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read())
        print(f"✅ {cube['cube_id']} → ID: {result['id']}")
    except Exception as e:
        print(f"❌ {cube['cube_id']} → {e}")

print("\nЗагрузка завершена.")
PYEOF

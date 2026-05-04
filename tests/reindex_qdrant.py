import json, urllib.request as req, time, subprocess

POLZA_KEY = "pza_K738KdM_Cm2HYltwAvCLi3Uw9n8U5Rfo"

# Получаем кубики через docker exec
result = subprocess.run(
    ['docker', 'exec', 'skv_postgres', 'psql', '-U', 'skv_user', '-d', 'skv_db', '-t', '-c',
     "SELECT json_agg(json_build_object('cube_id', cube_id, 'title', title, 'text', rules::text, 'type', type)) FROM cubes"],
    capture_output=True, text=True
)
cubes = json.loads(result.stdout.strip())
print(f"Total cubes: {len(cubes)}")

# Qdrant
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

qdrant = QdrantClient(host="127.0.0.1", port=6333)

# Пересоздаём коллекцию
try:
    qdrant.delete_collection("skv_rules_v2")
except:
    pass

qdrant.create_collection(
    collection_name="skv_rules_v2",
    vectors_config={"size": 1536, "distance": "Cosine"}
)
print("Collection recreated")

# Индексируем
batch_size = 50
for i in range(0, len(cubes), batch_size):
    batch = cubes[i:i+batch_size]
    texts = [f"{c['title']}: {c['text'][:200]}" for c in batch]
    
    emb_body = json.dumps({"model": "text-embedding-3-small", "input": texts}).encode()
    emb_req = req.Request("https://api.polza.ai/v1/embeddings", data=emb_body, headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"
    })
    emb_resp = json.loads(req.urlopen(emb_req, timeout=30).read())
    embeddings = [e["embedding"] for e in emb_resp["data"]]
    
    points = [PointStruct(id=c['cube_id'], vector=emb, payload=c) for c, emb in zip(batch, embeddings)]
    qdrant.upsert(collection_name="skv_rules_v2", points=points)
    
    print(f"  {min(i+batch_size, len(cubes))}/{len(cubes)}")
    time.sleep(0.5)

info = qdrant.get_collection("skv_rules_v2")
print(f"\nDone! {info.points_count} points in Qdrant")

import requests
r = requests.post(
    'http://localhost:8000/api/v7/experience/create',
    json={'event_id':'test','semantics_emb':[0.5]*218,'essence':'test','topics':[]},
    headers={'Authorization':'bad'}
)
print(r.status_code, r.text)

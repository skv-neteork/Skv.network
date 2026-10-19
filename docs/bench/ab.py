import json, sys, time, os, resource
sys.path.insert(0, "/app")
import numpy as np
from app import semantic as S
S.MODELS["mpnet"] = {"name": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2", "dim": 768,
                     "dir": "/data/skv/hnsw_mpnet", "table": "pvec_mpnet"}
tags = sys.argv[1].split(",")
convs = [int(x) for x in sys.argv[2].split(",")]
data = json.load(open("/tmp/ab768/locomo10.json"))
def windows(turns, n=300):
    out, ids, txt = [], [], ""
    for did, t in turns:
        ids.append(did); txt += t + "\n"
        if len(txt) >= n: out.append((ids, txt)); ids, txt = [], ""
    if ids: out.append((ids, txt))
    return out
res = {}
for tag in tags:
    t0 = time.time(); S.embed(["warm"], tag, threads=2); load = time.time() - t0
    t0 = time.time(); S.embed(["Где живёт сестра Мелани и как зовут её кота?"], tag, threads=2); lat = (time.time() - t0) * 1000
    hits = {1: 0, 5: 0, 10: 0}; nq = 0; emb_t = 0; nwin = 0
    for ci in convs:
        c = data[ci]["conversation"]; turns = []
        for k in sorted([k for k in c if k.startswith("session_") and not k.endswith("date_time")], key=lambda x: int(x.split("_")[1])):
            for tr in c[k]: turns.append((tr["dia_id"], f'{tr["speaker"]}: {tr["text"]}'))
        wins = windows(turns); nwin += len(wins)
        t0 = time.time(); V = S.embed([w[1] for w in wins], tag, threads=2, batch_size=16); emb_t += time.time() - t0
        qa = [q for q in data[ci]["qa"] if q.get("category") != 5 and q.get("evidence")]
        Q = S.embed([q["question"] for q in qa], tag, threads=2, batch_size=16)
        sims = Q @ V.T
        for q, s in zip(qa, sims):
            ev = set(e.strip() for e in q["evidence"]); order = np.argsort(-s)
            for k in hits:
                got = set(); [got.update(wins[i][0]) for i in order[:k]]
                hits[k] += bool(ev & got)
            nq += 1
    res[tag] = {"q": nq, **{f"hit@{k}": round(v / nq, 3) for k, v in hits.items()},
                "load_s": round(load, 1), "query_ms": round(lat), "ms_per_window": round(emb_t * 1000 / nwin, 1),
                "maxrss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024}
    print(tag, res[tag], flush=True)
json.dump(res, open(f"/tmp/ab768/locomo_{'_'.join(tags)}.json", "w"))

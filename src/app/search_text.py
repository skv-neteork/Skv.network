"""/api/v7/search without a valid 768-d query_vector used to crash the worker (malloc in HNSW -> 502).
Text queries now go through the same semantic + keyword (RRF) path as /memory."""
def text_search(uid, query, top_k=20):
    from app import semantic as _sem
    sem = []
    try:
        sem, _v = _sem.semantic_events(uid, query, k=max(top_k, 20))
        sem = [(e, s) for e, s in sem if e.startswith(uid + "::")]
    except Exception as e:
        print(f"[search_text] semantic skipped: {e}", flush=True)
    fts = _sem.fts_ranked(uid, query, limit=30)
    fused = _sem.rrf(sem, fts)[:top_k]
    from app.recall_polish import _rows, clean, clip
    rows = _rows(uid, [e for e, _ in fused])
    out = []
    for e, sc in fused:
        r = rows.get(e)
        if not r:
            continue
        out.append({"event_id": e, "score": float(round(sc, 5)), "source": "personal",
                    "summary": clip(clean(r["raw"]), 300), "metadata": {"time_str": r.get("time_str")}})
    return out

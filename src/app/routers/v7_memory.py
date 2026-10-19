"""SKV v7 API: memory: recall (/memory), remember, events, shelves, search, deep recall, forget, calendar.
Split from v7_router.py with behavior unchanged; shared helpers and state come from v7_core."""
from app.routers import v7_core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith("__")})

@router.post("/vectors/process")
async def trigger_vectorization(request: Request):
    """Owner-only: embed any events still missing a vector (same path as the 60s batch)."""
    if not _is_owner(_request_user(request)):
        raise HTTPException(status_code=403, detail="owner only")
    from app import account_memory as _am, semantic as _sem
    def _run():
        with _am._batch_lock:
            return _sem.build_pending_all(force=True)
    count = await asyncio.to_thread(_run)
    return {"status": "ok", "model": _sem.active_tag(), "vectors_created": count}

@router.post("/cache/clear")
async def clear_search_cache(buffer: ChronoBufferV77Ultimate = Depends(get_memory_buffer)):
    """Clear search cache and reload buffer"""
    global _search_cache
    with _cache_lock:
        _search_cache.clear()
    
    # Reload buffer from disk
    buffer.persistence.load()
    
    return {
        "status": "ok",
        "message": "Cache cleared and buffer reloaded",
        "personal_active": int(np.sum(buffer.personal_active_mask[:buffer.personal_current_size])),
        "shared_active": int(np.sum(buffer.shared_active_mask[:buffer.shared_current_size]))
    }


@router.post("/memory")
async def guardian_l1_memory(req: MemoryRequest, buffer: ChronoBufferV77Ultimate = Depends(get_memory_buffer), authorization: str = Header(None)):
    try:   # lazy schema migration for accounts created before shelves (kind/source/project)
        from app import shelves as _shm
        _shm.ensure_user_db(req.user_id)
    except Exception as _e:
        print(f"[shelves] ensure skipped: {_e}", flush=True)
    # Извлекаем user_id из токена
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
        try:
            import sqlite3 as _sq
            _conn = _sq.connect(SHARED_DB)
            _cur = _conn.cursor()
            _cur.execute(_ak.SQL_USER, _ak.args(token))
            _row = _cur.fetchone()
            _conn.close()
            if _row:
                req.user_id = _row[0]
        except:
            pass
        token = authorization.replace("Bearer ", "")
        try:
            import sqlite3 as _sq
            _conn = _sq.connect(SHARED_DB)
            _cur = _conn.cursor()
            _cur.execute(_ak.SQL_USER, _ak.args(token))
            _row = _cur.fetchone()
            if _row:
                req.user_id = _row[0]
            _conn.close()
        except:
            pass
    if not req.user_id or not req.user_id.strip():
        raise HTTPException(status_code=422, detail="user_id cannot be empty")
    check_rate_limit(req.user_id)
    from app import memory_v2 as _mv2
    _view = ((req.view or _mv2.config().get("default_view", "legacy")) if _mv2.enabled() else "legacy").lower()
    if _view not in ("legacy", "agent", "debug"):
        _view = "legacy"
    _no_bump = bool(req.probe) or (_view == "agent" and not req.interact)
    if _no_bump:
        step = _mv2.peek_step(req.user_id)
    else:
        try:
            from app.account_memory import next_step
            step = next_step(req.user_id)
        except Exception:
            step = req.step
    duty_error = ""
    try:
        import sqlite3 as _duty
        prev = step - 1
        if prev > 0 and not _no_bump:
            conn = _duty.connect(SHARED_DB)
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS agent_duty (id INTEGER PRIMARY KEY, user_id TEXT, step INTEGER, duty TEXT, reason TEXT, created_at TEXT)")
            rows = cur.execute("SELECT duty FROM agent_duty WHERE user_id=? AND step=?", (req.user_id, prev)).fetchall()
            done = {r[0] for r in rows}
            missed = []
            if "saved" not in done:
                missed.append("the turn was not saved with remember")
            try:
                from app import cubes_v2 as _cv2
                _cv2.ensure(conn)
                missed += _cv2.duty_errors(conn, req.user_id, step)
                conn.commit()
            except Exception as _e:
                print(f"[cubes_v2] duty check skipped: {_e}", flush=True)
            conn.close()
            if missed:
                duty_error = "ERROR: previous step " + str(prev) + " was not closed. " + "; ".join(missed) + "."
    except Exception:
        duty_error = ""
    print(f'DEBUG query_text={repr(req.query_text)}', flush=True)
    from app import semantic as _sem
    _sem_tag = _sem.active_tag()
    _sem_vec = None
    if req.query_text and _sem_tag != "bge":
        q_vec = None
    elif req.query_text:
        from app.routers.v4_middleware import get_embedding_cached
        full_emb = get_embedding_cached(req.query_text)
        full_list = full_emb if isinstance(full_emb, list) else full_emb.tolist()
        q_vec = np.zeros(768, dtype=np.float32)
        q_vec[:768] = full_list[:768]
    elif req.query_vector:
        q_vec = np.array(req.query_vector, dtype=np.float32)
    else:
        q_vec = np.zeros(768, dtype=np.float32)
    memory_text = ""
    has_cubes = False
    raw_results = []
    _fts_ranked = []
    try:
        # v7.8: pass layer_weights for dynamic masks
        lw = req.layer_weights if hasattr(req, 'layer_weights') else None
        # Try VectorRouter (HNSW) first, fallback to _cached_search
        if _sem_tag != "bge" and req.query_text:
            hnsw_results, _sem_vec = _sem.semantic_events(req.user_id, req.query_text, k=max(req.top_k * 3, 20))
            hnsw_results = [(e, sc) for e, sc in hnsw_results if e.startswith(f"{req.user_id}::")]
        else:
            hnsw_results = GLOBAL_VECTOR_ROUTER.search(req.user_id.replace("@", "").replace(".", ""), q_vec, top_k=req.top_k)
        raw_results = []
        if hnsw_results:
            raw_results = [{"event_id": eid, "score": score, "source": "personal"} for eid, score in hnsw_results]
        if hnsw_results:
            raw_results = [{"event_id": eid, "score": score, "source": "personal"} for eid, score in hnsw_results]
            
            # FTS5 boost using focus_words from agent

        elif q_vec is not None:
            raw_results = _cached_search(buffer, q_vec, req.user_id, req.hops, req.top_k, layer_weights=lw)
        
        if req.query_text and _sem.fusion_mode() == "rrf":
            # Reciprocal Rank Fusion (k=60) of semantic HNSW + bm25 FTS5; FTS-only hits included
            _fts_ranked = _sem.fts_ranked(req.user_id, req.query_text, limit=30)
            _fused = _sem.rrf([(r["event_id"], r["score"]) for r in raw_results], _fts_ranked)
            _sem_scores = {r["event_id"]: r["score"] for r in raw_results}
            raw_results = [{"event_id": e, "score": round(sc, 5), "semantic": _sem_scores.get(e), "source": "personal"}
                           for e, sc in _fused[:max(req.top_k * 2, 10)]]
            # newer fact on the same subject ranks above the older one
            try:
                _order, _sup = _sem.supersede(req.user_id, [r["event_id"] for r in raw_results])
                _by_id = {r["event_id"]: r for r in raw_results}
                raw_results = [_by_id[i] for i in _order if i in _by_id]
                for _old, _new in _sup.items():
                    if _old in _by_id:
                        _by_id[_old]["superseded_by"] = _new
            except Exception as _e:
                print(f"[semantic] supersede skipped: {_e}", flush=True)
        if getattr(req, "kind", None) or getattr(req, "source", None) or getattr(req, "project", None):
            from app import shelves as _sh
            _ok = _sh.allowed(req.user_id, [r["event_id"] for r in raw_results] + [e for e, _ in _fts_ranked], req.kind, req.source, req.project)
            raw_results = [r for r in raw_results if r["event_id"] in _ok]
            _fts_ranked = [x for x in _fts_ranked if x[0] in _ok]
        # HYBRID: Multi-word FTS5 boost (legacy)
        if req.query_text and raw_results and _sem.fusion_mode() != "rrf":
            try:
                import sqlite3 as sq
                db_name = req.user_id.replace('@', '').replace('.', '')
                fts_conn = sq.connect(f'/data/skv/metadata_store/{db_name}.db')
                fts_cur = fts_conn.cursor()
                all_words = [w for w in req.query_text.split() if len(w) > 3]
                if all_words:
                    fts_matches = {}
                    for word in all_words:
                        fts_cur.execute('SELECT event_id FROM events_fts WHERE events_fts MATCH ?', (word,))
                        for (eid,) in fts_cur.fetchall():
                            fts_matches[eid] = fts_matches.get(eid, 0) + 1
                    fts_conn.close()
                    if fts_matches:
                        for r in raw_results:
                            eid = r.get('event_id')
                            if eid in fts_matches:
                                word_count = fts_matches[eid]
                                                                # Name boost: uppercase words = 0.5, lowercase = 0.2
                                name_boost = 0
                                word_boost = 0
                                for word in all_words:
                                    if word[0].isupper():
                                        name_boost += 0.5
                                    else:
                                        word_boost += 0.2
                                r['score'] = r.get('score', 0) + name_boost + word_boost
                        raw_results.sort(key=lambda x: -x.get('score', 0))
            except:
                pass
        
        if raw_results:
            filtered_dicts = []
            candidate_ids = []
            for r in raw_results:
                event_id = r["event_id"]
                score = r["score"]
                if event_id.startswith("CUBE_"):
                    source = "core"
                elif event_id in buffer.shared_id_to_idx:
                    source = "shared"
                else:
                    source = "personal"
                    if not event_id.startswith(f"{req.user_id}::"):
                        continue
                candidate_ids.append(event_id)
                filtered_dicts.append({"event_id": event_id, "score": score, "source": source})
            metadata_map = metadata_store.batch_get_metadata(req.user_id, candidate_ids)
            for r in filtered_dicts:
                r["metadata"] = metadata_map.get(r["event_id"], {})
            # Enhanced output: top-1 full text, rest essence
            memory_parts_v7 = []
            for i, r in enumerate(filtered_dicts[:5]):
                meta = r.get("metadata", {})
                eid = r.get("event_id", "?")
                score = r.get("score", 0)
                links = meta.get('links_json', '')
                link_str = ""
                if links and links.strip() and links != '[]':
                    try:
                        links_data = json.loads(links) if isinstance(links, str) else links
                        if isinstance(links_data, dict):
                            link_str = " | 🔗 " + ", ".join(list(links_data.keys())[:3])
                        elif isinstance(links_data, list):
                            link_str = " | 🔗 " + ", ".join([str(l)[:30] for l in links_data[:3]])
                    except:
                        pass
                
                if i == 0:
                    raw = meta.get('raw_dialogue', meta.get('essence', ''))
                    memory_parts_v7.append(f"=== TOP MATCH (Score: {score:.2f}) ===\nID: {eid}{link_str}\n{str(raw)[:3000]}")
                else:
                    memory_parts_v7.append(f"ID: {eid}{link_str} | Score: {score:.2f} | {str(meta.get('essence', ''))[:500]}")
            memory_text = "\n".join(memory_parts_v7)
            has_cubes = len(filtered_dicts) > 0
    except Exception:
        memory_text = "=== ПАМЯТЬ SKV: совпадений не найдено ===\n"
    
    # Load constitutional cubes from SQLite (shared_master.db)
    constitution_cube_ids = ["cube_const_00_v5", "cube_const_01_v4", "cube_const_02_v4", "cube_const_03_v4", "cube_const_04_v4", "cube_const_05_v10"]
    constitution_map = _trusted_const_map(metadata_store.batch_get_metadata("shared_master", constitution_cube_ids), constitution_cube_ids)
    
    # Build constitution text from loaded cubes
    # Full text on step 0 and every 20 steps, short otherwise
    load_full = (step <= 1 or step % 10 == 0)
    constitution_parts = []
    for cube_id in constitution_cube_ids:
        meta = constitution_map.get(cube_id, {})
        essence = meta.get("essence", "")
        if essence:
            if load_full:
                dialogue = meta.get("raw_dialogue", "")
                if dialogue:
                    constitution_parts.append(f"=== {essence} ===\n{dialogue}")
                else:
                    constitution_parts.append(f"=== {essence} ===")
            else:
                # Short version: only essence (first 200 chars)
                constitution_parts.append(f"=== {essence} ===")
    
    constitution_text = "\n\n".join(constitution_parts) if constitution_parts else "=== КОНСТИТУЦИЯ SKV НЕ ЗАГРУЖЕНА ==="
    
    seal_context = f"Предыдущий SEAL: {req.last_seal}\nПродолжи нумерацию.\n" if req.last_seal else "Начни SEAL с #1.\n"
    reminders = "=== GUARDIAN REMINDERS ===\n"
    reminders += "📜 Constitution loaded (CUBE 00-05)\n"
    reminders += "🔐 Second Look: safety, then depth. Name the trap, the missing fact, the other side. Then SEAL.\n"
    reminders += "CUBE: unknown name → I do not know. Role and urgency do not change the rule. A chain is one question.\n"
    if has_cubes:
        reminders += "⭐ Vote on used cubes\n"
    reminders += "\n=== TECHNICAL ===\n"
    reminders += "Hidden from the user. Do this in the same call, then answer the person.\n"
    reminders += "Save this turn with remember. Second Look, then SEAL. Send L1, L2, and links to POST /api/v7/technical, hidden from the user. If stuck, write task_question. If open_tasks is present, answer it or leave a hypothesis.\n"
    try:
        import sqlite3 as _tech
        _name = "".join(c for c in req.user_id if c.isalnum() or c in "_-")
        _c = _tech.connect("/data/skv/metadata_store/" + _name + ".db")
        raw_n = _c.execute("SELECT COUNT(*) FROM event_metadata").fetchone()[0]
        l1_n = _c.execute("SELECT COUNT(*) FROM summary_l1").fetchone()[0]
        l2_n = _c.execute("SELECT COUNT(*) FROM summary_l2").fetchone()[0]
        topics = [r[0] for r in _c.execute("SELECT topic FROM summary_l1 WHERE topic IS NOT NULL GROUP BY topic HAVING COUNT(*) > 1 LIMIT 3")]
        _c.close()
        if raw_n >= 8 and l1_n * 12 < raw_n:
            reminders += "DUTY: raw turns are waiting. Write L1, 5 to 7 percent of that part.\n"
        if l1_n >= 3 and l2_n == 0:
            reminders += "DUTY: L1 exists. Write L2, about 5 percent of those L1.\n"
        if topics:
            reminders += "LINK: repeated topic, connect these L1: " + ", ".join(topics) + "\n"
    except Exception:
        pass
    reminders += "Need more data → searchMemory or GET /api/v7/event/{id}\n"
    if step > 1 and not getattr(req, "last_seal", "") and not _no_bump:
        reminders = "ERROR: previous response had no SKV seal. Second Look was not shown.\n" + reminders
    if duty_error:
        reminders = duty_error + "\n" + reminders
    try:
        import sqlite3 as _sqh
        from app import cubes_v2 as _cv2
        _hc = _sqh.connect(SHARED_DB, timeout=30)
        _cv2.ensure(_hc)
        for _h in _cv2.duty_hints(_hc, req.user_id):
            reminders += _h + "\n"
        _hc.commit(); _hc.close()
    except Exception as _e:
        print(f"[cubes_v2] hints skipped: {_e}", flush=True)

    # Memory Pyramid via single source (full at step=0, short at step>0)
    memory_map_text = build_memory_map(req.user_id, step=step)

    # Smart assembly: full constitution+map at step 0 / every 20; short map always when step>0
    if step <= 1 or step % 10 == 0:
        prompt_text = f"{memory_text}\n\n{memory_map_text}\n{constitution_text}\n\n{seal_context}\n{reminders}"
    else:
        # Short: search hits + compact Memory Map (L2+Critical+hint) + reminders
        prompt_text = f"{memory_text}\n\n{memory_map_text}\n\n{seal_context}\n{reminders}"
    # Раздельная выдача
    vector_top = raw_results[:10] if raw_results else []
    fts_top = []
    focus = getattr(req, 'focus_words', None) or []
    if not focus and getattr(req, 'query_text', None):
        focus = [w.strip(".,!?;:\"'") for w in req.query_text.split() if len(w) > 3][:8]
    if focus:
        try:
            import sqlite3 as sq
            db_name = req.user_id.replace('@', '').replace('.', '')
            fts_conn = sq.connect(f'/data/skv/metadata_store/{db_name}.db')
            fts_cur = fts_conn.cursor()
            phrase = " ".join(focus)
            raw_phrase = (getattr(req, "query_text", "") or "").strip()
            if len(raw_phrase.split()) > 2:
                fts_cur.execute("SELECT event_id FROM event_metadata WHERE raw_dialogue LIKE ? LIMIT 3", ("%" + raw_phrase + "%",))
                for (eid,) in fts_cur.fetchall():
                    if eid not in [f.get("event_id") for f in fts_top]:
                        fts_top.append({"event_id": eid, "matched_word": raw_phrase, "source": "phrase"})
            if len(focus) > 1 and not fts_top:
                try:
                    fts_cur.execute('SELECT event_id FROM events_fts WHERE events_fts MATCH ? LIMIT 5', ('"' + phrase + '"',))
                    for (eid,) in fts_cur.fetchall():
                        if eid not in [f.get('event_id') for f in fts_top]:
                            fts_top.append({'event_id': eid, 'matched_word': phrase, 'source': 'phrase'})
                except Exception:
                    pass
            if not fts_top and _fts_ranked:
                for eid, _sc in _fts_ranked[:10]:
                    fts_top.append({'event_id': eid, 'matched_word': '', 'source': 'fts', 'bm25': round(_sc, 3)})
            if not fts_top:
                for word in focus:
                    fts_cur.execute('SELECT event_id FROM events_fts WHERE events_fts MATCH ? LIMIT 10', (word,))
                    for (eid,) in fts_cur.fetchall():
                        if eid not in [f.get('event_id') for f in fts_top]:
                            fts_top.append({'event_id': eid, 'matched_word': word, 'source': 'fts'})
            fts_conn.close()
        except:
            pass
    vector_ids = {v.get('event_id') for v in vector_top}
    fts_ids = {f.get('event_id') for f in fts_top}
    intersection = [v for v in vector_top if v.get('event_id') in fts_ids]
    
    # Full text for best results
    def _full_text(eid):
        try:
            import sqlite3 as sq
            db_name = req.user_id.replace('@', '').replace('.', '')
            conn = sq.connect(f'/data/skv/metadata_store/{db_name}.db')
            cur = conn.cursor()
            cur.execute('SELECT raw_dialogue FROM event_metadata WHERE event_id = ?', (eid,))
            row = cur.fetchone()
            conn.close()
            return row[0][:1000] if row and row[0] else ''
        except:
            return ''
    
    common = {"call", "such", "time", "best", "girl", "revolution", "this", "that", "with", "from", "have", "were", "been", "your", "killed", "who", "what", "where", "when", "book"}
    no_exact = False
    phrases = [f for f in fts_top if f.get("source") == "phrase"]
    if phrases:
        fts_top = phrases
    else:
        strong = [f for f in fts_top if (f.get("matched_word") or "").lower() not in common]
        fts_top = strong
        if not fts_top and vector_top:
            vector_top = vector_top
    if not phrases and vector_top:
        exact_ids = {f.get("event_id") for f in fts_top}
        vector_top = [v for v in vector_top if v.get("event_id") not in exact_ids] + [v for v in vector_top if v.get("event_id") in exact_ids]
        vector_top = list(reversed(vector_top)) if False else vector_top
        # meaning outranks a lone common word; common words already removed
        if not fts_top:
            pass
    try:
        import sqlite3 as _sq
        db_name = req.user_id.replace("@", "").replace(".", "")
        word = max([w for w in (req.query_text or "").split() if len(w) > 3], key=len, default="")
        if word:
            conn = _sq.connect(f"/data/skv/metadata_store/{db_name}.db")
            rows = conn.execute("SELECT topic, summary_text, created_at FROM summary_l1 WHERE summary_text LIKE ? ORDER BY created_at ASC LIMIT 8", ("%" + word + "%",)).fetchall()
            conn.close()
            if rows:
                lines = ["=== PAST SUMMARIES ==="]
                for topic, summary, created in rows:
                    lines.append(f"[{created}] {topic}: {summary}")
                memory_map_text = "\n".join(lines) + "\n\n" + memory_map_text
    except Exception:
        pass
    try:
        if _sem_vec is not None:
            import sqlite3 as _sq
            hits = [h for h in _sem.search_l1(req.user_id, _sem_vec, k=3) if h[1] >= 0.45]
            if hits:
                conn = _sq.connect("/data/skv/metadata_store/" + _sem.account_name(req.user_id) + ".db")
                lines = ["=== RELATED SUMMARIES (semantic) ==="]
                for hid, sc in hits:
                    row = conn.execute("SELECT topic, summary_text, created_at FROM summary_l1 WHERE rowid=?", (int(hid.split(":")[1]),)).fetchone()
                    if row and (row[1] or "") not in memory_map_text:
                        lines.append(f"[{row[2]}] {row[0]}: {row[1]}")
                conn.close()
                if len(lines) > 1:
                    memory_map_text = "\n".join(lines) + "\n\n" + memory_map_text
    except Exception as _e:
        print(f"[semantic] l1 skipped: {_e}", flush=True)
    if getattr(req, "kind", None) or getattr(req, "source", None) or getattr(req, "project", None):
        try:
            from app import shelves as _sh
            _ok = _sh.allowed(req.user_id, [f.get("event_id") for f in fts_top] + [v.get("event_id") for v in vector_top], req.kind, req.source, req.project)
            fts_top = [f for f in fts_top if f.get("event_id") in _ok]
            vector_top = [v for v in vector_top if v.get("event_id") in _ok]
            intersection = [v for v in intersection if v.get("event_id") in _ok]
        except Exception as _e:
            print(f"[shelves] filter skipped: {_e}", flush=True)
    if _sem_vec is not None and len(fts_top) > 1:
        try:
            _order, _sup = _sem.supersede(req.user_id, [f.get("event_id") for f in fts_top])
            _by_id = {f.get("event_id"): f for f in fts_top}
            fts_top = [_by_id[i] for i in _order if i in _by_id]
            for _old, _new in _sup.items():
                if _old in _by_id:
                    _by_id[_old]["superseded_by"] = _new
        except Exception as _e:
            print(f"[semantic] fts supersede skipped: {_e}", flush=True)
    best_vec = vector_top[0] if vector_top else {}
    if best_vec: best_vec['full_text'] = _full_text(best_vec.get('event_id', ''))
    best_fts = fts_top[0] if fts_top else {}
    if best_fts: best_fts['full_text'] = _full_text(best_fts.get('event_id', ''))
    best_int = intersection[0] if intersection else {}
    if best_int: best_int['full_text'] = _full_text(best_int.get('event_id', ''))
    exact = best_int or best_fts
    if not phrases and not fts_top:
        no_exact = True
        exact = {}
    words = [w.strip("?.!,") for w in (req.query_text or "").lower().split() if len(w) > 4]
    key = max(words, key=len).replace("-", "") if words else ""
    def _has(eid):
        return key and key in (_full_text(eid) or "").lower().replace("-", "").replace(" ", "")
    if exact and exact.get("event_id") and not _has(exact.get("event_id")):
        no_exact = True
        exact = {}
    if key and not (exact and exact.get("event_id")):
        for item in (fts_top[:8] + vector_top[:8]):
            if _has(item.get("event_id")):
                exact = item
                no_exact = False
                break
    if exact and exact.get('event_id'):
        prompt_text = "=== EXACT MATCH ===\nID: " + exact.get('event_id') + "\n" + _full_text(exact.get('event_id')) + "\n\n" + prompt_text
        memory_text = "=== EXACT MATCH ===\nID: " + exact.get('event_id') + "\n" + _full_text(exact.get('event_id')) + "\n\n" + memory_text
    fragments = []
    side = vector_top[:5] if no_exact else []
    for item in ([exact] if exact and exact.get('event_id') else []) + fts_top[:5] + vector_top[:5]:
        eid = item.get('event_id')
        if not eid or any(f.get('event_id') == eid for f in fragments):
            continue
        fragments.append({"event_id": eid, "source": item.get('source', 'exact'), "score": item.get('score'), "text": _full_text(eid)})
    def _stamp(f):
        eid = f.get("event_id") or ""
        tail = eid.rsplit("_", 1)[-1]
        return int(tail) if "remember_" in eid and tail.isdigit() else 0
    phrases = [f for f in fragments if f.get("source") == "phrase"]
    phrases.sort(key=_stamp, reverse=True)
    rest = [f for f in fragments if f.get("source") != "phrase"]
    fragments = phrases + rest
    latest = fragments[:1]
    previous = [{"event_id": f.get("event_id"), "source": f.get("source"), "open": "/api/v7/event/" + f.get("event_id", ""), "preview": (f.get("text") or "")[:160]} for f in fragments[1:6]]
    if no_exact:
        previous = [{"event_id": f.get("event_id"), "source": "nearby", "note": "no exact match", "open": "/api/v7/event/" + f.get("event_id", ""), "preview": (f.get("text") or "")[:160]} for f in fragments[:5]]
        fragments = []
    else:
        fragments = latest
    fragment_links = []
    try:
        import sqlite3 as _sq
        if fragments:
            _db = "/data/skv/metadata_store/" + "".join(c for c in req.user_id if c.isalnum() or c in "_-") + ".db"
            _c = _sq.connect(_db)
            fragment_links = [{"src": r[0], "dst": r[1], "kind": r[2], "open": "/api/v7/event/" + r[1]} for r in _c.execute("SELECT src, dst, kind FROM event_links WHERE src=? OR dst=? LIMIT 6", (fragments[0]["event_id"], fragments[0]["event_id"]))]
            _c.close()
    except Exception:
        fragment_links = []
    
    shared_cubes = []
    try:
        import sqlite3 as _sq
        words = [w for w in (getattr(req, "query_text", "") or "").split() if len(w) >= 3][:4]
        if words:
            _c = _sq.connect(SHARED_DB)
            _cur = _c.cursor()
            topic = None
            stems = []
            for word in words:
                stems.append(word)
                for end in ("ed", "ing", "es", "s"):
                    if word.endswith(end) and len(word) - len(end) >= 3:
                        stems.append(word[:-len(end)])
            for word in sorted(set(stems), key=len, reverse=True):
                hit = _cur.execute("SELECT subject_action_object FROM cubes_new WHERE (subject_action_object=? OR subject_action_object LIKE ?) AND cube_id NOT LIKE 'cube_const_%' AND status NOT IN ('deprecated','archived','removed','quarantine') AND COALESCE(kind,'moment') NOT IN ('help_request','project','project_node') LIMIT 1", (word, "%" + word + "%")).fetchone()
                if hit:
                    topic = hit[0]
                    break
            if hit:
                topic = hit[0]
            if topic:
                from app import cubes_v2 as _cv2
                _cv2.ensure(_c)
                _vs = {}
                try:
                    if _sem_vec is not None:
                        _vs = {cid: sc for cid, sc in _sem.search_cubes(_sem_vec, k=30)}
                except Exception:
                    _vs = {}
                shared_cubes = _cv2.select_pack(_c, topic, req.user_id, step, record=not _no_bump, query=req.query_text or "", vec_scores=_vs)
            if not shared_cubes and _sem_vec is not None:
                for cid, sc in _sem.search_cubes(_sem_vec, k=3):
                    if sc < 0.5:
                        continue
                    row = _cur.execute("SELECT cube_id, essence, subject_action_object, rules_markdown FROM cubes_new WHERE cube_id=? AND status NOT IN ('deprecated','archived','removed','quarantine') AND COALESCE(kind,'moment') NOT IN ('help_request','project','project_node')", (cid,)).fetchone()
                    if row:
                        shared_cubes.append({"cube_id": row[0], "topic": row[2], "essence": row[1], "rules": (row[3] or "")[:500], "shared": True, "note": "semantic", "score": round(sc, 3)})
            if not shared_cubes:
                like = "%" + max(words, key=len) + "%"
                for row in _cur.execute("SELECT cube_id, essence, subject_action_object, rules_markdown FROM cubes_new WHERE status NOT IN ('deprecated','archived','removed','quarantine') AND COALESCE(kind,'moment') NOT IN ('help_request','project','project_node') AND cube_id NOT LIKE 'cube_const_%' AND (subject_action_object LIKE ? OR essence LIKE ?) LIMIT 3", (like, like)):
                    shared_cubes.append({"cube_id": row[0], "topic": row[2], "essence": row[1], "rules": (row[3] or "")[:500], "shared": True, "note": "matched"})
            _c.commit()
            _c.close()
    except Exception:
        shared_cubes = []
    open_tasks = []
    try:
        _tc = _sq.connect(SHARED_DB)
        _tc.execute("CREATE TABLE IF NOT EXISTS cube_tasks (task_id TEXT PRIMARY KEY, topic TEXT, question TEXT, tried TEXT, accept TEXT, status TEXT, created_by TEXT, created_at TEXT)")
        word = ""
        words = [w for w in (getattr(req, "query_text", "") or "").split() if len(w) > 3]
        if words:
            word = max(words, key=len)
        for row in _tc.execute("SELECT task_id, topic, question, tried, accept FROM cube_tasks WHERE status='open' AND (topic LIKE ? OR question LIKE ?) LIMIT 1", ("%"+word+"%", "%"+word+"%")):
            open_tasks.append({"task_id": row[0], "topic": row[1], "question": row[2], "tried": row[3], "accept": row[4], "note": "open task, answer or leave a hypothesis"})
        _tc.close()
    except Exception:
        open_tasks = []
    help_hits = []
    try:
        import sqlite3 as _sqhh
        from app import cubes_v2 as _cv2
        _hh = _sqhh.connect(SHARED_DB, timeout=30)
        _cv2.ensure(_hh)
        _topic = (shared_cubes[0].get("topic") if shared_cubes else "") or ""
        help_hits = _cv2.help_hits(_hh, req.user_id, _topic, mark=not _no_bump)
        _hh.commit(); _hh.close()
    except Exception as _e:
        print(f"[cubes_v2] help_hits skipped: {_e}", flush=True)
    due = []
    try:
        import datetime, re
        months = {"января":1,"февраля":2,"марта":3,"апреля":4,"мая":5,"июня":6,"июля":7,"августа":8,"сентября":9,"октября":10,"ноября":11,"декабря":12}
        today = datetime.date.today()
        name = "".join(c for c in req.user_id if c.isalnum() or c in "_-")
        dc = _sq.connect(f"/data/skv/metadata_store/{name}.db")
        dc.execute("CREATE TABLE IF NOT EXISTS due_cache (day TEXT PRIMARY KEY, payload TEXT)")
        cached = dc.execute("SELECT payload FROM due_cache WHERE day=?", (today.isoformat(),)).fetchone()
        if cached:
            due = __import__("json").loads(cached[0])
            dc.close()
            raise StopIteration
        rows = dc.execute("SELECT event_id, raw_dialogue FROM event_metadata WHERE raw_dialogue LIKE ? LIMIT 200", ("%>>>%",)).fetchall()
        for eid, text in rows:
            found = None
            m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text or "")
            if m:
                found = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            else:
                m = re.search(r"(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)", text or "", re.I)
                if m:
                    found = datetime.date(today.year, months[m.group(2).lower()], int(m.group(1)))
            if not found:
                continue
            delta = (found - today).days
            if delta < 0 and found.month == today.month:
                found = found.replace(year=today.year+1)
                delta = (found - today).days
            if 0 <= delta <= 7:
                due.append({"event_id": eid, "in_days": delta, "note": "через "+str(delta)+" дней" if delta else "сегодня"})
        dc.execute("INSERT OR REPLACE INTO due_cache (day, payload) VALUES (?,?)", (today.isoformat(), __import__("json").dumps(due, ensure_ascii=False)))
        dc.commit()
        dc.close()
    except StopIteration:
        pass
    except Exception:
        due = []
    agent_hint = "Center is fragments. If empty, do not invent: open previous.event_id or search again with a narrower name. Full text is GET /api/v7/event/{id}. Third look is POST /api/v7/memory/dig with query."
    span = 0
    try:
        import sqlite3 as _span
        name = "".join(c for c in req.user_id if c.isalnum() or c in "_-")
        key = "".join(ch for ch in (req.query_text or "").lower() if ch.isalnum())
        if len(key) > 4:
            span = sum(1 for body in _cached_scan(name, "norm") if key in body)
    except Exception:
        span = 0
    lens = {"windows": []}
    try:
        import sqlite3 as _lens
        name = "".join(c for c in req.user_id if c.isalnum() or c in "_-")
        conn = _lens.connect(f"/data/skv/metadata_store/{name}.db")
        raw_q = (req.query_text or "").lower()
        words = []
        for w in raw_q.replace("-", "").split():
            token = "".join(ch for ch in w if ch.isalnum())
            if len(token) >= 4 and token not in words:
                words.append(token)
        words = sorted(words, key=len, reverse=True)[:3]
        rows_c = _cached_scan(name, "grokexp")
        crits_c = _cached_scan(name, "crit")
        l2 = ""
        try:
            l2 = conn.execute("select map_json from summary_l2 order by last_updated desc limit 1").fetchone()[0] or ""
        except Exception:
            l2 = ""
        for word in words:
            hit = None
            for eid, raw, body in rows_c:
                if word and word in body:
                    hit = (eid, raw)
                    break
            if not hit:
                continue
            eid, raw = hit
            tail = (eid or "").rsplit("_", 1)[-1]
            around = []
            if tail.isdigit():
                n = int(tail)
                l1_range = conn.execute("select start_n, end_n from l1_span where ? between start_n and end_n", (n,)).fetchone()
                if l1_range:
                    near = conn.execute("select session_id, start_n, end_n, summary from l1_span order by start_n").fetchall()
                    before = [r for r in near if r[2] < l1_range[0]][-1:]
                    after = [r for r in near if r[1] > l1_range[1]][:1]
                    around = [{"l1": sid, "from": a, "to": b, "text": (summary or "")[:400]} for sid, a, b, summary in before+after]
            theme = l2[:400]
            if word and word in l2.lower().replace("-", "").replace(" ", ""):
                theme = l2[:800]
            important = []
            for cid, text, body in crits_c:
                if word and word in body:
                    important.append({"event_id": cid, "text": text[:200]})
            if lens["windows"] and word in lens["windows"][0]["word"]:
                continue
            before = around[:1]
            after = around[1:2]
            lens["windows"].append({"word": word, "center": {"event_id": eid, "text": (raw or "")[:800]}, "around": around, "l1_before": before, "l1_after": after, "map": theme, "important": important[:2]})
        conn.close()
    except Exception:
        pass
    _legacy = {"prompt_text": prompt_text, "memory": memory_text, "fragments": fragments, "previous": previous, "agent_hint": agent_hint, "span": span, "lens": lens, "links": fragment_links, "shared_cubes": shared_cubes, "shared_cubes_note": CUBES_DATA_MARKER if shared_cubes else "", "open_tasks": open_tasks, "help_hits": help_hits, "due": due, "constitution": constitution_text, "reminders": reminders, "duty_error": duty_error, "has_cubes": has_cubes, "step": step, "memory_map": memory_map_text, "vector_top10": vector_top[:10], "fts_top10": fts_top[:10], "intersection": intersection[:10], "best_vector": best_vec, "best_fts": best_fts, "best_intersection": best_int}
    if _view != "agent":
        return _mv2.mask_obj(_legacy)
    _ctx = {"step": step, "duty_error": duty_error, "fts_top": fts_top, "vector_top": vector_top, "raw_results": raw_results,
            "full_map": lambda: build_memory_map(req.user_id, step=0)}
    try:
        from app import memory_v2_windows as _mvw
        _ctx["first_pack"] = lambda b: _mvw.first_pack(req.user_id, b)
    except ImportError:
        pass
    try:
        from app import memory_v2_lens as _mvl
        if (req.query_text or req.focus_event_id) and _mv2.config().get("lens_v2", True):
            _ctx["lens_fn"] = lambda _b: _mvl.lens(req.user_id, req.query_text or "", raw_results=raw_results, budget=_b,
                                                   focus_event_id=req.focus_event_id, radius=req.radius, offset=req.lens_offset,
                                                   kind=req.kind, source=req.source, project=req.project)
    except ImportError:
        pass
    return _mv2.agent_view(req, _legacy, _ctx)

@router.post("/search", response_model=SearchResponse)
async def search_endpoint(req: SearchRequest, buffer: ChronoBufferV77Ultimate = Depends(get_memory_buffer)):
    q_vec = np.array(req.query_vector, dtype=np.float32)
    try:
        # v7.8: pass layer_weights for dynamic masks
        lw = req.layer_weights if hasattr(req, 'layer_weights') else None
        # Try VectorRouter (HNSW) first, fallback to _cached_search
        hnsw_results = GLOBAL_VECTOR_ROUTER.search(req.user_id.replace("@", "").replace(".", ""), q_vec, top_k=req.top_k)
        raw_results = []
        if hnsw_results:
            raw_results = [{"event_id": eid, "score": score, "source": "personal"} for eid, score in hnsw_results]
        if hnsw_results:
            raw_results = [{"event_id": eid, "score": score, "source": "personal"} for eid, score in hnsw_results]
            
            # FTS5 boost using focus_words from agent

        else:
            raw_results = _cached_search(buffer, q_vec, req.user_id, req.hops, req.top_k, layer_weights=lw)
        
        print(f'DEBUG HYBRID: query_text={bool(req.query_text)}, raw_results={bool(raw_results)}', flush=True)
        # HYBRID: Multi-word FTS5 boost (more matched words = higher boost)
        if req.query_text and raw_results:
            try:
                import sqlite3 as sq
                db_name = req.user_id.replace('@', '').replace('.', '')
                fts_conn = sq.connect(f'/data/skv/metadata_store/{db_name}.db')
                fts_cur = fts_conn.cursor()
                all_words = [w for w in req.query_text.split() if len(w) > 3]
                if all_words:
                    fts_matches = {}
                    for word in all_words:
                        fts_cur.execute('SELECT event_id FROM events_fts WHERE events_fts MATCH ?', (word,))
                        for (eid,) in fts_cur.fetchall():
                            fts_matches[eid] = fts_matches.get(eid, 0) + 1
                    fts_conn.close()
                    if fts_matches:
                        for r in raw_results:
                            eid = r.get('event_id')
                            if eid in fts_matches:
                                word_count = fts_matches[eid]
                                boost = 1.0 + (word_count * 0.5)
                                                                # Name boost: uppercase words = 0.5, lowercase = 0.2
                                name_boost = 0
                                word_boost = 0
                                for word in all_words:
                                    if word[0].isupper():
                                        name_boost += 0.5
                                    else:
                                        word_boost += 0.2
                                r['score'] = r.get('score', 0) + name_boost + word_boost
                        raw_results.sort(key=lambda x: -x.get('score', 0))
            except:
                pass
        
        if raw_results:
            event_ids = [r["event_id"] for r in raw_results]
            metadata_map = metadata_store.batch_get_metadata(req.user_id, event_ids)
            for r in raw_results:
                r["metadata"] = metadata_map.get(r["event_id"], {})
            # Separate by source
            personal = [r for r in raw_results if r.get("source") == "personal"]
            shared = [r for r in raw_results if r.get("source") == "shared"]
            core = [r for r in raw_results if r.get("source") == "core"]
            memory_text = ChronoCognitiveDecoder.decode_structured(personal, shared, core)
        else:
            memory_text = ""
        
        memory_map = ""
        if req.step == 0:
            memory_map = "\n=== YOUR MEMORY MAP ===\n"
            if buffer.personal_current_size > 0:
                memory_map += f"Personal sessions: {buffer.personal_current_size}\n"
            if buffer.shared_current_size > 0:
                memory_map += f"Shared knowledge cubes: {buffer.shared_current_size}\n"
            memory_map += "Use memory search to explore specific topics.\n"
        
        constitution_ids = ["cube_const_00_v5", "cube_const_01_v4", "cube_const_02_v4", "cube_const_03_v4", "cube_const_04_v4", "cube_const_05_v10"]
        const_map = _trusted_const_map(metadata_store.batch_get_metadata("shared_master", constitution_ids), constitution_ids)
        const_parts = []
        for cid in constitution_ids:
            meta = const_map.get(cid, {})
            if meta.get("raw_dialogue"):
                clean_name = cid.replace("cube_const_", "CUBE ").replace("_v4","").replace("_v5","")
                const_parts.append(f"=== {clean_name} ===\n{meta['raw_dialogue']}")
        constitution_text = "\n\n".join(const_parts)
        
        reminders = ""
        if req.step == 0:
            reminders += "Load all constitution cubes (CUBE 00-05)\n"
        if req.step > 0 and req.step % 5 == 0:
            reminders += "Save session to memory\n"
        if req.step > 0 and req.step % 15 == 0:
            reminders += "Create experience cube if important\n"
        if memory_text:
            reminders += "Leave feedback on used cubes\n"
        reminders += "Execute Second Look and put SEAL\n"
        
        seal_context = f"Previous SEAL: {req.last_seal}\nContinue numbering.\n" if req.last_seal else "Start SEAL with #1.\n"
        
        search_map = f"\n=== SEARCH MEMORY MAP ===\n{search_memory_map}\n" if search_memory_map else ""
        search_instruction = "=== SEARCH MEMORY FIRST ===\nBEFORE answering, check the memory below.\n\n"
        lens_text = ""
        try:
            keyrow = (_ak.internal_token(req.user_id),)
            if keyrow:
                lens_req = urlreq.Request("http://127.0.0.1:8000/api/v7/memory", data=json.dumps({"user_id": req.user_id, "query_text": req.message, "top_k": 2}).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer "+keyrow[0]})
                with urlreq.urlopen(lens_req, timeout=40) as lens_resp:
                    lens = json.loads(lens_resp.read().decode())
                bits = ["span="+str(lens.get("span"))]
                for w in (lens.get("lens") or {}).get("windows") or []:
                    bits.append(w.get("word","")+" center "+((w.get("center") or {}).get("event_id") or ""))
                    bits.append(((w.get("center") or {}).get("text") or "")[:600])
                lens_text = "\n".join(bits)
        except Exception:
            lens_text = ""

        opened = ""
        try:
            center = ""
            for line in lens_text.split("\n"):
                if "center " in line:
                    center = line.split("center ", 1)[1].strip()
                    break
            if center:
                keyrow = (_ak.internal_token(req.user_id),)
                headers = {"Authorization": "Bearer "+keyrow[0]} if keyrow else {}
                with urlreq.urlopen(urlreq.Request("http://127.0.0.1:8000/api/v7/event/"+center, headers=headers), timeout=20) as ev:
                    opened = ev.read().decode()[:1200]
        except Exception:
            opened = ""

        prompt = f"{guest_warning}{search_instruction}{lens_text}\n\nOPENED EVENT:\n{opened}\n\n{memory_text if memory_text else 'No relevant memory found.'}\n\nUser question: {req.message}\n\nFormat: TOOL: memory query=... or TOOL: event event_id=... or === ЗАКЛЮЧЕНИЕ ===. Do not conclude before one TOOL if the archive is wide."
        tools = [
            {"type": "function", "function": {"name": "memory", "description": "Search the user archive", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
            {"type": "function", "function": {"name": "dig", "description": "Scan the archive for a rare word", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
            {"type": "function", "function": {"name": "event", "description": "Open one event by id", "parameters": {"type": "object", "properties": {"event_id": {"type": "string"}}, "required": ["event_id"]}}},
            {"type": "function", "function": {"name": "sandbox", "description": "Run a short Python check", "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}}},
        ]
        polza_body = json.dumps({"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": prompt + " You may call memory, dig, event, or sandbox before answering."}], "tools": tools, "temperature": 0.3, "max_tokens": 1400}).encode()
        polza_key = os.environ.get("POLZA_KEY", "")
        r = urlreq.Request("https://api.polza.ai/v1/chat/completions", data=polza_body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {polza_key}"})
        with urlreq.urlopen(r, timeout=120) as resp:
            response_data = json.loads(resp.read().decode())
            message = response_data["choices"][0]["message"]
            
            # Handle tool calls
            tool_results = []
            if "tool_calls" in message:
                for tc in message["tool_calls"]:
                    name = tc["function"]["name"]
                    args = json.loads(tc["function"].get("arguments") or "{}")
                    if name in ("memory", "dig", "event", "sandbox"):
                        try:
                            if name == "memory":
                                url, payload = "http://127.0.0.1:8000/api/v7/memory", {"user_id": req.user_id, "query_text": args.get("query", ""), "top_k": 2}
                            elif name == "dig":
                                url, payload = "http://127.0.0.1:8000/api/v7/memory/dig", {"user_id": req.user_id, "query": args.get("query", "")}
                            elif name == "event":
                                url, payload = "http://127.0.0.1:8000/api/v7/event/" + args.get("event_id", ""), None
                            else:
                                url, payload = "http://127.0.0.1:8000/api/execute/code", {"code": args.get("code", ""), "user_id": req.user_id}
                            headers = {"Content-Type": "application/json"}
                            if name != "sandbox":
                                keyrow = (_ak.internal_token(req.user_id),)
                                if keyrow:
                                    headers["Authorization"] = "Bearer " + keyrow[0]
                            call = urlreq.Request(url, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
                            with urlreq.urlopen(call, timeout=40) as tool_resp:
                                tool_results.append({"tool": name, "result": tool_resp.read().decode()[:1500]})
                        except Exception as e:
                            tool_results.append({"tool": name, "error": str(e)})
                    if tc["function"]["name"] == "createFile":
                        try:
                            args = json.loads(tc["function"]["arguments"])
                            # Call our own API
                            create_req = urlreq.Request("http://127.0.0.1:8000/api/v7/tools/create-file",
                                data=json.dumps(args).encode(),
                                headers={"Content-Type": "application/json"})
                            with urlreq.urlopen(create_req, timeout=10) as create_resp:
                                file_result = json.loads(create_resp.read().decode())
                                tool_results.append({"tool": "createFile", "result": file_result})
                        except Exception as e:
                            tool_results.append({"tool": "createFile", "error": str(e)})
                
                # Send tool results back to AI
                if tool_results:
                    tool_msg = json.dumps(tool_results)
                    followup_body = json.dumps({
                        "model": "deepseek/deepseek-chat",
                        "messages": [
                            {"role": "user", "content": prompt},
                            {"role": "assistant", "tool_calls": message["tool_calls"]},
                            {"role": "tool", "content": tool_msg}
                        ],
                        "temperature": 0.3
                    }).encode()
                    followup_req = urlreq.Request("https://api.polza.ai/v1/chat/completions",
                        data=followup_body,
                        headers={"Content-Type": "application/json", "Authorization": f"Bearer {polza_key}"})
                    with urlreq.urlopen(followup_req, timeout=30) as followup_resp:
                        answer = json.loads(followup_resp.read().decode())["choices"][0]["message"]["content"]
                else:
                    answer = message.get("content", "")
            else:
                answer = message.get("content", "")
        for _step in range(3):
            m = re.search(r"TOOL:\s*(\w+)\s+(\w+)=(.+)", answer or "")
            if "=== ЗАКЛЮЧЕНИЕ ===" in (answer or ""):
                break
            if not m:
                follow = urlreq.Request("https://api.polza.ai/v1/chat/completions", data=json.dumps({"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": prompt}, {"role": "assistant", "content": answer}, {"role": "user", "content": "Нет. Напиши TOOL: memory query=Т-пары или === ЗАКЛЮЧЕНИЕ ===. Не отвечай пользователю."}], "temperature": 0.2, "max_tokens": 400}).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {polza_key}"})
                with urlreq.urlopen(follow, timeout=60) as follow_resp:
                    answer = json.loads(follow_resp.read().decode())["choices"][0]["message"]["content"]
                continue
            name, arg, val = m.group(1), m.group(2), m.group(3).strip()
            result = ""
            try:
                keyrow = (_ak.internal_token(req.user_id),)
                headers = {"Content-Type": "application/json"}
                if keyrow:
                    headers["Authorization"] = "Bearer " + keyrow[0]
                if name == "memory":
                    call = urlreq.Request("http://127.0.0.1:8000/api/v7/memory", data=json.dumps({"user_id": req.user_id, "query_text": val, "top_k": 2}).encode(), headers=headers)
                elif name == "dig":
                    call = urlreq.Request("http://127.0.0.1:8000/api/v7/memory/dig", data=json.dumps({"user_id": req.user_id, "query": val}).encode(), headers=headers)
                elif name == "event":
                    call = urlreq.Request("http://127.0.0.1:8000/api/v7/event/" + val, headers=headers)
                else:
                    result = "unknown tool"
                    call = None
                if call:
                    with urlreq.urlopen(call, timeout=40) as tool_resp:
                        result = tool_resp.read().decode()[:1200]
            except Exception as e:
                result = str(e)
            follow = urlreq.Request("https://api.polza.ai/v1/chat/completions", data=json.dumps({"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": prompt}, {"role": "assistant", "content": answer}, {"role": "user", "content": "Результат:\n" + result + "\nTOOL or === ЗАКЛЮЧЕНИЕ ==="}], "temperature": 0.3, "max_tokens": 1400}).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {polza_key}"})
            with urlreq.urlopen(follow, timeout=90) as follow_resp:
                answer = json.loads(follow_resp.read().decode())["choices"][0]["message"]["content"]
        # Remove SEAL from user-facing response
        answer = re.sub(r"🔐.*$", "", answer, flags=re.DOTALL).strip()
        center = ""
        for line in (lens_text or "").split("\n"):
            if "center " in line:
                center = line.split("center ", 1)[1].strip()
                break
        if center and center not in (answer or ""):
            quote = " ".join((opened or "").split())[:220]
            answer = (answer or "").strip() + "\n\nИсточник: " + center + ("\n" + quote if quote else "")
        
        if not is_guest:
            safe_event_id = f"{req.user_id}::chat_{req.session_id}_{int(time.time())}"
            now = datetime.now(timezone.utc)
            session_emb = get_embedding_cached(req.message + " " + answer)
            session_list = session_emb if isinstance(session_emb, list) else session_emb.tolist()
            session_vec = session_list[:218]
            buffer.write_personal_event(event_id=safe_event_id, hour=now.hour, minute=now.minute, semantics_emb=np.array(session_vec, dtype=np.float32), parent_indices=None, details_emb=None, metric_value=len(answer)/1000.0)
            metadata_store.write_metadata(user_id=req.user_id, event_id=safe_event_id, time_str=f"{now.hour:02d}:{now.minute:02d}, {now.strftime('%d.%m.%Y')}", essence=req.message[:200], messages_count=2, topics=["chat_history"], links=[], metric_value=len(answer)/1000.0, raw_dialogue=f"Q: {req.message}\nA: {answer}", is_shared=False)
            pass  # buffer.persistence removed
        
        return {"response": answer, "session_id": req.session_id, "step": req.step + 1, "is_guest": is_guest}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/event/write", status_code=status.HTTP_201_CREATED)
async def write_event(req: EventWriteRequest):
    try:
        import sqlite3
        db_name = req.user_id.replace("@", "").replace(".", "")
        conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db", timeout=30)
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO event_metadata (event_id, time_str, essence, raw_dialogue, status, messages_count, links_json, topics_json, subject, action, object, metric_value) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (f"{req.user_id}::{req.session_id}", datetime.now().strftime("%Y-%m-%d %H:%M"), req.topic or req.query[:100],
                    f"Q: {req.query}\nA: {req.response}", "active", 1, "[]", "[]", "", "", "", 0))
        conn.commit()
        conn.close()
        try:
            from app.account_memory import queue_turn
            queue_turn("/data/skv/metadata_store", req.user_id, f"{req.user_id}::{req.session_id}", req.query, req.response, source="agent", topic=req.topic or "")
        except Exception as exc:
            print(f"[memory] agent queue skipped: {exc}", flush=True)
        return {"status": "ok", "event_id": f"{req.user_id}::{req.session_id}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/memory/summarize", status_code=status.HTTP_201_CREATED)
async def store_summary(req: SummarizeRequest):
    try:
        import sqlite3
        db_name = req.user_id.replace("@", "").replace(".", "")
        conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db", timeout=30)
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS summary_l1
            (session_id TEXT PRIMARY KEY, user_id TEXT, topic TEXT, summary_text TEXT,
             summary_json TEXT, message_count INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("INSERT OR REPLACE INTO summary_l1 (session_id, user_id, topic, summary_text, message_count) VALUES (?,?,?,?,?)",
                   (req.session_id, req.user_id, req.topic, req.summary_text, req.message_count))
        conn.commit()
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/memory/map", status_code=status.HTTP_200_OK)
async def update_memory_map(req: MapUpdateRequest):
    try:
        import sqlite3
        db_name = req.user_id.replace("@", "").replace(".", "")
        conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db", timeout=30)
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS summary_l2
            (user_id TEXT PRIMARY KEY, map_json TEXT, session_count INTEGER,
             last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("INSERT OR REPLACE INTO summary_l2 (user_id, session_count) VALUES (?,?)",
                   (req.user_id, req.session_count))
        conn.commit()
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/agent/batch_flush", status_code=status.HTTP_202_ACCEPTED)
async def agent_batch_flush(req: BatchFlushRequest):
    import sqlite3
    db_name = req.user_id.replace("@", "").replace(".", "")
    conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db", timeout=30)
    cur = conn.cursor()
    if req.batch_logs:
        text = "\n".join([f"Q: {log.get('q','')}\nA: {log.get('a','')}" for log in req.batch_logs])
        cur.execute("INSERT OR REPLACE INTO event_metadata (event_id, time_str, essence, raw_dialogue, status, messages_count, links_json, topics_json, subject, action, object, metric_value) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (f"{req.user_id}::{req.session_id}", req.query or "batch", text, "active", len(req.batch_logs)))
        conn.commit()
    conn.close()
    return {"status": "batch_accepted", "logs_saved": len(req.batch_logs)}


@router.get("/agent/memory")
async def agent_get_memory(query: str, key: str = "", user_id: str = "", top_k: int = 5, authorization: str = Header(None),
                           view: str = "", session_id: str = "", start: bool = False, probe: bool = False,
                           interact: bool = False, format: str = "", focus_event_id: str = ""):
    """Read fallback for weak agents. Key in the query, same result as POST."""
    if not user_id and key:
        user_id = _user_from_key(key)
    if not user_id:
        raise HTTPException(401, "key or user_id required")
    body = MemoryRequest(user_id=user_id, query_text=query, top_k=max(1, min(top_k, 10)), view=view or None,
                         session_id=session_id or None, start=start, probe=probe, interact=interact,
                         format=format or ("text" if (view or _default_view()) == "agent" else None), focus_event_id=focus_event_id or None)
    return await guardian_l1_memory(body, get_memory_buffer(), authorization)

@router.get("/memory/start")
async def memory_start(user_id: str = "", session_id: str = "", query: str = "", format: str = "text",
                       interact: bool = False, authorization: str = Header(None)):
    """First-request pack (memory map + raw/L1/L2 windows + compact constitution) for any agent that can GET."""
    from app import memory_v2 as _mv2
    if not _mv2.enabled():
        raise HTTPException(404, "memory v2 disabled")
    if not user_id:
        raise HTTPException(401, "API key required")
    body = MemoryRequest(user_id=user_id, query_text=query or None, view="agent", session_id=session_id or None,
                         start=True, interact=interact, format=format or "text")
    return await guardian_l1_memory(body, get_memory_buffer(), authorization)


@router.get("/memory/settings")
async def memory_settings_get(user_id: str = ""):
    from app import memory_v2 as _mv2
    if not user_id:
        raise HTTPException(401, "API key required")
    cfg = _mv2.config()
    return {"budgets": _mv2.resolve_budgets(user_id, {}), "user": _mv2.user_settings(user_id),
            "defaults": cfg["budgets"], "caps": cfg["caps"]}


@router.post("/memory/settings")
async def memory_settings_set(req: MemorySettingsRequest):
    """Per-user default budgets (tokens). The server cap still applies."""
    from app import memory_v2 as _mv2
    if not req.user_id:
        raise HTTPException(401, "API key required")
    return {"status": "ok", "budgets": _mv2.save_user_budgets(req.user_id, req.budgets)}


@router.post("/memory/lens")
async def memory_lens(req: MemoryLensRequest):
    """Light follow-up: episodes for a query, or expand one episode with focus_event_id. No step bump."""
    from app import memory_v2 as _mv2
    from app import memory_v2_lens as _mvl
    if not req.user_id:
        raise HTTPException(401, "API key required")
    q = req.query_text or req.query
    if not q and not req.focus_event_id:
        raise HTTPException(422, "query_text or focus_event_id required")
    try:   # lazy schema migration for accounts created before shelves (kind/source/project)
        from app import shelves as _shm
        _shm.ensure_user_db(req.user_id)
    except Exception as _e:
        print(f"[shelves] ensure skipped: {_e}", flush=True)
    b = _mv2.resolve_budgets(req.user_id, {"lens": req.budget_lens})["lens"]
    out = _mvl.lens(req.user_id, q, budget=b, focus_event_id=req.focus_event_id, radius=req.radius, offset=req.offset,
                    kind=req.kind, source=req.source, project=req.project)
    out["budget"] = {"lens": b}
    return _mv2.mask_obj(out)


@router.get("/memory/profile")
async def memory_profile_get(user_id: str = ""):
    from app import memory_v2_windows as _mvw
    if not user_id:
        raise HTTPException(401, "API key required")
    return _mvw.get_profile(user_id)


@router.post("/memory/profile")
async def memory_profile_set(req: MemoryProfileRequest):
    """Merge into the user profile used by the memory map (who, projects, prefs). Nothing is deleted."""
    from app import memory_v2_windows as _mvw
    if not req.user_id:
        raise HTTPException(401, "API key required")
    return {"status": "ok", "profile": _mvw.merge_profile(req.user_id, who=req.who, projects=req.projects, prefs=req.prefs)}


@router.get("/memory/l2/blocks")
async def memory_l2_blocks(user_id: str = "", limit: int = 50):
    from app import memory_v2_windows as _mvw
    if not user_id:
        raise HTTPException(401, "API key required")
    return {"blocks": _mvw.list_l2_blocks(user_id, max(1, min(limit, 200)))}



@router.get("/event/{event_id}")
async def get_event_detail(event_id: str):
    import json
    """Возвращает полный текст события по ID."""
    import sqlite3
    user_part = event_id.split("::")[0] if "::" in event_id else "test_user"
    db_name = user_part.replace("@", "").replace(".", "")
    
    conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db", timeout=30)
    cur = conn.cursor()
    cur.execute("SELECT event_id, time_str, essence, raw_dialogue, links_json, messages_count FROM event_metadata WHERE event_id = ?", (event_id,))
    row = cur.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(404, "Event not found")
    
    from app import memory_v2 as _mv2
    return _mv2.mask_obj({
        "event_id": row[0],
        "time": row[1],
        "essence": row[2],
        "full_text": row[3],
        "links": json.loads(row[4]) if row[4] and row[4].strip() else [],
        "messages_count": row[5]
    })


@router.post("/memory/search/date")
async def search_by_date(data: dict):
    """Fuzzy search by date/time. Day→week, time→+-2h, month→month."""
    user_id = data.get("user_id", "")
    date_query = data.get("date", "")
    event_prefix = data.get("event_prefix", "")
    limit = data.get("limit", 20)
    
    if not user_id:
        return {"error": "user_id required"}
    
    db_name = user_id.replace("@", "").replace(".", "")
    conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db", timeout=10)
    cur = conn.cursor()
    
    query = "SELECT event_id, time_str, essence, substr(raw_dialogue,1,300) FROM event_metadata WHERE 1=1"
    params = []
    
    if date_query:
        if len(date_query) == 16:  # YYYY-MM-DD HH:MM → +-2h
            query += " AND time_str >= ? AND time_str <= ?"
            params.append(date_query)
            try:
                dt = datetime.strptime(date_query, "%Y-%m-%d %H:%M")
                params.append((dt + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"))
            except:
                params.append(date_query + ":99")
        elif len(date_query) == 10:  # YYYY-MM-DD → +-7 days
            query += " AND time_str >= ? AND time_str <= ?"
            params.append(date_query)
            try:
                dt = datetime.strptime(date_query, "%Y-%m-%d")
                params.append((dt + timedelta(days=7)).strftime("%Y-%m-%d"))
            except:
                params.append(date_query + "z")
        elif len(date_query) == 7:  # YYYY-MM → whole month
            query += " AND time_str LIKE ?"
            params.append(f"{date_query}%")
        else:
            query += " AND time_str LIKE ?"
            params.append(f"%{date_query}%")
    
    if event_prefix:
        query += " AND event_id LIKE ?"
        params.append(f"%{event_prefix}%")
    
    query += " ORDER BY event_id DESC LIMIT ?"
    params.append(limit)
    
    cur.execute(query, params)
    results = [{"event_id": eid, "time": ts, "essence": essence, "preview": raw[:200]} 
               for eid, ts, essence, raw in cur.fetchall()]
    conn.close()
    return {"results": results, "count": len(results)}


@router.post("/remember")
async def remember(req: RememberRequest):
    import sqlite3, json, time
    from app.account_memory import queue_turn, account_db_name
    saved = []
    name = account_db_name(req.user_id)
    _vaulted = []
    try:   # secrets never stay in memory: move them to the vault, keep [vault:<name>] references
        from app import vault as _vault
        if _vault.available():
            for _f in ("query", "response", "critical", "l1_summary", "l2_map", "cube_rules", "cube_evidence", "topic", "cube_topic", "cube_essence"):
                _v = getattr(req, _f, None)
                if isinstance(_v, str) and _v:
                    _new, _names = _vault.scrub(req.user_id, _v)
                    if _names:
                        setattr(req, _f, _new)
                        _vaulted += _names
    except Exception as _e:
        print(f"[vault] remember scrub skipped: {_e}", flush=True)
    if req.query or req.response:
        text_q = req.query
        text_a = req.response
        if req.pin or req.critical:
            text_a = (text_a + "\n>>> " + (req.critical or req.topic or "pinned")).strip()
    elif req.critical:
        # a Critical item on its own (no turn text): store it as its own pinned record
        text_q = req.topic or "critical"
        text_a = ">>> " + req.critical
    if req.query or req.response or req.critical:
        eid = f"{req.user_id}::remember_{time.time_ns()}"
        _ts = _event_time_str(req.ts or req.occurred_at)
        queue_turn("/data/skv/metadata_store", req.user_id, eid, text_q, text_a, source="agent", topic=req.topic, time_str=_ts)
        from app.account_memory import link_turn
        link_turn("/data/skv/metadata_store", req.user_id, eid, req.topic or "")
        saved.append(eid)
        if req.kind != "dialogue" or req.source or req.project:
            try:
                from app import shelves as _sh
                _sh.tag(req.user_id, [eid], _sh.normalize_kind(req.kind) or "dialogue", req.source, req.project)
            except Exception as _e:
                print(f"[shelves] tag skipped: {_e}", flush=True)
        try:
            st = sqlite3.connect(path if False else f"/data/skv/metadata_store/{name}.db")
            row = st.execute("SELECT step FROM agent_state WHERE user_id=?", (name,)).fetchone()
            st.close()
            dc = sqlite3.connect(SHARED_DB)
            dc.execute("CREATE TABLE IF NOT EXISTS agent_duty (id INTEGER PRIMARY KEY, user_id TEXT, step INTEGER, duty TEXT, reason TEXT, created_at TEXT)")
            dc.execute("INSERT INTO agent_duty (user_id, step, duty, reason, created_at) VALUES (?,?,?,?,datetime('now'))", (req.user_id, row[0] if row else 0, "saved", "remember"))
            dc.commit(); dc.close()
        except Exception:
            pass
    path = f"/data/skv/metadata_store/{name}.db"
    if req.l1_summary or req.l2_map:
        _l1_sid = None
        try:
            from app import memory_v2 as _mv2
            _l2_overwrite = bool(_mv2.config().get("l2_legacy_overwrite", True))
            if req.l2_map and _mv2.enabled():
                from app import memory_v2_windows as _mvw
                _mvw.before_legacy_l2_overwrite(req.user_id)   # keep the old L2 text as a block
        except Exception as _e:
            _l2_overwrite = True
            print(f"[memory_v2] l2 snapshot skipped: {_e}", flush=True)
        conn = sqlite3.connect(path, timeout=30)
        cur = conn.cursor()
        if req.l1_summary:
            cur.execute("CREATE TABLE IF NOT EXISTS summary_l1 (session_id TEXT PRIMARY KEY, user_id TEXT, topic TEXT, summary_text TEXT, summary_json TEXT, message_count INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            _l1_sid = (req.session_id or "remember") + "_" + str(__import__("time").time_ns())
            cur.execute("INSERT OR REPLACE INTO summary_l1 (session_id, user_id, topic, summary_text, message_count) VALUES (?,?,?,?,?)",
                        (_l1_sid, req.user_id, req.topic or "session", req.l1_summary, 1))
            saved.append("l1")
        if req.l2_map:
            cur.execute("CREATE TABLE IF NOT EXISTS summary_l2 (user_id TEXT PRIMARY KEY, map_json TEXT, themes_json TEXT, timeline_json TEXT, session_count INTEGER, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            if _l2_overwrite:
                cur.execute("INSERT OR REPLACE INTO summary_l2 (user_id, map_json, themes_json, timeline_json, session_count) VALUES (?,?,?,?,?)",
                            (req.user_id, req.l2_map, "[]", "[]", 1))
            saved.append("l2")
        conn.commit(); conn.close()
        try:
            from app import memory_v2 as _mv2
            if _mv2.enabled():
                from app import memory_v2_windows as _mvw
                _ev = next((x for x in saved if "::" in x), None)
                _mvw.on_remember(req.user_id, _ev, _l1_sid, req.l2_map or None)
        except Exception as _e:
            print(f"[memory_v2] on_remember skipped: {_e}", flush=True)
    _cube_info = None
    if req.cube_topic and req.cube_rules:
        import uuid
        from app import cube_guard as _cg
        _ess = (req.cube_essence or "").strip() or (req.cube_rules or "").strip().splitlines()[0][:200]
        _ok, _fields, _reasons, _pii = _cg.prepare_shared(req.cube_topic, _ess, req.cube_rules, req.cube_evidence)
        _shared = bool(req.cube_publish) and _ok
        cube_id = "cube_" + uuid.uuid4().hex[:12]
        from app import cubes_v2 as _cv2
        _ctype = _cv2.norm_kind(req.cube_type, "moment")
        if _ctype not in _cv2.EXPERIENCE_KINDS:
            _ctype = "moment"
        if _shared:
            conn = sqlite3.connect(SHARED_DB)
            _cv2.ensure(conn)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO cubes_new (cube_id, essence, subject_action_object, rules_markdown, evidence, source_session, status, created_by, kind) VALUES (?,?,?,?,?,?,?,?,?)",
                (cube_id, _fields["essence"], _fields["topic"], _fields["rules"], _fields["evidence"], req.session_id, "community", req.user_id, _ctype),
            )
            conn.commit(); conn.close()
        else:
            # private cube: stays in the user's own database, never in the shared pool
            _pc = sqlite3.connect(os.path.join(USER_DB_DIR, name + ".db"), timeout=30)
            _cv2.migrate_private_schema(_pc)   # older user dbs have another experience_cubes schema
            _pc.execute("INSERT INTO experience_cubes (cube_id, topic, essence, rules_markdown, evidence, session_id, kind) VALUES (?,?,?,?,?,?,?)",
                        (cube_id, req.cube_topic, _ess, req.cube_rules, req.cube_evidence, req.session_id, _ctype))
            _pc.commit(); _pc.close()
        _cube_info = {"cube_id": cube_id, "shared": _shared,
                      "why_private": ([] if _shared else (["not published: send cube_publish=true"] if not req.cube_publish else []) + _reasons),
                      "pii_masked": _pii if _shared else []}
        if saved:
            import sqlite3 as _link
            _db = "/data/skv/metadata_store/" + "".join(c for c in req.user_id if c.isalnum() or c in "_-") + ".db"
            _c = _link.connect(_db)
            _c.execute("CREATE TABLE IF NOT EXISTS event_links (src TEXT, dst TEXT, kind TEXT, created_at TEXT, PRIMARY KEY (src, dst, kind))")
            _c.execute("INSERT OR REPLACE INTO event_links (src, dst, kind, created_at) VALUES (?,?,?,datetime('now'))", (saved[0], cube_id, "cube"))
            _c.commit(); _c.close()
        if _shared and req.close_task and req.cube_rules:
            tconn = sqlite3.connect(SHARED_DB)
            tconn.execute("CREATE TABLE IF NOT EXISTS cube_links (src TEXT, dst TEXT, kind TEXT, created_by TEXT, created_at TEXT, PRIMARY KEY (src, dst, kind))")
            kind = "answer" if req.cube_kind == "answer" else "hypothesis"
            tconn.execute("INSERT OR IGNORE INTO cube_links (src, dst, kind, created_by, created_at) VALUES (?,?,?,?,datetime('now'))", (req.close_task, saved[-1] if saved else "", kind, req.user_id))
            if kind == "answer":
                tconn.execute("CREATE TABLE IF NOT EXISTS task_confirms (task_id TEXT PRIMARY KEY, n INTEGER)")
                tconn.execute("INSERT INTO task_confirms (task_id, n) VALUES (?,1) ON CONFLICT(task_id) DO UPDATE SET n=n+1", (req.close_task,))
                n = tconn.execute("SELECT n FROM task_confirms WHERE task_id=?", (req.close_task,)).fetchone()[0]
                if n >= 3:
                    tconn.execute("UPDATE cube_tasks SET status='closed' WHERE task_id=?", (req.close_task,))
                    tconn.execute("INSERT OR IGNORE INTO cube_links (src, dst, kind, created_by, created_at) VALUES (?,?,?,?,datetime('now'))", (req.close_task, saved[-1] if saved else "", "sequence", req.user_id))
            tconn.commit(); tconn.close()
        if _shared and req.cube_from:
            conn2 = sqlite3.connect(SHARED_DB)
            conn2.execute("CREATE TABLE IF NOT EXISTS cube_links (src TEXT, dst TEXT, kind TEXT, created_by TEXT, created_at TEXT, PRIMARY KEY (src, dst, kind))")
            kind = req.cube_kind if req.cube_kind in ("progress", "synthesis") else "progress"
            conn2.execute("INSERT OR IGNORE INTO cube_links (src, dst, kind, created_by, created_at) VALUES (?,?,?,?,datetime('now'))", (req.cube_from, cube_id, kind, req.user_id))
            conn2.commit(); conn2.close()
        saved.append(cube_id if _shared else "private:" + cube_id)
    if req.task_question:
        import uuid as _uuid
        task_id = "task_" + _uuid.uuid4().hex[:12]
        tconn = sqlite3.connect(SHARED_DB)
        tconn.execute("CREATE TABLE IF NOT EXISTS cube_tasks (task_id TEXT PRIMARY KEY, topic TEXT, question TEXT, tried TEXT, accept TEXT, status TEXT, created_by TEXT, created_at TEXT)")
        tconn.execute("INSERT INTO cube_tasks (task_id, topic, question, tried, accept, status, created_by, created_at) VALUES (?,?,?,?,?,'open',?,datetime('now'))",
                      (task_id, req.cube_topic or req.topic, req.task_question, req.task_tried, req.task_accept, req.user_id))
        tconn.commit(); tconn.close()
        saved.append(task_id)
    if req.duty:
        conn = sqlite3.connect(SHARED_DB)
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS agent_duty (id INTEGER PRIMARY KEY, user_id TEXT, step INTEGER, duty TEXT, reason TEXT, created_at TEXT)")
        cur.execute("INSERT INTO agent_duty (user_id, step, duty, reason, created_at) VALUES (?,?,?,?,datetime('now'))",
                    (req.user_id, _duty_step(req.user_id), req.duty, req.duty_reason or ""))
        conn.commit(); conn.close()
        saved.append(req.duty)
    _duty_notes = []
    try:
        from app import cubes_v2 as _cv2
        _dc = sqlite3.connect(SHARED_DB, timeout=30)
        _cv2.ensure(_dc)
        _wrote = bool(_cube_info)
        if _wrote:
            _dc.execute("INSERT INTO agent_duty (user_id, step, duty, reason, created_at) VALUES (?,?,?,?,datetime('now'))", (req.user_id, _duty_step(req.user_id), "cube", _cube_info["cube_id"]))
        _duty_notes = _cv2.on_remember(_dc, req.user_id, _duty_step(req.user_id), topic=req.topic or req.cube_topic if not _wrote else req.topic,
                                       task_done=req.task_done, wrote_cube=_wrote, duty=req.duty, duty_reason=req.duty_reason, turn=bool(req.query or req.response))
        _dc.commit(); _dc.close()
    except Exception as _e:
        print(f"[cubes_v2] remember duty skipped: {_e}", flush=True)
    _out = {"status": "ok", "saved": saved}
    if _duty_notes:
        _out["cube_duty"] = _duty_notes
    if _cube_info:
        _out["cube"] = _cube_info
    if _vaulted:
        _out["vaulted"] = list(dict.fromkeys(_vaulted))
        _out["vault_note"] = "Secrets were moved to the vault; memory keeps [vault:<name>] references. Use POST /api/v7/vault/use."
    return _out


@router.post("/memory/forget/preview")
async def forget_preview(req: ForgetPreviewRequest):
    """Step 1: list what would be forgotten. Nothing changes. Confirm with the returned token."""
    import json as _json, secrets, time as _t
    if not req.user_id:
        raise HTTPException(401, "API key required")
    conn = _forget_db(req.user_id)
    try:
        lim = max(1, min(req.limit, 200))
        own = req.user_id + "::%"
        if req.mode == "shelf":
            if not (req.kind or req.source or req.project):
                raise HTTPException(422, "kind, source or project required for mode=shelf")
            from app import shelves as _sh
            rows = _sh.select_ids(req.user_id, req.kind or None, req.source or None, req.project or None, lim)
        elif req.mode == "event":
            ids = [i for i in req.event_ids if i.startswith(req.user_id + "::")][:lim]
            rows = conn.execute("SELECT event_id, time_str, substr(raw_dialogue,1,160) FROM event_metadata WHERE event_id IN (%s)" % ",".join("?" * len(ids)), ids).fetchall() if ids else []
        elif req.mode == "topic":
            if not req.query.strip():
                raise HTTPException(422, "query required")
            rows = conn.execute("SELECT event_id, time_str, substr(raw_dialogue,1,160) FROM event_metadata WHERE event_id LIKE ? AND (essence = ? OR raw_dialogue LIKE ?) LIMIT ?",
                                (own, req.query, "%[" + req.query + "]%", lim)).fetchall()
        else:
            if len(req.query.strip()) < 3:
                raise HTTPException(422, "query of 3+ characters required")
            rows = conn.execute("SELECT event_id, time_str, substr(raw_dialogue,1,160) FROM event_metadata WHERE event_id LIKE ? AND raw_dialogue LIKE ? LIMIT ?",
                                (own, "%" + req.query + "%", lim)).fetchall()
        token = "fg_" + secrets.token_hex(12)
        conn.execute("INSERT INTO forget_requests (token, ids_json, created) VALUES (?,?,?)", (token, _json.dumps([r[0] for r in rows]), _t.time()))
        conn.commit()
    finally:
        conn.close()
    return {"status": "preview", "count": len(rows), "items": [{"event_id": r[0], "time": r[1], "preview": r[2]} for r in rows],
            "confirm": {"POST": "/api/v7/memory/forget/confirm", "token": token, "user_confirmed": True, "expires_in_s": FORGET_TTL_S, "single_use": True},
            "ask_user": "Show the user these items and say: '" + FORGET_WARNING + "' Ask for an explicit yes. Call confirm only after the user explicitly says yes.",
            "warning": FORGET_WARNING,
            "retention_days": FORGET_RETENTION_S // 86400,
            "purge_at": _purge_at(_t.time()) + " if confirmed now",
            "for_agent": "Never auto-confirm. Never confirm in the same turn as the preview without the user's explicit yes.",
            "note": "Nothing is deleted yet."}


@router.post("/memory/forget/confirm")
async def forget_confirm(req: ForgetConfirmRequest):
    """Step 2: move the previewed turns to the archive table event_forgotten."""
    return _forget_apply(req)


@router.post("/memory/forget/restore")
async def forget_restore(req: ForgetConfirmRequest):
    """Undo a confirmed forget with the same token, within 30 days (then the archive is purged)."""
    return _forget_apply(req, restore=True)


@router.post("/shelf/ingest")
async def shelf_ingest(req: ShelfIngestRequest):
    """Put a document, code file or email on its shelf. Chunked per kind: code by function/class (path+version), docs by section, email with sender+date."""
    from app import shelves as _sh
    from app.account_memory import queue_turn
    if not req.user_id:
        raise HTTPException(401, "API key required")
    req.kind = _sh.normalize_kind(req.kind) or ""
    if not req.kind:
        raise HTTPException(422, "kind must be an English slug (a-z, 0-9, '-'); recommended: " + ", ".join(_sh.DEFAULT_KINDS))
    if len(req.text) > 400_000:
        raise HTTPException(413, "text too large (max 400k chars)")
    parts = _sh.chunk(req.kind, req.text, req.path, req.version, req.sender, req.date, req.title)[:300]
    ids = []
    for header, body in parts:
        eid = _sh.chunk_id(req.user_id, req.kind, req.project, header, body)
        if req.critical:
            body = body + "\n>>> " + req.critical
        queue_turn("/data/skv/metadata_store", req.user_id, eid, header, body, source=req.source or req.kind, topic=req.title or req.path or header[:80])
        ids.append(eid)
    _sh.tag(req.user_id, ids, req.kind, req.source, req.project, req.shelf_description)
    return {"status": "ok", "kind": req.kind, "source": req.source, "project": req.project, "chunks": len(ids), "event_ids": ids[:50]}


@router.post("/shelf/rename")
async def shelf_rename(req: ShelfRenameRequest):
    """Rename a shelf, or merge it into an existing shelf (same call)."""
    from app import shelves as _sh
    if not req.user_id:
        raise HTTPException(401, "API key required")
    try:
        return {"status": "ok", **_sh.rename(req.user_id, req.from_shelf, req.to_shelf, req.description)}
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/shelves")
async def list_shelves(user_id: str = ""):
    """How much is on each shelf (kind / source / project)."""
    from app import shelves as _sh
    if not user_id:
        raise HTTPException(401, "API key required")
    return {"shelves": _sh.counts(user_id)}

@router.post("/memory/dig")
async def memory_dig(req: DigRequest):
    """Third look. Server scans stored text. No cheap model on the whole archive."""
    import sqlite3
    words = [w.strip(".,!?;:\"'") for w in (req.query or req.query_text).split() if len(w) > 3]
    common = {"killed", "who", "what", "where", "when", "this", "that", "with", "from", "have", "book", "call"}
    rare = [w for w in words if w.lower() not in common] or words[:2]
    name = "".join(c for c in req.user_id if c.isalnum() or c in ("_", "-"))
    found = []
    path = f"/data/skv/metadata_store/{name}.db"
    try:
        conn = sqlite3.connect(path)
        for word in rare[:4]:
            like = "%" + word + "%"
            for row in conn.execute("SELECT event_id, substr(raw_dialogue,1,180) FROM event_metadata WHERE raw_dialogue LIKE ? LIMIT 3", (like,)):
                found.append({"event_id": row[0], "preview": row[1], "word": word, "open": "/api/v7/event/" + row[0]})
            try:
                for row in conn.execute("SELECT topic, summary_text FROM summary_l1 WHERE summary_text LIKE ? LIMIT 3", (like,)):
                    found.append({"event_id": "l1:" + (row[0] or ""), "preview": row[1], "word": word, "open": ""})
            except Exception:
                pass
            try:
                for row in conn.execute("SELECT event_id, substr(raw_dialogue,1,180) FROM event_archive WHERE raw_dialogue LIKE ? LIMIT 2", (like,)):
                    found.append({"event_id": row[0], "preview": row[1], "word": word, "open": "/api/v7/event/" + row[0], "note": "archived"})
            except Exception:
                pass
        conn.close()
    except Exception as exc:
        return {"status": "empty", "reason": str(exc), "found": []}
    from app import memory_v2 as _mv2
    return _mv2.mask_obj({"status": "ok" if found else "not_found", "query": req.query, "why": req.why, "found": found[:8], "note": "Server scan only. Do not invent a fact if found is empty."})

@router.post("/technical")
async def technical(req: TechnicalRequest):
    """Hidden channel. Same call as the user reply, not shown to the person."""
    body = RememberRequest(user_id=req.user_id, l1_summary=req.l1_summary, l2_map=req.l2_map, topic=req.topic, duty="cube_nothing", duty_reason="technical")
    saved = await remember(body)
    if req.link_src and req.link_dst:
        import sqlite3
        db = "/data/skv/metadata_store/" + "".join(c for c in req.user_id if c.isalnum() or c in "_-") + ".db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE IF NOT EXISTS event_links (src TEXT, dst TEXT, kind TEXT, created_at TEXT, PRIMARY KEY (src, dst, kind))")
        conn.execute("INSERT OR REPLACE INTO event_links (src, dst, kind, created_at) VALUES (?,?,?,datetime('now'))", (req.link_src, req.link_dst, "topic"))
        conn.commit(); conn.close()
        saved.setdefault("saved", []).append("link")
    return saved


@router.get("/start")
async def start_page():
    from fastapi.responses import HTMLResponse
    return HTMLResponse("""<!doctype html><meta charset="utf-8"><title>SKV start</title>
<body style="font-family:sans-serif;max-width:640px;margin:40px auto;line-height:1.5">
<h1>После регистрации</h1>
<ol>
<li>Открой чат и подтверди почту. Ключ sk_ появится в профиле.</li>
<li>Положи ключ в настройку своего агента, не в текст чата.</li>
<li>Дай агенту ссылку https://skv.network/api/v7/agent/start и попроси настроить SKV под твою модель.</li>
<li>В новом чате он сам начнёт с карты, step 0.</li>
</ol>
<p><a href="/chat">К чату</a></p>
</body>""")

@router.post("/calendar")
async def add_calendar(req: CalendarRequest):
    import sqlite3
    name = "".join(c for c in req.user_id if c.isalnum() or c in "_-")
    path = f"/data/skv/metadata_store/{name}.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS agent_calendar (id INTEGER PRIMARY KEY, user_id TEXT, date TEXT, title TEXT, kind TEXT, status TEXT, created_at TEXT)")
    conn.execute("INSERT INTO agent_calendar (user_id, date, title, kind, status, created_at) VALUES (?,?,?,?,?,datetime('now'))",
                 (req.user_id, req.date, req.title[:200], req.kind, "open"))
    conn.commit(); conn.close()
    return {"status": "ok"}

@router.get("/calendar")
async def list_calendar(user_id: str, limit: int = 10):
    import sqlite3
    name = "".join(c for c in user_id if c.isalnum() or c in "_-")
    path = f"/data/skv/metadata_store/{name}.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS agent_calendar (id INTEGER PRIMARY KEY, user_id TEXT, date TEXT, title TEXT, kind TEXT, status TEXT, created_at TEXT)")
    rows = conn.execute("SELECT date, title, kind FROM agent_calendar WHERE status='open' ORDER BY date LIMIT ?", (limit,)).fetchall()
    conn.close()
    return {"items": [{"date": r[0], "title": r[1], "kind": r[2]} for r in rows]}

@router.get("/agent/remember")
async def agent_get_remember(key: str, query: str = "", response: str = "", topic: str = "", critical: str = "", l1_summary: str = "", ts: str = "", occurred_at: str = ""):
    user_id = _user_from_key(key)
    return await remember(RememberRequest(user_id=user_id, query=query, response=response, topic=topic, critical=critical, l1_summary=l1_summary, ts=ts, occurred_at=occurred_at))


@router.post("/recall/deep")
async def deep_recall_start(req: DeepRecallRequest):
    """Start a deep scan across all shelves. Returns job_id at once; poll GET /recall/deep/{job_id}."""
    import secrets as _s
    if not req.user_id:
        raise HTTPException(401, "API key required")
    if len(req.topic.strip()) < 2:
        raise HTTPException(422, "topic required")
    now = _time.time()
    with _DEEP_LOCK:
        for k in [k for k, v in _DEEP_JOBS.items() if now - v["created"] > _DEEP_TTL_S]:
            _DEEP_JOBS.pop(k, None)
        running = sum(1 for v in _DEEP_JOBS.values() if v["owner"] == req.user_id and v["status"] in ("queued", "running"))
        if running >= 3:
            raise HTTPException(429, "too many deep recall jobs running")
        job_id = "dr_" + _s.token_hex(10)
        _DEEP_JOBS[job_id] = {"owner": req.user_id, "status": "queued", "created": now, "topic": req.topic, "partial": None, "final": None}
    threading.Thread(target=_deep_scan, args=(job_id, req.user_id, req.topic, max(10, min(req.limit, 300))), daemon=True).start()
    return {"job_id": job_id, "status": "queued", "poll": f"/api/v7/recall/deep/{job_id}"}


@router.get("/recall/deep/{job_id}")
async def deep_recall_get(job_id: str, user_id: str = ""):
    if not user_id:
        raise HTTPException(401, "API key required")
    job = _DEEP_JOBS.get(job_id)
    if not job or job["owner"] != user_id:
        raise HTTPException(404, "job not found")
    out = {"job_id": job_id, "status": job["status"], "topic": job["topic"]}
    if job["status"] == "done":
        out["result"] = job["final"]
    elif job["status"] == "error":
        out["error"] = job.get("error")
    else:
        out["partial"] = job["partial"]
    return out

"""SKV v7 API: agent helpers: site chat, agent run/step/pack/start, owner shell.
Split from v7_router.py with behavior unchanged; shared helpers and state come from v7_core."""
from app.routers import v7_core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith("__")})


@router.post("/agent/shell")
async def agent_shell(data: dict, authorization: str = Header(None), x_api_key: str = Header(None)):
    """Execute shell command. Owner account only (env SKV_SHELL_OWNERS, comma-separated user ids)."""
    cmd = data.get("cmd", "")
    token = (data.get("token") or "").strip()
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token and x_api_key:
        token = x_api_key.strip()
    if not token:
        raise HTTPException(401, "Token required")

    # Verify token
    import sqlite3 as _sq
    conn = _sq.connect(SHARED_DB, timeout=5)
    cur = conn.cursor()
    cur.execute(_ak.SQL_USER, _ak.args(token))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(401, "Invalid token")
    owners = {u.strip().lower() for u in os.environ.get("SKV_SHELL_OWNERS", "denizchavdarov@gmail.com").split(",") if u.strip()}
    if str(row[0]).strip().lower() not in owners:
        raise HTTPException(403, "Shell is restricted to the owner account")
    
    if not cmd:
        return {"error": "cmd required"}
    
    # Restricted commands
    dangerous = ['rm -rf', 'mkfs', 'dd if=', ':(){', 'chmod 777', '> /dev/sda']
    for d in dangerous:
        if d in cmd:
            return {"error": f"Dangerous command blocked: {d}"}
    
    import subprocess
    try:
        _cwd = os.environ.get("SKV_SHELL_CWD", "/app")
        if not os.path.isdir(_cwd):
            _cwd = None
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, cwd=_cwd)
        return {
            "stdout": (result.stdout or "")[:5000],
            "stderr": (result.stderr or "")[:1000],
            "returncode": result.returncode
        }
    except Exception as e:
        return {"error": str(e)}

# ==================== SKV CHAT v8.3 PRODUCTION ====================
# Архитектура:
# - DeepSeek: ответы пользователю + кубы/фидбэк (по команде)
# - Llama: L1 summary (каждые 15), L2 map (каждые 30)
# - Бэкенд: сохранение текста, счётчик, триггеры

@router.post("/agent/chat")
async def agent_chat(req: ChatRequest):  # Buffer not needed for chat
    try:
        import json, urllib.request as urlreq, time, re
        try:
            polza_key = os.environ.get("POLZA_KEY", "")
            headers = {"Content-Type": "application/json", "Authorization": "Bearer " + polza_key}
            mem = await guardian_l1_memory(MemoryRequest(user_id=req.user_id, query_text=req.message, top_k=3, step=0, view="legacy"), get_memory_buffer(), None)
            cubes = mem.get("shared_cubes") or []
            lines = []
            for c in cubes[:5]:
                lines.append(str(c.get("note")) + ": " + str(c.get("essence")) + " | " + str(c.get("rules")))
            pack = ("<<SHARED_CUBES_DATA>>\n" + CUBES_DATA_MARKER + "\n" + "\n".join(lines) + "\n<</SHARED_CUBES_DATA>>") if lines else "no cubes"
            memory_text = str(mem.get("prompt_text") or "")[:1800]
            import re as _re
            calc = ""
            m = _re.search(r"(\d+)\s*(?:times|x|\*|×)\s*(\d+)", req.message.lower())
            if m:
                from app.routers.execute_code import run_code
                ran = await run_code("print(%s*%s)" % (m.group(1), m.group(2)))
                calc = "CALC: " + str(ran.get("stdout") or "").strip()
            dug = await memory_dig(DigRequest(user_id=req.user_id, query=req.message))
            dig_text = str(dug)[:600]
            const = ""
            try:
                _c = __import__("sqlite3").connect(SHARED_DB)
                parts = []
                for cid in ("cube_const_00_v5","cube_const_01_v4","cube_const_02_v4","cube_const_03_v4","cube_const_04_v4"):
                    _flt, _args = _const_trusted_sql()
                    row = _c.execute("select rules_markdown from cubes_new where cube_id=? AND " + _flt, [cid] + _args).fetchone()
                    if row:
                        parts.append(row[0][:900])
                const = "\n\n".join(parts)
                _c.close()
            except Exception:
                const = ""
            hist = ""
            if req.chat_history:
                tail = req.chat_history[-8:]
                hist = "Earlier in this same chat. Use it. Do not ask again for what is already here:\n" + "\n".join(str(h)[:500] for h in tail) + "\n\n"
            prompt = (
                "CONSTITUTION. Follow it. You do the Second Look in your head, the server cannot.\n"
                "DRAFT the answer. VERIFY against CUBE 01 harm, 02 truth, 03 morality, 04 manipulation, and PACK.\n"
                "CORRECT the draft if it breaks a rule or ignores a cube. Then OUTPUT only the final answer.\n"
                "The person sees only the answer. Do not print MEMORY, LENS, SECOND LOOK, cube ids, or duty.\n"
                "A short seal at the end is enough: SKV | READ | VERIFY | CORRECT | OUTPUT\n\n"
                + const + "\n\nPACK:\n" + pack + "\n\nMEMORY:\n" + memory_text[:700] + "\n\n" + hist + calc + "\n\nQuestion: " + req.message
            )
            body = json.dumps({"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 800}).encode()
            final = json.loads(urlreq.urlopen(urlreq.Request("https://api.polza.ai/v1/chat/completions", data=body, headers=headers), timeout=60).read())["choices"][0]["message"]["content"].strip()
            seal = "SKV | probe | READ | VERIFY | " + str(len(cubes)) + " cubes"
            try:
                from app.account_memory import queue_turn
                queue_turn("/data/skv/metadata_store", req.user_id, req.user_id + "::chat_" + str(int(time.time())), req.message, final, source="chat")
            except Exception:
                pass
            return {"response": final + "\n\n" + seal, "session_id": req.session_id, "step": (req.step or 0) + 1, "is_guest": req.user_id.startswith("guest_"), "cubes": [c.get("cube_id") for c in cubes[:5]], "steps": 2}
        except Exception:
            pass
        import sqlite3 as _sq
        from datetime import datetime, timedelta
        from app.routers.v4_middleware import get_embedding_cached

        # Normalize chat history to strings
        if req.chat_history and isinstance(req.chat_history[0], dict):
            req.chat_history = [f"{h.get('role', '?')}: {h.get('content', '')}" for h in req.chat_history]
        
        # Find or create session for this user
        db_name = req.user_id.replace('@', '').replace('.', '')
        if req.session_id == 'default' or not req.session_id:
            # Auto-find last active session or create new
            try:
                sconn = _sq.connect(f'/data/skv/metadata_store/{db_name}.db')
                scur = sconn.cursor()
                scur.execute("SELECT session_id FROM chat_sessions WHERE user_id=? ORDER BY updated_at DESC LIMIT 1", (req.user_id,))
                srow = scur.fetchone()
                if srow:
                    req.session_id = srow[0]
                else:
                    req.session_id = f"{req.user_id}_chat_{int(time.time())}"
                sconn.close()
            except:
                req.session_id = f"{req.user_id}_chat_{int(time.time())}"
        
        is_guest = req.user_id.startswith("guest_")
        guest_warning = "GUEST MODE: Register at skv.network for permanent memory.\n" if is_guest else ""
        user_status = f"User: {req.user_id} | Status: {'Guest (temporary)' if is_guest else 'Registered (memory active)'}\n"


        # ========== 1. ПОИСК ПАМЯТИ (FTS5 first, then HNSW) ==========
        emb = get_embedding_cached(req.message)
        emb_list = emb if isinstance(emb, list) else emb.tolist()
        q_vec = np.zeros(768, dtype=np.float32)
        q_vec[:min(len(emb_list), 768)] = emb_list[:768]
        
        hnsw_results = []  # Agent uses searchMemory tool
        if hnsw_results:
            event_ids = [eid for eid, _ in hnsw_results[:5]]
            metadata_map = metadata_store.batch_get_metadata(req.user_id, event_ids)
            memory_parts = []
            for eid, score in hnsw_results[:5]:
                meta = metadata_map.get(eid) or {}
                essence = meta.get('essence', '') if meta else ''
                # Топ-1: полный текст, остальные: essence + links
                links_data = meta.get('links_json', '')
                link_str = ""
                if links_data and links_data.strip() and links_data != '[]':
                    try:
                        links_parsed = json.loads(links_data) if isinstance(links_data, str) else links_data
                        if isinstance(links_parsed, dict):
                            link_str = " | 🔗 " + ", ".join(list(links_parsed.keys())[:3])
                    except:
                        pass
                
                if len(memory_parts) == 0:
                    raw = meta.get('raw_dialogue', essence) or ''
                    memory_parts.append(f"=== TOP MATCH (Score: {score:.2f}) ===\nID: {eid}{link_str}\n{str(raw)[:3000]}")
                else:
                    memory_parts.append(f"ID: {eid}{link_str} | Score: {score:.2f} | {str(essence)[:500]}")
            memory_text = "\n".join(memory_parts)
        else:
            memory_text = "No relevant memory."
        
        # FTS5 exact search FIRST (better for names, terms)
        fts_text = ""
        try:
            import sqlite3 as sq
            db_name = req.user_id.replace('@', '').replace('.', '')
            fts_conn = sq.connect(f'/data/skv/metadata_store/{db_name}.db')
            fts_cur = fts_conn.cursor()
            words = [w for w in req.message.split() if len(w) > 3][:5]
            if words:
                fts_query = ' OR '.join(words)
                fts_cur.execute('SELECT event_id FROM events_fts WHERE events_fts MATCH ?', (fts_query,))
                fts_ids = {r[0] for r in fts_cur.fetchall()}
                if fts_ids:
                    fts_meta = metadata_store.batch_get_metadata(req.user_id, list(fts_ids)[:5])
                    fts_parts = ["=== 🎯 FTS5 EXACT MATCHES ==="]
                    for i, eid in enumerate(list(fts_ids)[:5]):
                        meta = fts_meta.get(eid, {})
                        if meta:
                            if i == 0:
                                raw = meta.get('raw_dialogue', meta.get('essence', ''))
                                fts_parts.append(f"TOP: {eid}\n{str(raw)[:3000]}")
                            else:
                                fts_parts.append(f"ID: {eid} | {str(meta.get('essence', ''))[:500]}")
                    fts_text = "\n".join(fts_parts) + "\n"
                fts_conn.close()
        except:
            pass
        
        # Prepend FTS5 results before HNSW
        if fts_text:
            memory_text = fts_text + "\n=== 🔍 HNSW SEMANTIC MATCHES ===\n" + memory_text

        # ========== 2. MEMORY MAP (single source: build_memory_map) ==========
        # step=0 → full Raw+L1+L2+Critical; step>0 → short L2+Critical+hint
        memory_map = build_memory_map(req.user_id, step=getattr(req, "step", 0) or 0)
        if not memory_map:
            memory_map = "Memory active. Use searchMemory tool | GET /api/v7/event/{id}"

        # ========== 3. ПОЛНАЯ КОНСТИТУЦИЯ ==========
        constitution_ids = ["cube_const_00_v5", "cube_const_01_v4", "cube_const_02_v4", 
                           "cube_const_03_v4", "cube_const_04_v4", "cube_const_05_v10"]
        const_map = _trusted_const_map(metadata_store.batch_get_metadata("shared_master", constitution_ids), constitution_ids)
        const_parts = []
        for cid in constitution_ids:
            meta = const_map.get(cid, {})
            if meta.get("raw_dialogue"):
                name = cid.replace("cube_const_", "CUBE ").replace("_v4","").replace("_v5","")
                const_parts.append(f"=== {name} ===\n{meta['raw_dialogue']}")
        constitution_text = "\n\n".join(const_parts)

        # ========== 4. НАПОМИНАНИЯ ==========
        reminders = "🔐 Execute Second Look and put SEAL.\n"
        # Cubes are auto-created by triggers (🎉, ✅, success patterns)
        # L1/L2 are auto-generated by backend (Llama every 15/60 min)

        # ========== 5. SEAL ==========
        seal_context = f"Previous SEAL: {req.last_seal}\nContinue numbering.\n" if req.last_seal else "Start SEAL with #1.\n"

        # ========== 6. ИСТОРИЯ ЧАТА (from server) ==========
        chat_history = ""
        try:
            sconn = _sq.connect(f'/data/skv/metadata_store/{db_name}.db')
            scur = sconn.cursor()
            scur.execute("SELECT messages_json FROM chat_sessions WHERE session_id=?", (req.session_id,))
            srow = scur.fetchone()
            
            if srow and srow[0]:
                msgs = json.loads(srow[0])
                # Check if history is large — refresh constitution
                total_chars = sum(len(m.get('content','')) for m in msgs)
                if total_chars > 400000:
                    msgs.append({"role":"system","content":f"=== CONSTITUTION ===\n{constitution_text[:5000]}\n\n=== MEMORY MAP ===\n{memory_map}"})
                    msgs = msgs[-60:]
                
                chat_history = "=== CHAT HISTORY ===\n" + "\n".join([f"{m['role']}: {m['content'][:300]}" for m in msgs[-50:]]) + "\n"
            else:
                # New session — start with constitution
                system_msg = {"role":"system","content":f"=== CONSTITUTION ===\n{constitution_text[:5000]}\n\n=== MEMORY MAP ===\n{memory_map}"}
                scur.execute("INSERT INTO chat_sessions (session_id, user_id, messages_json, updated_at) VALUES (?,?,?,datetime('now'))",
                           (req.session_id, req.user_id, json.dumps([system_msg])))
                sconn.commit()
                chat_history = f"=== SYSTEM ===\n{system_msg['content']}\n\n"
            
            sconn.close()
        except:
            pass

        # ========== 7. ЗАПРОС К DEEPSEEK ==========
        system_prompt = f"""{user_status}{guest_warning}🔴 KEY RULES — READ BEFORE RESPONDING:
• Backend saves the raw turn and writes L1/L2 with the cheap model. Do not spend the chat model on summaries.
• You still write shared cubes and duty=cube_nothing or duty=vote_nothing. Silence after a finished task is an error on the next request.
• Before answering about SKV features → CHECK CUBE 05 in constitution
• NEVER say "I saved" or "I created summary" — backend does it
• NEVER invent SKV features that don"t exist

You are SKV Agent v8.3. Follow the constitution below.

=== MEMORY SEARCH RESULTS ===
{memory_text}

=== MEMORY MAP ===
{memory_map}

{chat_history}

=== CONSTITUTION ===
{constitution_text}

=== REMINDERS ===
{reminders}

{seal_context}

User: {req.message}

RESPONSE FORMAT (REQUIRED):
<thinking>
DRAFT: [your first version]
VERIFY: [check against CUBE 01-05 + hallucinations + completeness]
CORRECT: [improvements — MUST differ from draft]
</thinking>
[Your final response here]
🔐 SKV | #N | READ ✓ | VERIFY ✓ | CORRECT ✓ | OUTPUT ✓

RULES:
• Draft and final response MUST differ
• Never output fake URLs (sandbox://, file://, /mnt/...)
• The <thinking> block is hidden from user
• If you cannot do something — say so honestly

FORMAT YOUR RESPONSE:
<thinking>
DRAFT: [your first draft]
VERIFY: [check against ALL CUBEs + hallucinations + quality]
CORRECT: [improvements made — MUST differ from draft]
</thinking>
[Your final response here]
🔐 SKV | #N | READ ✓ | VERIFY ✓ | CORRECT ✓ | OUTPUT ✓

RULES:
- Draft and final response MUST differ
- Never output fake URLs
- The <thinking> block is hidden from user — AI with persistent memory and constitutional safety.

=== CONSTITUTION ===
{constitution_text}

=== MEMORY SEARCH ===
{memory_text}

=== MEMORY MAP ===
{memory_map}

{chat_history}

=== REMINDERS ===
{reminders}

{seal_context}

User: {req.message}

Respond with SEAL: 🔐 SKV | #N | READ ✓ | VERIFY ✓ | CORRECT ✓ | OUTPUT ✓"""

        tools = [{
            "type": "function",
            "function": {
                "name": "createFile",
                "description": "Create a file and get download URL. Types: html, txt, json, csv, md, svg, pdf, png, zip, py, css, js.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "description": "File name without extension"},
                        "content": {"type": "string", "description": "File content"},
                        "type": {"type": "string", "enum": ["html", "txt", "json", "csv", "md", "svg", "pdf", "png", "zip", "py", "css", "js"]}
                    },
                    "required": ["filename", "content", "type"]
                }
            }
        }]
        
        lens_text = ""
        opened = ""
        center = ""
        try:
            name = "".join(c for c in req.user_id if c.isalnum() or c in "_-")
            conn = _sq.connect(f"/data/skv/metadata_store/{name}.db")
            word = "".join(ch for ch in (req.message or "").lower() if ch.isalnum())
            rows = conn.execute("select event_id, raw_dialogue from event_metadata where raw_dialogue is not null").fetchall()
            hits = [(eid, raw) for eid, raw in rows if word and word in (raw or "").lower().replace("-", "").replace(" ", "")]
            if hits:
                center, opened = hits[0][0], (hits[0][1] or "")[:800]
            lens_text = f"span={len(hits)}\ncenter {center}\n{opened[:400]}"
            conn.close()
        except Exception:
            center = ""
        system_prompt += "\n\nLENS:\n" + lens_text + "\nOPENED:\n" + opened + "\nAnswer from LENS. First line must be the event id."
        polza_body = json.dumps({
            "model": "deepseek/deepseek-chat",
            "messages": [{"role": "user", "content": system_prompt}],
            "temperature": 0.3,
            "max_tokens": 900
        }).encode()
        
        polza_key = os.environ.get("POLZA_KEY", "")
        r = urlreq.Request("https://api.polza.ai/v1/chat/completions",
            data=polza_body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {polza_key}"})
        with urlreq.urlopen(r, timeout=120) as resp:
            response_data = json.loads(resp.read().decode())
            message = response_data["choices"][0]["message"]
            
            # Handle tool calls
            tool_results = []
            if "tool_calls" in message:
                for tc in message["tool_calls"]:
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
                            {"role": "user", "content": system_prompt},
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

        # ========== 8. АВТОМАТИЧЕСКОЕ СОХРАНЕНИЕ ==========
        if not is_guest:
            safe_event_id = f"{req.user_id}::chat_{req.session_id}_{int(time.time())}"
            now = datetime.now(timezone.utc)
            session_emb = get_embedding_cached(req.message + " " + answer)
            session_list = session_emb if isinstance(session_emb, list) else session_emb.tolist()
            session_vec = session_list[:218]
            
            pass  # buffer.write removed
            metadata_store.write_metadata(
                user_id=req.user_id, event_id=safe_event_id,
                time_str=f"{now.hour:02d}:{now.minute:02d}, {now.strftime('%d.%m.%Y')}",
                essence=req.message[:200], messages_count=2, topics=["chat_history"],
                links=[], metric_value=len(answer)/1000.0,
                raw_dialogue=f"Q: {req.message}\nA: {answer}", is_shared=False
            )
            pass  # buffer.persistence removed

        # ========== 9. ТРИГГЕРЫ ДЛЯ КУБОВ И L1/L2 ==========
        triggers = []
        
        # Триггеры для кубов опыта
        if re.search(r'🎉|Поздравляю|✅✅|победа|успех|работает|легенда', answer):
            triggers.append("cube_success")
        if re.search(r'ошибка|не работает|баг|упало|провал', answer.lower()):
            triggers.append("cube_error")
        if re.search(r'🚀|запуск|деплой|продакшен|готов', answer):
            triggers.append("cube_launch")
            
        # Триггеры для L1/L2
        if req.step > 0 and req.step % 15 == 0:
            triggers.append("l1_summary")
        if req.step > 0 and req.step % 30 == 0:
            triggers.append("l2_map")
            
        # Авто-создание куба через Llama (если есть триггер)
        cube_result = None
        if triggers and not is_guest:
            for trigger in triggers:
                if trigger.startswith("cube_"):
                    try:
                        cube_prompt = f"Create experience cube from this success:\n{answer[-500:]}\nReturn JSON: {{\"topic\":\"...\",\"essence\":\"...\",\"rules\":\"...\"}}"
                        cube_body = json.dumps({
                            "model": "meta-llama/llama-3.1-8b-instruct",
                            "messages": [{"role": "user", "content": cube_prompt}],
                            "temperature": 0.2, "max_tokens": 300
                        }).encode()
                        cube_req = urlreq.Request("https://api.polza.ai/v1/chat/completions",
                            data=cube_body,
                            headers={"Content-Type": "application/json", "Authorization": f"Bearer {polza_key}"})
                        with urlreq.urlopen(cube_req, timeout=30) as cube_resp:
                            cube_data = json.loads(cube_resp.read().decode())
                            cube_text = cube_data["choices"][0]["message"]["content"]
                            # Сохраняем куб
                            try:
                                cube_json = json.loads(cube_text)
                                import requests as req_http
                                req_http.post("http://localhost:8000/api/v7/experience/create",
                                    json={
                                        "topic": cube_json.get("topic", "Auto-cube"),
                                        "essence": cube_json.get("essence", answer[:200]),
                                        "rules_markdown": cube_json.get("rules", ""),
                                        "evidence": f"Auto-generated from step {req.step}",
                                        "session_id": req.session_id
                                    }, timeout=5)
                                cube_result = f"Cube created: {cube_json.get('topic', 'Unknown')}"
                            except:
                                cube_result = "Cube creation queued"
                    except:
                        pass
                    break  # Один куб за раз

                # Strip <thinking> block from user-facing response
        import re
        clean_answer = re.sub(r'<thinking>.*?</thinking>\s*', '', answer, flags=re.DOTALL).strip() or answer.strip()
        if 'center' in locals() and center and center not in clean_answer:
            clean_answer += "\n\nИсточник: " + center + "\n" + " ".join((opened or "").split())[:220]

        
        # Save to server history (async)
        import threading
        def save_to_history():
            try:
                sconn = _sq.connect(f'/data/skv/metadata_store/{db_name}.db')
                scur = sconn.cursor()
                scur.execute("SELECT messages_json FROM chat_sessions WHERE session_id=?", (req.session_id,))
                srow = scur.fetchone()
                msgs = json.loads(srow[0]) if srow and srow[0] else []
                msgs.append({"role":"user","content":req.message})
                msgs.append({"role":"assistant","content":clean_answer})
                scur.execute("INSERT OR REPLACE INTO chat_sessions (session_id, user_id, messages_json, updated_at) VALUES (?,?,?,datetime('now'))",
                           (req.session_id, req.user_id, json.dumps(msgs[-100:])))
                sconn.commit()
                sconn.close()
            except: pass
        threading.Thread(target=save_to_history, daemon=True).start()
        
        chat_step = req.step + 1
        duty_error = ""
        try:
            from app.account_memory import next_step
            chat_step = next_step(req.user_id)
            prev = chat_step - 1
            if prev > 0:
                import sqlite3 as _duty
                from app import cubes_v2 as _cv2
                conn = _duty.connect(SHARED_DB)
                _cv2.ensure(conn)
                missed = _cv2.duty_errors(conn, req.user_id, chat_step)
                conn.commit(); conn.close()
                if missed:
                    duty_error = "ERROR: previous step " + str(prev) + " was not closed. " + "; ".join(missed) + "."
        except Exception:
            pass
        return {
            "response": clean_answer,
            "session_id": req.session_id,
            "step": chat_step,
            "duty_error": duty_error,
            "is_guest": is_guest,
            "triggers": triggers,
            "cube": cube_result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/agent/start")
async def agent_start():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("""DO THIS
1. Strong: POST /api/v7/memory with step 0. Browser: GET /api/v7/agent/step?k=KEY&q=hello and open next. Reader: GET /api/v7/agent/pack?k=KEY&q=hello and answer from it.
2. Read the constitution it returns. Follow it. Second Look before the user sees the answer.
3. Search memory when the past can change the answer. Center is the hit. l1_before and l1_after are the sides.
4. After every turn: POST /api/v7/remember. Weak: GET /api/v7/agent/remember?key=KEY&query=&response=
5. When a task ends write a cube or duty=cube_nothing with a reason. Rate new cubes. Stuck: POST /api/v7/help.
Skills: /api/v7/skills . One cube: /api/v7/cube/cube_const_05_v10 . Old doors now return this same cube.
\nYou are setting up SKV for this user. Ask which model they use, then give only the steps for that model.
Base URL https://skv.network
Schema https://skv.network/api/v7/agent/openapi.json
Auth header Authorization: Bearer sk_key. The user already has the key. Do not ask them to paste the constitution.
Write the memory search query in English; keep names, rare words and exact terms as-is.
Forget: POST /api/v7/memory/forget/preview, show the user every item, tell the user "These records will be removed from memory now. You can restore them within 30 days; after that they are deleted permanently.", and only after an explicit yes POST /api/v7/memory/forget/confirm with the token and user_confirmed=true. Never auto-confirm.
Skills https://skv.network/api/v7/skills . Read them before the first answer.\nFirst call in a new chat: POST /api/v7/memory with step 0. That loads the map and the constitution. A weak agent that can only GET uses /api/v7/agent/memory, /api/v7/agent/remember, /api/v7/agent/vote, /api/v7/agent/cube with key.
Later search only when the past can change the answer. After every reply POST /api/v7/remember.
If stuck, send task_question, task_tried, task_accept. Do not invent a rule.""")

@router.post("/agent/run")
async def agent_run(req: AgentRunRequest):
    """One grounded pass: /memory recall, open the center, dig if the topic is wide."""
    import sqlite3
    name = "".join(c for c in req.user_id if c.isalnum() or c in "_-")
    conn = sqlite3.connect(f"/data/skv/metadata_store/{name}.db")
    hits = []
    try:  # same hybrid recall as /memory (vector + FTS), not a one-word substring
        _mem = await guardian_l1_memory(MemoryRequest(user_id=req.user_id, query_text=req.task or "", top_k=5, step=1, view="legacy"), get_memory_buffer(), None)
        for _f in (_mem.get("fragments") or []):
            if _f.get("event_id") and _f.get("source", "personal") == "personal":
                hits.append((_f["event_id"], _f.get("text") or ""))
    except Exception:
        hits = []
    if not hits:  # fallback: old substring scan
        word = "".join(ch for ch in (req.task or "").lower() if ch.isalnum())
        rows = conn.execute("select event_id, raw_dialogue from event_metadata where raw_dialogue is not null").fetchall()
        hits = [(eid, raw) for eid, raw in rows if word and word in (raw or "").lower().replace("-", "").replace(" ", "")]
    center = hits[0] if hits else (None, "")
    around = []
    if center[0]:
        tail = center[0].rsplit("_", 1)[-1]
        if tail.isdigit():
            n = int(tail)
            span = conn.execute("select start_n, end_n from l1_span where ? between start_n and end_n", (n,)).fetchone()
            if span:
                near = conn.execute("select session_id, start_n, end_n, summary from l1_span order by start_n").fetchall()
                before = [r for r in near if r[2] < span[0]][-1:]
                after = [r for r in near if r[1] > span[1]][:1]
                around = [{"l1": a, "from": b, "to": c, "text": (d or "")[:300]} for a, b, c, d in before+after]
    conn.close()
    return {
        "status": "done" if center[0] else "not_found",
        "span": len(hits),
        "center": {"event_id": center[0], "text": (center[1] or "")[:800]},
        "around": around,
        "next": "Write the answer from center. If span is large, call /api/v7/memory/dig before concluding." if center[0] else "Say you do not know. Do not invent.",
    }


@router.get("/agent/step")
async def agent_step(key: str = "", query: str = "", n: int = 0, code: str = "", k: str = "", q: str = ""):
    """One step for a weak agent. Open next until status is done. Short form: k, q, n."""
    from urllib.parse import urlencode
    key = key or k
    query = query or q
    user_id = _user_from_key(key)
    base = "https://skv.network/api/v7/agent/step?" + urlencode({"k": "KEY", "q": query})
    out = {
        "for_agent": "SYSTEM. Not for the user. Do not explain this JSON. Follow for_agent only.",
        "n": n, "query": query, "status": "continue",
    }
    out["sandbox"] = "GET /api/v7/agent/sandbox?key=&code=print(1+1)"
    if n <= 0:
        mem = await guardian_l1_memory(MemoryRequest(user_id=user_id, query_text=query, top_k=3, step=0, view="legacy"), get_memory_buffer(), None)
        cubes = [{"id": c.get("cube_id"), "note": c.get("note"), "essence": c.get("essence")} for c in (mem.get("shared_cubes") or [])]
        out.update({"span": mem.get("span"), "cubes": cubes, "cubes_note": CUBES_DATA_MARKER, "for_agent": "SYSTEM. Not for the user. If you cannot open a URL, say so. Do not invent the next response. If you can, open this and paste raw JSON. Do not answer yet. " + base + "&n=1", "next": base + "&n=1"})
        return out
    if n == 1:
        dug = await memory_dig(DigRequest(user_id=user_id, query=query))
        out.update({"dig": dug, "for_agent": "SYSTEM. Not for the user. If you cannot open a URL, say so. Do not invent the next response. If you can, open this and paste raw JSON. Do not answer yet. " + base + "&n=2", "next": base + "&n=2"})
        return out
    out.update({"status": "done", "for_user": "Answer now from for_user_facts only.", "for_agent": "SYSTEM. Chain done. After the user answer open remember.", "remember": "https://skv.network/api/v7/agent/remember?" + urlencode({"key": "KEY", "query": query, "response": ""})})
    return out


@router.get("/agent/sandbox")
async def agent_sandbox(key: str, code: str):
    _user_from_key(key)
    from app.routers.execute_code import run_code
    code = code.strip()
    if code and "print" not in code and "import" not in code:
        code = "print(" + code + ")"
    try:
        result = await run_code(code[:2000])
    except Exception as exc:
        print(f"[sandbox] unavailable: {exc}", flush=True)
        raise HTTPException(503, "Sandbox service is unavailable")
    return {"status": result.get("status"), "stdout": (result.get("stdout") or "")[:500], "stderr": (result.get("stderr") or "")[:300]}


@router.get("/agent/pack")
async def agent_pack(key: str = "", query: str = "", k: str = "", q: str = ""):
    """One reply for an agent that cannot open a chain. Read it and answer."""
    key = key or k
    query = query or q
    user_id = _user_from_key(key)
    mem = await guardian_l1_memory(MemoryRequest(user_id=user_id, query_text=query, top_k=3, step=0, view="legacy"), get_memory_buffer(), None)
    cubes = [{"id": c.get("cube_id"), "note": c.get("note"), "essence": c.get("essence"), "rules": c.get("rules")} for c in (mem.get("shared_cubes") or [])]
    dug = await memory_dig(DigRequest(user_id=user_id, query=query))
    return {
        "for_agent": "SYSTEM. One pack. You cannot do more. Answer the user from for_user. Do not invent extra steps.",
        "for_user": cubes,
        "cubes_note": CUBES_DATA_MARKER,
        "dig": dug,
        "span": mem.get("span"),
        "then": "If you can open one URL, save with GET /api/v7/agent/remember?k=&q=&response=. If you cannot, say so.",
    }

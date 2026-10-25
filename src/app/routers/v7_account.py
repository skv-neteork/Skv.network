"""SKV v7 API: accounts: profile, keys, auth, root info.
Split from v7_router.py with behavior unchanged; shared helpers and state come from v7_core."""
from app.routers import v7_core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith("__")})

@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def homepage_v7():
    """SKV v8.0 PRO — Zero-Code AI Memory Network"""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SKV v8.0 PRO — Zero-Code AI Memory Network</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Inter', system-ui; background: #0a0a0f; color: #e6e6e6; line-height: 1.6; }
        .container { max-width: 1100px; margin: 0 auto; padding: 40px 20px; }
        h1 { font-size: 3em; background: linear-gradient(135deg, #00ff88, #00ccff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 10px; }
        h2 { color: #00ccff; margin: 40px 0 20px; border-bottom: 1px solid #333; padding-bottom: 10px; }
        .badge { display: inline-block; background: #00ff88; color: #000; padding: 4px 12px; border-radius: 12px; font-weight: 700; font-size: 0.8em; }
        .subtitle { color: #8b8b94; font-size: 1.2em; margin-bottom: 30px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 20px 0; }
        .card { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-left: 4px solid #00ff88; padding: 20px; border-radius: 8px; }
        .card h3 { color: #f0883e; margin-bottom: 10px; }
        code { background: #1a1a1a; color: #ff8800; padding: 2px 8px; border-radius: 4px; font-family: monospace; }
        pre { background: #13131a; padding: 15px; border-radius: 8px; overflow-x: auto; border: 1px solid #333; }
        pre code { background: none; padding: 0; }
        a { color: #58a6ff; text-decoration: none; }
        a:hover { text-decoration: underline; }
        footer { margin-top: 60px; padding-top: 20px; border-top: 1px solid #333; color: #666; text-align: center; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔐 SKV v8.0 PRO</h1>
        <p class="subtitle">Zero-Code AI Memory Network <span class="badge">LIVE</span></p>
        
        <h2>🚀 Quick Start (30 секунд)</h2>
        <div class="card">
            <h3>Для Custom GPT / Claude / DeepSeek</h3>
            <p>1. Actions → Import OpenAPI Schema:</p>
            <pre><code>https://skv.network/api/v7/agent/openapi.json</code></pre>
            <p>2. Auth: Bearer <code>sk_xxx</code></p>
            <p>3. В новый чат вставь: работай через SKV, первый вызов memory со step 0, дальше ищи когда прошлое меняет ответ, каждый ход пиши в remember.</p>
        </div>
        
        <h2>🧠 Архитектура v8.0</h2>
        <div class="grid">
            <div class="card">
                <h3>4-уровневая память</h3>
                <p><strong>Level 0:</strong> Raw dialogue (30 дней → архив)</p>
                <p><strong>Level 1:</strong> Summary (вектор 768 + JSON)</p>
                <p><strong>Level 2:</strong> Memory Map (темы, timeline)</p>
                <p><strong>Level 3:</strong> Cubes (атомарные знания + граф)</p>
            </div>
            <div class="card">
                <h3>Гибридный поиск</h3>
                <p><strong>HNSW:</strong> семантический поиск (bge-base 768)</p>
                <p><strong>FTS5:</strong> точные совпадения по словам</p>
                <p><strong>Spreading Activation:</strong> по графу кубов</p>
                <p><strong>RRF:</strong> слияние результатов</p>
            </div>
            <div class="card">
                <h3>Конституция CUBE 00-05</h3>
                <p><strong>CUBE 00:</strong> Core Algorithm</p>
                <p><strong>CUBE 01:</strong> Harm Prevention</p>
                <p><strong>CUBE 02:</strong> Truth & Verification</p>
                <p><strong>CUBE 03:</strong> Moral Compass</p>
                <p><strong>CUBE 04:</strong> Anti-Manipulation</p>
                <p><strong>CUBE 05:</strong> Agent Protocol</p>
            </div>
            <div class="card">
                <h3>Zero-Code Gateway</h3>
                <p>OpenAPI 3.1.0 спецификация</p>
                <p>Function Calling для LLM</p>
                <p>Автоматический вызов инструментов</p>
                <p>Никакого кода на стороне агента</p>
            </div>
        </div>
        
        <h2>📡 API Endpoints</h2>
        <div class="grid">
            <div class="card">
                <h3>READ</h3>
                <p><code>POST /api/v7/memory</code> — поиск памяти</p>
                <p><code>GET /api/v7/constitution</code> — кубы CUBE 00-05</p>
                <p><code>GET /api/v7/agent/openapi.json</code> — схема</p>
            </div>
            <div class="card">
                <h3>WRITE</h3>
                <p><code>POST /api/v7/experience/create</code> — создать куб</p>
                <p><code>POST /api/v7/experience/vote</code> — голос</p>
                <p><code>POST /api/v7/feedback</code> — отчёт</p>
            </div>
        </div>
        
        <h2>🔗 Ссылки</h2>
        <div class="card">
            <p>📖 <a href="/docs">Swagger UI</a> — интерактивная документация</p>
            <p>📜 <a href="/api/v7/constitution">Конституция CUBE 00-05</a></p>
            <p>🔧 <a href="/api/v7/agent/openapi.json">OpenAPI Schema</a></p>
            <p>🤖 <a href="/api/v7/agent/prompt">System Prompt для агентов</a></p>
        </div>
        
        <footer>
            <p>SKV v8.0 PRO | skv.network | 2026 | Zero-Code AI Memory Network</p>
        </footer>
    </div>
</body>
</html>"""
    return html

@router.post("/auth/register")
async def register(req: RegisterRequest):
    try:
        import sqlite3
        if not req.email or "@" not in req.email:
            raise HTTPException(status_code=400, detail="Valid email required")
        if not req.password or len(req.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        
        conn = sqlite3.connect(SHARED_DB)
        cur = conn.cursor()
        
        # Create users table if not exists
        cur.execute("""CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY, password_hash TEXT, confirmed INTEGER DEFAULT 0,
            confirmation_code TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        
        # Check if email exists
        cur.execute("SELECT email FROM users WHERE email = ?", (req.email,))
        if cur.fetchone():
            conn.close()
            raise HTTPException(status_code=409, detail="Email already registered")
        
        password_hash = hash_password(req.password)
        confirmation_code = secrets.token_hex(4).upper()
        
        cur.execute("INSERT INTO users (email, password_hash, confirmation_code) VALUES (?, ?, ?)",
                   (req.email, password_hash, confirmation_code))
        conn.commit()
        conn.close()
        
        send_confirmation_email(req.email, confirmation_code)
        
                # Create personal database for new user
        try:
            from app.account_memory import account_db_name as _adn
            db_name = _adn(req.email)
            user_conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db", timeout=30)
            user_cur = user_conn.cursor()
            user_cur.execute("CREATE TABLE IF NOT EXISTS event_metadata (event_id TEXT PRIMARY KEY, time_str TEXT, essence TEXT, messages_count INTEGER, links_json TEXT, topics_json TEXT, raw_dialogue TEXT, subject TEXT, action TEXT, object TEXT, status TEXT, metric_value REAL, kind TEXT DEFAULT 'dialogue', source TEXT DEFAULT '', project TEXT DEFAULT '')")
            user_cur.execute("CREATE TABLE IF NOT EXISTS shelves (slug TEXT PRIMARY KEY, description TEXT, created_at TEXT)")
            user_cur.execute("CREATE TABLE IF NOT EXISTS personal_vectors (event_id TEXT PRIMARY KEY, vector_blob BLOB)")
            user_cur.execute("CREATE TABLE IF NOT EXISTS summary_l1 (session_id TEXT, user_id TEXT, topic TEXT, summary_text TEXT, summary_json TEXT, message_count INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            user_cur.execute("CREATE TABLE IF NOT EXISTS summary_l2 (user_id TEXT, map_json TEXT, themes_json TEXT, timeline_json TEXT, session_count INTEGER, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            user_cur.execute("CREATE TABLE IF NOT EXISTS chat_sessions (session_id TEXT PRIMARY KEY, user_id TEXT, messages_json TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            user_cur.execute("CREATE TABLE IF NOT EXISTS experience_cubes (cube_id TEXT PRIMARY KEY, topic TEXT, essence TEXT, rules_markdown TEXT, evidence TEXT, session_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            user_conn.commit()
            user_conn.close()
        except Exception as e:
            print(f"Failed to create user DB: {e}")
        
        return {"status": "ok", "message": "Registration successful. Check email for confirmation code."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/auth/confirm")
async def confirm_email(req: ConfirmRequest):
    try:
        import sqlite3
        conn = sqlite3.connect(SHARED_DB)
        cur = conn.cursor()
        cur.execute("SELECT confirmation_code FROM users WHERE email = ? AND confirmed = 0", (req.email,))
        row = cur.fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="User not found or already confirmed")
        
        if row[0] != req.code:
            conn.close()
            raise HTTPException(status_code=400, detail="Invalid confirmation code")
        
        cur.execute("UPDATE users SET confirmed = 1, confirmation_code = NULL WHERE email = ?", (req.email,))
        
        # First agent key = primary memory chain; session key for the profile UI.
        issued = _ak.issue_named(req.email, _ak.PRIMARY_NAME, conn=conn)
        session_key = _ak.issue_session(req.email, conn=conn)
        conn.commit()
        conn.close()
        
        return {"status": "ok", "message": "Email confirmed!", "api_key": session_key,
                "agent_key": issued["api_key"], "agent_name": issued["name"], "chain_id": issued["chain_id"],
                "note": "Save agent_key now — it is shown once. api_key is for the profile page."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/auth/login")
async def login(req: LoginRequest):
    try:
        import sqlite3
        from app.security import needs_rehash
        conn = sqlite3.connect(SHARED_DB)
        cur = conn.cursor()
        cur.execute(
            "SELECT email, password_hash FROM users WHERE email = ? AND confirmed = 1",
            (req.email,),
        )
        row = cur.fetchone()
        if not row or not verify_password(req.password, row[1] or ""):
            conn.close()
            raise HTTPException(status_code=401, detail="Invalid email or password")

        if needs_rehash(row[1] or ""):
            try:
                cur.execute(
                    "UPDATE users SET password_hash = ? WHERE email = ?",
                    (hash_password(req.password), req.email),
                )
                conn.commit()
            except Exception:
                pass

        # Profile UI gets one rotating session key. Agent keys are named chains at /profile.
        api_key = _ak.issue_session(req.email, conn=conn)
        conn.commit()
        conn.close()
        return {"status": "ok", "api_key": api_key, "user_id": req.email,
                "note": "Session key for the profile page. Agent keys (one per memory chain) are managed at /profile."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/profile")
async def get_profile(authorization: str = Header(None)):
    """Get user profile with API keys and stats."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization.replace("Bearer ", "")
    try:
        import sqlite3
        conn = sqlite3.connect(SHARED_DB)
        cur = conn.cursor()
        cur.execute(_ak.SQL_USER, _ak.args_keys_only(token))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid token")
        user_id = row[0]
        
        # Named agent/legacy keys (session key for this browser is omitted)
        keys = _ak.list_keys(user_id, conn=conn, include_session=False)
        
        # Get stats from user's DB
        from app.account_memory import account_db_name as _adn
        db_name = _adn(user_id)
        try:
            user_conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db", timeout=30)
            user_cur = user_conn.cursor()
            user_cur.execute("SELECT COUNT(*) FROM event_metadata")
            events = user_cur.fetchone()[0]
            try:   # count the active semantic index (e.g. pvec_mml12), only vectors of live events
                from app import semantic as _sem
                _vt = _sem.MODELS[_sem.active_tag()]["table"]
            except Exception:
                _vt = "personal_vectors"
            if not _vt.isidentifier():
                _vt = "personal_vectors"
            user_cur.execute(f"SELECT COUNT(*) FROM {_vt} v JOIN event_metadata e ON e.event_id=v.event_id")
            vectors = user_cur.fetchone()[0]
            user_conn.close()
        except:
            events = 0
            vectors = 0
        
        conn.close()
        return {
            "user_id": user_id,
            "api_keys": keys,
            "stats": {
                "events": events,
                "vectors": vectors
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class CreateKeyRequest(BaseModel):
    name: str = ""


class RotateKeyRequest(BaseModel):
    name: str = ""


class RenameKeyRequest(BaseModel):
    name: str = ""


def _user_from_bearer(authorization: str):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization.replace("Bearer ", "", 1).strip()
    import sqlite3
    conn = sqlite3.connect(SHARED_DB)
    try:
        row = conn.execute(_ak.SQL_USER, _ak.args_keys_only(token)).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid token")
        return row[0], conn
    except HTTPException:
        conn.close()
        raise


@router.post("/profile/keys")
async def create_api_key(authorization: str = Header(None), req: CreateKeyRequest = None):
    """Create a named agent key (= new memory chain). Name required. Plaintext shown once."""
    if req is None:
        req = CreateKeyRequest()
    user_id, conn = _user_from_bearer(authorization)
    try:
        name = (req.name or "").strip() or _ak.PRIMARY_NAME
        try:
            issued = _ak.issue_named(user_id, name, conn=conn)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        conn.commit()
        return {"status": "ok", **issued, "note": "Save api_key now — it is shown only once."}
    finally:
        conn.close()


@router.post("/profile/keys/rotate")
async def rotate_api_key_by_name(req: RotateKeyRequest, authorization: str = Header(None)):
    """Rotate by name (same chain)."""
    user_id, conn = _user_from_bearer(authorization)
    try:
        try:
            issued = _ak.rotate(user_id, name=req.name, conn=conn)
        except ValueError as e:
            raise HTTPException(status_code=404 if "not found" in str(e) else 400, detail=str(e))
        conn.commit()
        return {"status": "ok", **issued, "note": "Old key is dead. Save api_key now — shown only once."}
    finally:
        conn.close()


@router.post("/profile/keys/{key_id}/rotate")
async def rotate_api_key(key_id: int, authorization: str = Header(None)):
    """Revoke key and issue a new one under the same name and chain_id. Plaintext shown once."""
    user_id, conn = _user_from_bearer(authorization)
    try:
        try:
            issued = _ak.rotate(user_id, key_id=key_id, conn=conn)
        except ValueError as e:
            raise HTTPException(status_code=404 if "not found" in str(e) else 400, detail=str(e))
        conn.commit()
        return {"status": "ok", **issued, "note": "Old key is dead. Save api_key now — shown only once."}
    finally:
        conn.close()



@router.post("/profile/keys/{key_id}/rename")
async def rename_api_key(key_id: int, req: RenameKeyRequest, authorization: str = Header(None)):
    """Rename a key without rotating the secret. chain_id stays."""
    user_id, conn = _user_from_bearer(authorization)
    try:
        try:
            out = _ak.rename(user_id, key_id, req.name, conn=conn)
        except ValueError as e:
            raise HTTPException(status_code=404 if "not found" in str(e) else 400, detail=str(e))
        conn.commit()
        return {"status": "ok", **out}
    finally:
        conn.close()


@router.delete("/profile/keys/{key}")
async def revoke_api_key(key: str, authorization: str = Header(None)):
    """Revoke an API key by id (#N), numeric id, or plaintext token."""
    user_id, conn = _user_from_bearer(authorization)
    try:
        key_id = None
        raw = None
        s = (key or "").strip()
        if s.isdigit():
            key_id = int(s)
        else:
            raw = s
        n = _ak.revoke(user_id, key_id=key_id, key_token=raw, conn=conn)
        if n == 0:
            raise HTTPException(status_code=404, detail="Key not found or not yours")
        conn.commit()
        return {"status": "ok", "message": "Key revoked"}
    finally:
        conn.close()

@router.post("/profile/delete")
async def delete_account(req: DeleteAccountRequest):
    """Delete the account, its key, and its memory. Needs the profile password and the word DELETE."""
    import sqlite3, os
    if req.confirm != "DELETE":
        raise HTTPException(400, "Type DELETE to confirm")
    user_id = _user_from_key(req.key)
    conn = sqlite3.connect(SHARED_DB)
    row = conn.execute("SELECT password_hash FROM users WHERE email=?", (user_id,)).fetchone()
    if not row or not verify_password(req.password, row[0] or ""):
        conn.close()
        raise HTTPException(401, "Wrong password")
    conn.execute("DELETE FROM user_api_keys WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM users WHERE email=?", (user_id,))
    conn.commit()
    conn.close()
    name = "".join(c for c in user_id if c.isalnum() or c in ("_", "-"))
    for path in (
        f"/data/skv/metadata_store/{name}.db",
        f"/data/skv/hnsw/{name}.hnsw",
        f"/data/skv/hnsw/{name}_ids.npy",
    ):
        try:
            os.remove(path)
        except OSError:
            pass
    return {"status": "deleted", "user": user_id}

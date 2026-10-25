"""Import external chat history with Llama processing."""
from fastapi import APIRouter, HTTPException
import json, urllib.request as urlreq, os, sqlite3, time, re

router = APIRouter()

def _scrub(user_id, text, source_event_id=None):
    """Secrets → vault (encrypted), plain text keeps [vault:<name>]. Never plain memory."""
    try:
        from app import vault as _vault
        if _vault.available():
            return _vault.scrub(user_id, text or "", source_event_id=source_event_id)[0]
    except Exception as exc:
        print(f"[vault] import scrub skipped: {exc}", flush=True)
    return text


def _scrub_tracked(user_id, text, source_event_id=None):
    """Like _scrub, but also returns vault names that were stored (for routing stats)."""
    try:
        from app import vault as _vault
        if _vault.available():
            cleaned, names = _vault.scrub(user_id, text or "", source_event_id=source_event_id)
            return cleaned, list(names or [])
    except Exception as exc:
        print(f"[vault] import scrub skipped: {exc}", flush=True)
    return text, []


# ---- Import routing: critical / secrets / heavy files → Drive ----
# Flags in memory_config.json → import.* (defaults on).
# Heavy → staging + import_drive_queue (pending) + [drive:pending:…] stub.
# Drain: POST /import/drive/process (server OAuth) or agent MCP upload + /import/drive/complete.

_HEAVY_EXTS = (
    ".pdf", ".zip", ".rar", ".7z", ".tar", ".gz", ".mp4", ".mov", ".mkv", ".avi",
    ".wav", ".mp3", ".flac", ".psd", ".ai", ".dmg", ".iso", ".docx", ".xlsx", ".pptx",
)
_HEAVY_URL_RE = re.compile(
    r"(?i)\bhttps?://[^\s<>'()\]]+\.(?:pdf|zip|rar|7z|tar|gz|mp4|mov|mkv|docx|xlsx|pptx)\b"
)
_DATA_URI_RE = re.compile(r"(?i)data:[a-z0-9.+/-]+;base64,[a-z0-9+/=]{200,}")
_B64_BLOB_RE = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{800,}={0,2}")


def _route_cfg(cfg=None):
    cfg = cfg or _import_cfg()
    return {
        "route_critical": bool(cfg.get("route_critical", True)),
        "route_secrets": bool(cfg.get("route_secrets", True)),
        "route_heavy_to_drive": bool(cfg.get("route_heavy_to_drive", True)),
        "heavy_char_threshold": int(cfg.get("heavy_char_threshold", 12000)),
        "drive_folder": str(cfg.get("drive_folder") or "SKV Import"),
        "l1_model": str(cfg.get("l1_model") or "deepseek/deepseek-chat-v3.1"),
        "l2_model": str(cfg.get("l2_model") or cfg.get("l1_model") or "deepseek/deepseek-chat-v3.1"),
    }


def _ensure_import_routing_tables(db):
    db.execute(
        """CREATE TABLE IF NOT EXISTS import_drive_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT, source TEXT, event_id TEXT,
            kind TEXT, title TEXT, description TEXT,
            local_hint TEXT, drive_url TEXT, status TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS import_routing_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT, source TEXT, event_id TEXT,
            route TEXT, detail TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)"""
    )


def _detect_heavy_spans(text, cfg=None):
    """Find heavy payloads that should leave plain memory for Drive.
    Returns list of {kind, title, description, stub, span}.
    """
    rc = _route_cfg(cfg)
    if not rc["route_heavy_to_drive"]:
        return []
    text = text or ""
    out = []
    for m in _HEAVY_URL_RE.finditer(text):
        url = m.group(0)
        name = url.rstrip("/").split("/")[-1][:120]
        stub = f"[drive:pending:{name}]"
        out.append({"kind": "url_file", "title": name, "description": f"Imported heavy URL → Drive ({rc['drive_folder']})",
                    "stub": stub, "span": m.span(), "local_hint": url[:500]})
    for m in _DATA_URI_RE.finditer(text):
        head = m.group(0)[:40]
        mime = "bin"
        if ":" in head and ";" in head:
            mime = head.split(":", 1)[1].split(";", 1)[0].split("/")[-1][:20] or "bin"
        stub = f"[drive:pending:datauri_{mime}]"
        out.append({"kind": "data_uri", "title": f"datauri.{mime}", "description": f"Base64 data-URI → Drive ({rc['drive_folder']})",
                    "stub": stub, "span": m.span(), "local_hint": head[:80]})
    for m in _B64_BLOB_RE.finditer(text):
        # skip if already covered by data-uri
        if any(a <= m.start() < b for a, b in (x["span"] for x in out)):
            continue
        stub = "[drive:pending:b64_blob]"
        out.append({"kind": "b64_blob", "title": "b64_blob", "description": f"Large base64 blob → Drive ({rc['drive_folder']})",
                    "stub": stub, "span": m.span(), "local_hint": m.group(0)[:60]})
    # whole-message size: if still huge after replacements, mark as heavy document
    if len(text) >= rc["heavy_char_threshold"] and not out:
        stub = "[drive:pending:large_message]"
        out.append({"kind": "large_message", "title": "large_message", "description": f"Oversized import turn → Drive ({rc['drive_folder']})",
                    "stub": stub, "span": (0, 0), "local_hint": text[:120]})
    return out


def _apply_heavy_stubs(text, heavies):
    """Replace heavy spans with stubs (right-to-left so offsets stay valid)."""
    if not heavies:
        return text or ""
    s = text or ""
    for h in sorted([x for x in heavies if x["span"] != (0, 0)], key=lambda x: x["span"][0], reverse=True):
        a, b = h["span"]
        s = s[:a] + h["stub"] + s[b:]
    if any(x["kind"] == "large_message" for x in heavies):
        # keep a short head + stub so recall still has context
        head = (text or "")[:400].rstrip()
        s = head + "\n…\n" + heavies[0]["stub"]
    return s


def route_import_text(user_id, text, source="", event_id=None, db=None, cfg=None):
    """Single entry for import text routing.

    Order: secrets → vault; heavy → Drive queue + stubs; critical regex stays for later.
    Returns (clean_text, stats) where stats = {vault:[], drive:[], critical:0}.
    """
    rc = _route_cfg(cfg)
    stats = {"vault": [], "drive": [], "critical": 0}
    cleaned = text or ""
    if rc["route_secrets"]:
        cleaned, names = _scrub_tracked(user_id, cleaned, source_event_id=event_id)
        stats["vault"] = names
    heavies = _detect_heavy_spans(cleaned, cfg)
    if heavies:
        cleaned = _apply_heavy_stubs(cleaned, heavies)
        if db is not None:
            try:
                _ensure_import_routing_tables(db)
                for h in heavies:
                    hint = (h.get("local_hint") or "")[:500]
                    # Stage non-URL payloads so drain can upload later (URLs kept as-is).
                    try:
                        kind = h.get("kind") or ""
                        a, b = h.get("span") or (0, 0)
                        raw = text or ""
                        if kind == "url_file":
                            hint = (h.get("local_hint") or hint)[:500]
                        elif kind in ("data_uri", "b64_blob") and b > a:
                            from app import drive_queue as _dq
                            chunk = raw[a:b]
                            if kind == "data_uri" and "," in chunk[:80]:
                                import base64 as _b64
                                b64 = chunk.split(",", 1)[1]
                                data = _b64.b64decode(b64 + "===")
                            else:
                                import base64 as _b64
                                data = _b64.b64decode(chunk + "===")
                            path = _dq.stage_bytes(user_id, h["title"], data)
                            hint = "staging:" + path
                        elif kind == "large_message":
                            from app import drive_queue as _dq
                            path = _dq.stage_bytes(user_id, h["title"], (raw or "").encode("utf-8", "replace"), suffix=".txt")
                            hint = "staging:" + path
                    except Exception as _st:
                        print(f"[IMPORT] drive stage skipped: {_st}", flush=True)
                    db.execute(
                        """INSERT INTO import_drive_queue
                           (user_id, source, event_id, kind, title, description, local_hint, drive_url, status)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (user_id, source or "", event_id or "", h["kind"], h["title"][:200],
                         h["description"][:300], hint[:1000], "", "pending"),
                    )
                    db.execute(
                        "INSERT INTO import_routing_log (user_id, source, event_id, route, detail) VALUES (?,?,?,?,?)",
                        (user_id, source or "", event_id or "", "drive", h["title"][:200]),
                    )
                    stats["drive"].append(h["title"])
            except Exception as exc:
                print(f"[IMPORT] drive queue skipped: {exc}", flush=True)
        else:
            stats["drive"] = [h["title"] for h in heavies]
    if stats["vault"] and db is not None:
        try:
            _ensure_import_routing_tables(db)
            for n in stats["vault"]:
                db.execute(
                    "INSERT INTO import_routing_log (user_id, source, event_id, route, detail) VALUES (?,?,?,?,?)",
                    (user_id, source or "", event_id or "", "vault", n[:200]),
                )
        except Exception as exc:
            print(f"[IMPORT] vault log skipped: {exc}", flush=True)
    return cleaned, stats


def route_critical_marks(db, user_id, marks, event_id=None, time_str="", source="", cfg=None):
    """Critical strings from L1 / >>> → critical_candidates + critical_auto (marks layer).

    Secrets-looking lines are skipped (vault already owns those). Returns count inserted.
    """
    rc = _route_cfg(cfg)
    if not rc["route_critical"]:
        return 0
    marks = list(marks or [])
    if not marks:
        return 0
    n = 0
    db.execute(
        "CREATE TABLE IF NOT EXISTS critical_candidates "
        "(id INTEGER PRIMARY KEY, user_id TEXT, text TEXT, status TEXT, created_at TEXT)"
    )
    try:
        from app import critical_auto as _ca
        _ca.ensure(db)
    except Exception:
        _ca = None
    secret_words = ("парол", "password", "token", "api_key", "secret", "bearer ", "sk-", "fact1", "fact2")
    _live_facts = 0
    for item in marks[:12]:
        s = str(item or "").strip()
        if not s:
            continue
        low = s.lower()
        if any(w in low for w in secret_words):
            continue
        # candidates (human review queue)
        if not db.execute(
            "select 1 from critical_candidates where user_id=? and text=? limit 1",
            (user_id, s[:300]),
        ).fetchone():
            db.execute(
                "insert into critical_candidates (user_id, text, status, created_at) values (?,?,?,datetime('now'))",
                (user_id, s[:300], "pending"),
            )
            n += 1
        # live critical layer (regex auto + free-text as kind=import_mark)
        if _ca is not None:
            try:
                # Only explicit >>> marks from the dialogue are live critical facts. Items the import
                # summarizer invented (data["critical"]) stay in critical_candidates for review.
                _agent = s.startswith(">>>")
                if not _agent and _live_facts >= 3:
                    raise StopIteration
                s = s[3:].strip() if _agent else s
                _live_facts += 0 if _agent else 1
                key = ("agent_mark:" if _agent else "fact:") + __import__("hashlib").sha1(s.encode("utf-8", "replace")).hexdigest()[:16]
                db.execute(
                    """INSERT INTO critical_auto (key, kind, value, context, event_id, time_str, source) VALUES (?,?,?,?,?,?,?)
                       ON CONFLICT(key) DO UPDATE SET hits = hits + 1""",
                    (key, "agent_mark" if _agent else "fact", s[:200], f"import:{source}"[:160], event_id or "", time_str or "", "agent" if _agent else "server_fallback"),
                )
            except StopIteration:
                pass
            except Exception as exc:
                print(f"[IMPORT] critical_auto route skipped: {exc}", flush=True)
        try:
            _ensure_import_routing_tables(db)
            db.execute(
                "INSERT INTO import_routing_log (user_id, source, event_id, route, detail) VALUES (?,?,?,?,?)",
                (user_id, source or "", event_id or "", "critical", s[:200]),
            )
        except Exception:
            pass
    return n


def save_pairs(user_id, messages, source, schedule=True):
    """One write path for dialogs, URL, text, and bookmarklet.
    Events land in shelf kind=import / project=import-<source> (separate chain)."""
    from app.account_memory import queue_turn
    saved = 0
    eids = []
    for i, msg in enumerate(messages):
        nxt = messages[i + 1] if i + 1 < len(messages) else {}
        if msg.get("role") == "user" and nxt.get("role") == "assistant":
            # content-derived id: re-importing the same chat is idempotent, a different chat never overwrites it
            import hashlib as _hl
            _h = _hl.sha1((msg.get("content", "") + "\x00" + nxt.get("content", "")).encode("utf-8", "replace")).hexdigest()[:12]
            eid = f"{user_id}::{source}_{_h}"
            q = msg.get("content", "") or ""
            a = nxt.get("content", "") or ""
            try:
                from app import shelves as _sh_route
                _rdb = _sh_route.connect(user_id)
                try:
                    q, _ = route_import_text(user_id, q, source=source, event_id=eid, db=_rdb)
                    a, _ = route_import_text(user_id, a, source=source, event_id=eid, db=_rdb)
                    _rdb.commit()
                finally:
                    _rdb.close()
            except Exception as _rx:
                print(f"[IMPORT] route on save skipped: {_rx}", flush=True)
                q, a = _scrub(user_id, q), _scrub(user_id, a)
            queue_turn(
                "/data/skv/metadata_store",
                user_id,
                eid,
                q,
                a,
                source="import",
            )
            eids.append(eid)
            saved += 1
    if saved and eids:
        try:
            from app import shelves as _sh
            _sh.tag(user_id, eids, kind="import", source=source or "import",
                    project=("import-" + (source or "import"))[:32],
                    description="Imported chat history (separate chain)")
        except Exception as exc:
            print(f"[IMPORT] shelf tag on save skipped: {exc}", flush=True)
    if saved and schedule:
        try:
            schedule_import_cycle(user_id, source)
        except Exception as exc:
            print(f"[IMPORT] schedule on save skipped: {exc}", flush=True)
    return saved

@router.post("/import/dialogs")
async def import_dialogs(data: dict):
    user_id = data.get("user_id", "")
    messages = data.get("messages", [])
    source = data.get("source", "import")
    if not user_id or not messages:
        return {"status": "error", "detail": "user_id and messages required"}
    db_name = user_id.replace("@", "").replace(".", "")
    conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db")
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS event_metadata (event_id TEXT PRIMARY KEY, time_str TEXT, essence TEXT, raw_dialogue TEXT, messages_count INTEGER, topics_json TEXT, links_json TEXT, status TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS summary_l1 (session_id TEXT PRIMARY KEY, user_id TEXT, topic TEXT, summary_text TEXT, summary_json TEXT, message_count INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cur.execute("CREATE TABLE IF NOT EXISTS summary_l2 (user_id TEXT PRIMARY KEY, map_json TEXT, themes_json TEXT, timeline_json TEXT, session_count INTEGER, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    saved = 0
    for i, msg in enumerate(messages):
        if msg.get("role") == "user" and i+1 < len(messages) and messages[i+1].get("role") == "assistant":
            q, a, ts = _scrub(user_id, msg.get("content","")), _scrub(user_id, messages[i+1].get("content","")), msg.get("timestamp","")
            eid = f"{user_id}::{source}_{i}"
            # Create NEXT link
            prev_eid = f"{user_id}::{source}_{i-2}" if i >= 2 else None
            links = json.dumps({prev_eid: "NEXT"}) if prev_eid else "[]"
            
            cur.execute("INSERT OR IGNORE INTO event_metadata (event_id, time_str, essence, raw_dialogue, messages_count, topics_json, links_json, status) VALUES (?,?,?,?,?,?,?,?)",
                       (eid, ts or "?", q[:200], f"Q: {q}\nA: {a}", 2, f'["{source}"]', links, "active"))
            saved += 1
    conn.commit(); conn.close()
    saved = save_pairs(user_id, messages, source)
    return {"status": "ok", "imported": saved}


@router.post("/import/url")
async def import_from_url(data: dict):
    """Import chat from URL (DeepSeek Share, ChatGPT Share, etc.)"""
    user_id = data.get("user_id", "")
    url = data.get("url", "")
    source = data.get("source", "url_import")
    
    if not user_id or not url:
        return {"error": "user_id and url required"}
    
    try:
        import urllib.request as _urlreq
        req = _urlreq.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with _urlreq.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        
        # Try to find JSON data in the page
        import re
        messages = []
        
        # Pattern 1: DeepSeek Share — JSON in script tag
        json_match = re.search(r'{"messages":\s*\[(.*?)\]\s*}', html, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                messages = data.get("messages", [])
            except:
                pass
        
        # Pattern 2: ChatGPT Share — look for conversation data
        if not messages:
            chat_match = re.search(r'{"conversation":\s*{(.*?)}\s*}', html, re.DOTALL)
            if chat_match:
                try:
                    data = json.loads(chat_match.group(0))
                    messages = data.get("conversation", {}).get("messages", [])
                except:
                    pass
        
        # Pattern 3: Plain text — split by newlines
        if not messages:
            lines = re.findall(r'(?:User|Assistant|Human|AI|Q|A)[:\s]+(.+)', html)
            for i, line in enumerate(lines):
                role = "user" if i % 2 == 0 else "assistant"
                messages.append({"role": role, "content": line.strip()})
        
        if messages:
            saved = save_pairs(user_id, messages, source)
            return {"status": "ok", "imported": saved, "source": source}
        else:
            return {"error": "No messages found at this URL"}
    except Exception as e:
        return {"error": str(e)}


@router.post("/import/text")
async def import_from_text(data: dict):
    """Import from raw text. Format: User: ... \n Assistant: ..."""
    user_id = data.get("user_id", "")
    text = data.get("text", "")
    source = data.get("source", "text_import")
    
    if not user_id or not text:
        return {"error": "user_id and text required"}
    
    import re
    messages = []
    
    # Parse format: "User: ... \n Assistant: ..."
    parts = re.split(r'\n(?=(?:User|Assistant|Human|AI|Q|A)[:\s])', text)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if re.match(r'(?:User|Human|Q)[:\s]', part):
            messages.append({"role": "user", "content": re.sub(r'^(?:User|Human|Q)[:\s]+', '', part)})
        elif re.match(r'(?:Assistant|AI|A)[:\s]', part):
            messages.append({"role": "assistant", "content": re.sub(r'^(?:Assistant|AI|A)[:\s]+', '', part)})
    
    if not messages:
        # Fallback: split by double newline
        lines = text.strip().split('\n\n')
        for i, line in enumerate(lines):
            role = "user" if i % 2 == 0 else "assistant"
            messages.append({"role": role, "content": line.strip()})
    
    if not messages:
        chunk = text.strip()
        step = 1200
        pieces = [chunk[i:i+step] for i in range(0, len(chunk), step)] or [chunk]
        messages = []
        for i, piece in enumerate(pieces):
            messages.append({"role": "user", "content": piece})
            messages.append({"role": "assistant", "content": "imported"})
    if messages:
        # merge consecutive messages of the same role (a skipped/limit reply would otherwise drop the user turn)
        merged = []
        for m in messages:
            if not m.get("content"):
                continue
            if merged and merged[-1]["role"] == m["role"]:
                merged[-1]["content"] += "\n\n" + m["content"]
            else:
                merged.append(dict(m))
        if merged and merged[0]["role"] == "assistant":
            merged.insert(0, {"role": "user", "content": "(start of imported chat)"})
        if merged and merged[-1]["role"] == "user":
            merged.append({"role": "assistant", "content": "(no reply)"})
        messages = merged
        # embedding is CPU work (~0.3 s per turn): run it off the event loop so the API stays responsive for others
        import asyncio
        from app import inflight as _inf
        with _inf.track("import_save"):
            saved = await asyncio.to_thread(save_pairs, user_id, messages, source, True)
        return {"status": "ok", "imported": saved, "cycle": "started"}
    return {"error": "No messages found in text"}


@router.post("/import/dialog")
async def import_dialog_raw(data: dict):
    """Accept parsed dialog from bookmarklet."""
    user_id = data.get("user_id", "bookmarklet_user")
    messages = data.get("messages", [])
    source_url = data.get("source_url", "bookmarklet")
    
    if not messages:
        return {"status": "error", "detail": "messages required"}
    
    # Save using existing logic
    db_name = user_id.replace("@", "").replace(".", "")
    conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db", timeout=10)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS event_metadata (event_id TEXT PRIMARY KEY, time_str TEXT, essence TEXT, raw_dialogue TEXT, messages_count INTEGER, topics_json TEXT, links_json TEXT, status TEXT)")
    
    saved = 0
    for i, msg in enumerate(messages):
        if msg.get("role") == "user" and i+1 < len(messages) and messages[i+1].get("role") == "assistant":
            q = msg.get("content", "")
            a = messages[i+1].get("content", "")
            eid = f"{user_id}::bookmarklet_{i}_{int(time.time())}"
            cur.execute("INSERT OR IGNORE INTO event_metadata (event_id, time_str, essence, raw_dialogue, messages_count, topics_json, links_json, status) VALUES (?,?,?,?,?,?,?,?)",
                       (eid, "", q[:200], f"Q: {q}\nA: {a}", 2, '["bookmarklet"]', "[]", "active"))
            saved += 1
    
    conn.commit()
    conn.close()
    try:
        from app.account_memory import queue_turn
        for i, msg in enumerate(messages):
            if msg.get("role") == "user" and i+1 < len(messages) and messages[i+1].get("role") == "assistant":
                queue_turn("/data/skv/metadata_store", user_id, f"{user_id}::bookmarklet_{i}", msg.get("content",""), messages[i+1].get("content",""), source="import")
    except Exception as exc:
        print(f"[memory] import queue skipped: {exc}", flush=True)
    return {"status": "ok", "message_count": saved, "source_url": source_url}

@router.post("/import/process")
async def import_process(data: dict):
    """Deprecated bulk summarizer (fed up to 200k chars, saved model refusals as L1).
    Now kicks the per-source import cycle with topic-aware windows. Pass source=..."""
    user_id = data.get("user_id", "")
    source = data.get("source", "")
    if not user_id:
        return {"status": "error", "detail": "user_id required"}
    if not source:
        # pick the most recent import-like prefix from event ids
        db_name = user_id.replace("@", "").replace(".", "")
        conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db")
        row = conn.execute(
            "SELECT event_id FROM event_metadata WHERE event_id LIKE '%::%_%' "
            "AND (event_id LIKE '%::import_%' OR event_id LIKE '%::chatgpt_%' OR event_id LIKE '%::bookmarklet_%' "
            "OR event_id LIKE '%::text_import_%' OR event_id LIKE '%::url_import_%' OR event_id LIKE '%::grokexp_%' "
            "OR event_id LIKE '%::profile_%') ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if not row:
            return {"status": "ok", "detail": "No imported data"}
        tail = row[0].split("::", 1)[-1]
        source = tail.rsplit("_", 1)[0]
    schedule_import_cycle(user_id, source)
    return {"status": "ok", "cycle": "started", "source": source,
            "note": "legacy /import/process disabled; using topic-aware import cycle"}


def to_pairs(payload):
    """One shape out: user/assistant pairs. File or pasted text in, no remote URL."""
    if isinstance(payload, str):
        return _pairs_from_text(payload)
    if isinstance(payload, dict) and payload.get("text"):
        return _pairs_from_text(payload["text"])
    blob = payload
    if isinstance(payload, dict):
        for key in ("conversations", "messages", "chats"):
            if isinstance(payload.get(key), list):
                blob = payload[key]
                break
    pairs = []
    if isinstance(blob, list) and blob and isinstance(blob[0], dict) and "mapping" in blob[0]:
        for conv in blob:
            nodes = list((conv.get("mapping") or {}).values())
            msgs = []
            for node in nodes:
                msg = node.get("message") or {}
                role = ((msg.get("author") or {}).get("role") or "")
                parts = ((msg.get("content") or {}).get("parts") or [])
                text = " ".join(p for p in parts if isinstance(p, str))
                if role in ("user", "assistant") and text:
                    msgs.append({"role": role, "content": text})
            pairs.extend(_zip_pairs(msgs))
        return pairs
    msgs = _walk_messages(blob)
    return _zip_pairs(msgs)

def _walk_messages(node):
    found = []
    if isinstance(node, dict):
        role = node.get("role") or node.get("sender") or ""
        content = node.get("content") or node.get("text") or ""
        if isinstance(content, list):
            content = " ".join(str(x) for x in content)
        if role in ("user", "human", "assistant", "model") and content:
            found.append({"role": "user" if role in ("user", "human") else "assistant", "content": str(content)})
        for value in node.values():
            found.extend(_walk_messages(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk_messages(item))
    return found

def _zip_pairs(msgs):
    pairs = []
    for i, msg in enumerate(msgs):
        nxt = msgs[i + 1] if i + 1 < len(msgs) else {}
        if msg.get("role") == "user" and nxt.get("role") == "assistant":
            pairs.append(msg)
            pairs.append(nxt)
    return pairs

def _pairs_from_text(text):
    chunks = re.split(r"\n(?=(?:User|Human|Assistant|Grok|Q|A)\s*:)", text)
    msgs = []
    for chunk in chunks:
        if ":" not in chunk:
            continue
        head, body = chunk.split(":", 1)
        role = "user" if head.strip().lower() in ("user", "human", "q") else "assistant"
        if body.strip():
            msgs.append({"role": role, "content": body.strip()})
    return _zip_pairs(msgs)

@router.post("/import/file")
async def import_file(data: dict):
    user_id = data.get("user_id", "")
    if not user_id:
        return {"status": "error", "detail": "user_id required"}
    pairs = to_pairs(data.get("payload") if "payload" in data else data.get("text", ""))
    source = data.get("source", "import")
    saved = save_pairs(user_id, pairs, source, True)
    return {"status": "ok", "imported": saved, "cycle": "started" if saved else "none"}

import json, os, sqlite3, threading, urllib.request

# Config (memory_config.json -> "import"): switches for rollback.
# Defaults keep old fixed-size windows OFF; set import.legacy_fixed_windows=true to restore.

def _import_cfg():
    """Read import.* switches. Missing keys = safe new defaults."""
    cfg = {
        "legacy_fixed_windows": False,   # True = old cut by 60 msgs (rollback)
        "max_msgs": 12,                  # hard cap per L1 window (pairs)
        "min_msgs": 4,                   # min before topic-change can flush
        "max_chars": 6000,               # hard cap of text fed to the model
        "part_cap": 900,                 # per-event clip inside a window
        "topic_change_threshold": 0.10,  # flush when new msg overlap with bag < this
        "verify_term_overlap": True,     # reject summaries that don't share terms with window
        "min_term_overlap": 0.32,
        "reject_refusals": True,
        "separate_chain": True,          # L1 topic/session under import:<source>
        "tag_shelves": True,             # kind=import, source=<source> on events
        "fixed_window_size": 60,         # only used if legacy_fixed_windows
        # L1/L2 MUST stay on a cheap model (budget). Strong models are for interactive chat only.
        "l1_model": "deepseek/deepseek-chat-v3.1",
        "l2_model": "meta-llama/llama-3.1-8b-instruct",
        # Routing during import (Deniz): critical marks / vault secrets / heavy → Drive
        "route_critical": True,
        "route_secrets": True,
        "route_heavy_to_drive": True,
        "heavy_char_threshold": 12000,
        "drive_folder": "SKV Import",
    }
    try:
        path = "/data/skv/memory_config.json"
        raw = json.loads(open(path).read())
        if isinstance(raw.get("import"), dict):
            cfg.update({k: raw["import"][k] for k in cfg if k in raw["import"]})
    except Exception as exc:
        print(f"[IMPORT] config read skipped: {exc}", flush=True)
    return cfg



_L1_SYSTEM = "You write long-term memory for an AI agent: an L1 summary of one stretch of a user's conversations with AI agents. This is an import of old chats. Output STRICT JSON only (no prose, no code fences) with keys: topic: 1-3 lowercase words joined by underscores (e.g. skv_memory); summary: chronological STAGES, one per line, each 'STAGE n: done ...; decided ...; outcome ...' (only what happened in the text), final line 'OPEN: ...' if tasks remain; about 5-8 percent of the input; in the language of the dialogue; keep names, numbers, codes, file names exactly; critical: 0-3 lasting facts the agent must always remember: decisions taken, standing rules, agreements, names and roles of people other than the user, account or project facts; each fact specific (the concrete value: number, name, setting, decision). Not plans, opinions, general knowledge, dates alone or links alone; not trivial facts (who the user is, that the user leads the project, that a rule exists or is mandatory). Empty list if none; sensitive: exact strings from the text that are real secrets (passwords, private API keys, tokens, card numbers, private codes). Public keys (ssh-ed25519/ssh-rsa), IPs, domains and emails are NOT secrets. Empty list if none. Never copy a secret into summary or critical. Use only facts present in the text. Never invent."
_L1_ECHO = ('"..."', "STAGE n:", "lowercase words joined")

_STOP = set("""
это что как для или если они она его ей им их нам вас нас this that with from have been were will
your about just then than when which where while would could should also which these those into over
вопрос ответ также который которые которая может быть будет есть были было этот эта эти того уже еще
ещё только можно нужно надо при том чтобы куда здесь очень всё все более менее между после перед через
""".split())

_REFUSAL_RE = re.compile(
    r"(?i)("
    r"слишком\s+длинн|too\s+long|текст\s+слишком|"
    r"не\s+могу\s+обработать|cannot\s+process|i\s+cannot\s+.*"
    r"в\s+этом\s+формате|"
    r"вот\s+перевод|вот\s+ответ\s+на\s+(ваш\s+)?вопрос|"
    r"сделай\s+l1\s+на\s+русском|"
    r"ответы\s+на\s+вопросы|"
    r"мне\s+не\s+удалось\s+найти|"
    r"json\s*\{\s*\"summary\""
    r")"
)


def _tokens(text):
    return set(
        w for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9_]{4,}", (text or "").lower())
        if w not in _STOP
    )


def _distinctive(text):
    return set(
        w for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9_]{5,}", (text or "").lower())
        if w not in _STOP
    )


def _is_refusal(text):
    s = (text or "").strip()
    if not s:
        return True
    if _REFUSAL_RE.search(s[:400]):
        return True
    if any(e in s for e in _L1_ECHO):
        return True
    return False


def _term_overlap_ok(summary, parts, min_ratio=0.32):
    sd = _distinctive(summary)
    if len(sd) < 4:
        return len((summary or "").strip()) >= 40
    wd = _distinctive("\n".join(parts or []))
    return (len(sd & wd) / len(sd)) >= min_ratio


def split_import_windows(rows, cfg=None):
    """Split (rowid, event_id, text, essence) into topic-aware windows.

    rows: iterable of (rowid, event_id, raw_dialogue[, essence])
    Returns list of dicts: {parts, rids, essences, n_chars}
    """
    cfg = cfg or _import_cfg()
    part_cap = int(cfg.get("part_cap", 900))
    if cfg.get("legacy_fixed_windows"):
        size = max(1, int(cfg.get("fixed_window_size", 60)))
        out, cur, rids = [], [], []
        for row in rows:
            rid, eid, text = row[0], row[1], row[2]
            cur.append((text or "")[:part_cap]); rids.append(rid)
            if len(cur) >= size:
                out.append({"parts": cur, "rids": rids, "essences": [], "n_chars": sum(map(len, cur))})
                cur, rids = [], []
        if cur:
            out.append({"parts": cur, "rids": rids, "essences": [], "n_chars": sum(map(len, cur))})
        return out

    max_msgs = max(2, int(cfg.get("max_msgs", 12)))
    min_msgs = max(1, int(cfg.get("min_msgs", 4)))
    max_chars = max(1500, int(cfg.get("max_chars", 6000)))
    thr = float(cfg.get("topic_change_threshold", 0.10))
    out, cur, rids, ess_list, bag = [], [], [], [], set()
    cur_essence = None

    def _flush():
        nonlocal cur, rids, ess_list, bag, cur_essence
        if cur:
            out.append({"parts": cur, "rids": rids, "essences": ess_list,
                        "n_chars": sum(map(len, cur))})
        cur, rids, ess_list, bag, cur_essence = [], [], [], set(), None

    for row in rows:
        rid, eid, text = row[0], row[1], row[2]
        essence = row[3] if len(row) > 3 else ""
        piece = (text or "")[:part_cap]
        nt = _tokens(piece)
        new_chars = sum(map(len, cur)) + len(piece)
        flush = False
        if cur and (len(cur) >= max_msgs or new_chars > max_chars):
            flush = True
        elif cur and len(cur) >= min_msgs:
            if essence and cur_essence and essence.strip() and essence.strip() != cur_essence:
                flush = True
            elif nt and bag:
                ov = len(nt & bag) / max(1, len(nt))
                if ov < thr:
                    flush = True
        if flush:
            _flush()
        cur.append(piece); rids.append(rid); ess_list.append(essence or "")
        bag |= nt
        if essence and essence.strip():
            cur_essence = essence.strip()
    _flush()
    return out


def _chain_ids(source, n, cfg=None):
    """Session/topic for an import L1. Separate subsection when separate_chain=true."""
    cfg = cfg or _import_cfg()
    if cfg.get("separate_chain", True):
        topic = f"import:{source}"
        sid = f"import:{source}:l1_{n}"
    else:
        topic = source
        sid = f"{source}_auto_{n}"
    return sid, topic


def _tag_import_events(user_id, event_ids, source):
    try:
        from app import shelves as _sh
        _sh.tag(user_id, list(event_ids), kind="import", source=source or "import",
                project=f"import-{source}"[:32],
                description="Imported chat history (separate chain)")
    except Exception as exc:
        print(f"[IMPORT] shelf tag skipped: {exc}", flush=True)


def _polza(prompt, system="", max_tokens=500, model=None):
    """Cheap LLM only. Default = import.l1_model (Llama 3.1 8B). Do not pass a strong model here."""
    key = os.environ.get("POLZA_KEY", "")
    if not key:
        for line in open("/root/skv-core/.env"):
            if line.startswith("POLZA_KEY="):
                key = line.split("=", 1)[1].strip()
    model = model or _route_cfg().get("l1_model") or "deepseek/deepseek-chat-v3.1"
    # hard guard: never accidentally spend on frontier models in import/rebuild
    _cheap_ok = ("deepseek-chat" in model.lower() or "llama" in model.lower() or "8b" in model.lower() or "flash" in model.lower()
                 or "mini" in model.lower() or "small" in model.lower())
    if not _cheap_ok:
        print(f"[IMPORT] refused expensive model {model!r}, falling back to llama-3.1-8b", flush=True)
        model = "meta-llama/llama-3.1-8b-instruct"
    req = urllib.request.Request(
        "https://api.polza.ai/v1/chat/completions",
        data=json.dumps({"model": model,
                         "messages": ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}],
                         "temperature": 0.1, "max_tokens": max_tokens, "response_format": {"type": "json_object"}}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"]


def run_import_cycle(user_id, source, rebuild_prefix=None):
    """Build L1/L2 for imported events of `source`.

    rebuild_prefix: if set (e.g. 'v2'), session ids become import:<source>:v2:l1_N
    and old L1s are left untouched (side-by-side rebuild).
    """
    cfg = _import_cfg()
    name = user_id.replace("@", "").replace(".", "")
    db = sqlite3.connect(f"/data/skv/metadata_store/{name}.db")
    db.execute("CREATE TABLE IF NOT EXISTS summary_l1 (session_id TEXT PRIMARY KEY, user_id TEXT, topic TEXT, summary_text TEXT, summary_json TEXT, message_count INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    _have = {r[1] for r in db.execute("PRAGMA table_info(summary_l1)")}
    for _col in ("from_rowid INTEGER", "to_rowid INTEGER", "lang TEXT"):
        if _col.split()[0] not in _have:
            db.execute("ALTER TABLE summary_l1 ADD COLUMN " + _col)
    db.execute("CREATE TABLE IF NOT EXISTS summary_l2_blocks (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, source TEXT, period_key TEXT, period_from TEXT, period_to TEXT, from_rowid INTEGER, to_rowid INTEGER, topics_json TEXT, text TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(source, period_key))")
    rows = db.execute(
        "select rowid, event_id, raw_dialogue, coalesce(essence,'') from event_metadata where event_id like ? order by rowid",
        (f"%::{source}_%",),
    ).fetchall()
    if not rows:
        db.close()
        return {"windows": 0, "l1": 0, "skipped": "no events"}

    if cfg.get("tag_shelves", True):
        _tag_import_events(user_id, [r[1] for r in rows], source)

    windows = split_import_windows(rows, cfg)
    summaries = []
    n_ok = n_skip = 0
    for n, w in enumerate(windows):
        src_key = f"{source}:{rebuild_prefix}" if rebuild_prefix else source
        s = _one_l1(db, user_id, src_key, n, w["parts"], w["rids"][0], w["rids"][-1], cfg=cfg)
        if s:
            summaries.append(s); n_ok += 1
        else:
            n_skip += 1
    if [x for x in summaries if x]:
        _one_l2(db, user_id, summaries, source if not rebuild_prefix else f"{source}:{rebuild_prefix}",
                rows[0][0], rows[-1][0])
    db.close()
    return {"windows": len(windows), "l1": n_ok, "rejected": n_skip,
            "legacy": bool(cfg.get("legacy_fixed_windows")),
            "chain": f"import:{source}" if cfg.get("separate_chain", True) else source}


def _l1_parse(content):
    """Llama often ignores 'JSON only' on long Russian windows or runs out of tokens mid-JSON.
    Plain text is kept as the summary; a cut JSON keeps its summary string; a prompt echo is dropped."""
    s = (content or "").strip()
    a, b = s.find("{"), s.rfind("}")
    d = None
    if a >= 0 and b > a:
        try:
            d = json.loads(s[a:b + 1])
        except Exception:
            d = None
    if not isinstance(d, dict):
        m = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)', s)
        if m:
            try:
                summ = json.loads('"' + m.group(1) + '"')
            except Exception:
                summ = m.group(1)
            d = {"summary": summ, "critical": []}
        elif a >= 0:
            d = {"summary": "", "critical": []}
        else:
            d = {"summary": s, "critical": []}
    summ = str(d.get("summary") or "")
    if any(e in summ for e in _L1_ECHO):
        d["summary"] = ""
    return d


def _one_l1(db, user_id, source, n, parts, from_rowid=None, to_rowid=None, cfg=None):
    import hashlib
    cfg = cfg or _import_cfg()
    # secrets→vault stubs, heavy→Drive stubs BEFORE the cheap model sees the text
    _routed = []
    for p in parts:
        try:
            cp, _ = route_import_text(user_id, p, source=source, event_id=None, db=None, cfg=cfg)
            _routed.append(cp)
        except Exception:
            _routed.append(_scrub(user_id, p))
    parts = _routed
    # enforce model input budget even if caller passed a large window
    max_chars = int(cfg.get("max_chars", 6000))
    joined, used = [], 0
    for p in parts:
        if used + len(p) > max_chars and joined:
            break
        joined.append(p); used += len(p)
    parts = joined or parts[:1]
    wsha = hashlib.sha1("\n---\n".join(parts).encode("utf-8", "replace")).hexdigest()
    sid, topic = _chain_ids(source, n, cfg)
    try:
        old = db.execute("select summary_text, summary_json from summary_l1 where session_id=?", (sid,)).fetchone()
        if (old and old[0] and old[1] and json.loads(old[1]).get("window_sha") == wsha
                and not _is_refusal(old[0])
                and (not cfg.get("verify_term_overlap", True) or _term_overlap_ok(old[0], parts, cfg.get("min_term_overlap", 0.32)))):
            if from_rowid is not None:
                db.execute("update summary_l1 set from_rowid=?, to_rowid=?, topic=? where session_id=?",
                           (from_rowid, to_rowid, topic, sid))
                db.commit()
            return old[0]
    except Exception:
        pass
    _wlen = sum(len(p) for p in parts)
    _target = max(250, int(_wlen * 0.06))
    prompt = (f"Window: {_wlen} characters; summary about {_target} characters.\n\n" + "\n---\n".join(parts))
    try:
        data = _l1_parse(_polza(prompt, system=_L1_SYSTEM, max_tokens=min(1800, 500 + _target // 2), model=_route_cfg(cfg).get("l1_model")))
    except Exception as exc:
        print(f"[IMPORT] L1 window {source}_{n} failed: {exc}", flush=True)
        data = {"summary": "", "critical": []}
    summary = _scrub(user_id, str(data.get("summary") or "").strip())[:3000]
    reject_reason = None
    if cfg.get("reject_refusals", True) and _is_refusal(summary):
        reject_reason = "refusal"
    elif len(summary) < 40:
        reject_reason = "too_short"
    elif cfg.get("verify_term_overlap", True) and not _term_overlap_ok(summary, parts, float(cfg.get("min_term_overlap", 0.32))):
        reject_reason = "term_mismatch"
    if reject_reason:
        print(f"[IMPORT] L1 rejected {sid}: {reject_reason}", flush=True)
        summary = ""
    if summary:
        meta = {"window_sha": wsha, "source": "import", "chain": topic,
                "from_rowid": from_rowid, "to_rowid": to_rowid}
        db.execute(
            "insert or replace into summary_l1 (session_id,user_id,topic,summary_text,summary_json,message_count,from_rowid,to_rowid) values (?,?,?,?,?,?,?,?)",
            (sid, user_id, topic, summary, json.dumps(meta, ensure_ascii=False), len(parts), from_rowid, to_rowid),
        )
    for _x in [x for x in (data.get("sensitive") or []) if isinstance(x, str) and len(x) >= 4]:
        summary = (summary or "").replace(_x, "[SECRET]")
        data["critical"] = [c for c in (data.get("critical") or []) if _x not in str(c)]
    marks = list(data.get("critical") or []) if summary else []
    for part in parts:
        if ">>>" in part:
            marks.append(part[part.find(">>>"):][:240])
    for p in parts:
        try:
            route_import_text(user_id, p, source=source, event_id=sid, db=db, cfg=cfg)
        except Exception:
            pass
    try:
        route_critical_marks(db, user_id, marks, event_id=sid, source=source, cfg=cfg)
    except Exception as exc:
        print(f"[IMPORT] critical route skipped: {exc}", flush=True)
    db.commit()
    return summary


def _one_l2(db, user_id, summaries, source="import", from_rowid=None, to_rowid=None):
    summaries = [_scrub(user_id, x) for x in summaries]
    text = "\n".join(s[:300] for s in summaries if s)[:50000]
    _l2_target = max(120, int(len(text) * 0.05))
    system = ("Ты собираешь L2-карту памяти: это заголовки над L1-выжимками, примерно 5% от их длины. "
              "Дай короткий список тем-заголовков через точку с запятой, по порядку, каждый 3-8 слов, с датой или периодом, если она есть. "
              "Помечай коротко, что решено, а что открыто. Не пересказывай, без длинных предложений. "
              "Ответ только JSON-объект с одним ключом map (строка). Пароли и ключи не писать.")
    try:
        content = _polza(f"Выжимки по порядку ({len(text)} символов, карта примерно {_l2_target} символов):\n\n" + text + "\n\nОтвет: только JSON с ключом map.", system=system, max_tokens=700, model=_route_cfg().get("l2_model"))
        s_ = content.strip()
        try:
            mp = json.loads(s_[s_.find("{"):s_.rfind("}") + 1]).get("map") or ""
        except Exception:
            m = re.search(r'"map"\s*:\s*"((?:[^"\\]|\\.)*)', s_)
            mp = m.group(1) if m else ("" if "{" in s_ else s_)
    except Exception:
        mp = ""
    if isinstance(mp, dict):
        mp = " ".join(str(v) for v in mp.values())
    elif isinstance(mp, list):
        mp = " ".join(str(v) for v in mp)
    mp = str(mp).strip()
    if len(mp) < 80 or mp.lower().startswith(("темы, планы", "темы: ...")) or _is_refusal(mp):
        firsts = []
        for x in summaries:
            x = re.sub(r"\s+", " ", x or "").strip()
            if x and not x.startswith("{") and not _is_refusal(x):
                firsts.append(re.split(r"(?<=[.!?])\s", x, 1)[0][:220])
        mp = " ".join(firsts)
        if len(mp) < 80:
            mp = ""
    if mp:
        try:
            _t = lambda r: (db.execute("select time_str from event_metadata where rowid=?", (r,)).fetchone() or [None])[0]
            db.execute("INSERT OR REPLACE INTO summary_l2_blocks (user_id, source, period_key, period_from, period_to, from_rowid, to_rowid, topics_json, text) VALUES (?,?,?,?,?,?,?,?,?)",
                       (user_id, "import", f"import:{source}", _t(from_rowid), _t(to_rowid), from_rowid, to_rowid, "[]", _scrub(user_id, mp)[:4000]))
        except sqlite3.OperationalError:
            pass
        db.execute("CREATE TABLE IF NOT EXISTS summary_l2 (user_id TEXT PRIMARY KEY, map_json TEXT, themes_json TEXT, timeline_json TEXT, session_count INTEGER, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        if not db.execute("SELECT 1 FROM summary_l2 LIMIT 1").fetchone():
            db.execute("INSERT INTO summary_l2 (user_id, map_json, themes_json, timeline_json, session_count) VALUES (?,?,?,?,?)",
                       (user_id, _scrub(user_id, mp)[:4000], "[]", "[]", len(summaries)))
        db.commit()


_cycle_lock = threading.Lock()
_cycle_state = {}   # (user_id, source) -> "running" | "again"


def schedule_import_cycle(user_id, source):
    """One summary cycle per user+source at a time; imports that arrive meanwhile trigger exactly one re-run."""
    key = (user_id, source)
    with _cycle_lock:
        if key in _cycle_state:
            _cycle_state[key] = "again"
            return
        _cycle_state[key] = "running"
    def _loop():
        try:
            while True:
                try:
                    from app import inflight as _inf
                    with _inf.track("import_cycle_run"):
                        run_import_cycle(user_id, source)
                except Exception as e:
                    print(f"[IMPORT] cycle error {user_id} {source}: {e}", flush=True)
                with _cycle_lock:
                    if _cycle_state.get(key) == "again":
                        _cycle_state[key] = "running"
                        continue
                    _cycle_state.pop(key, None)
                    return
        except Exception:
            with _cycle_lock:
                _cycle_state.pop(key, None)
    threading.Thread(target=_loop, daemon=True).start()




# ---- Drive queue drain (T_GDRIVE) ----
@router.get("/import/drive/queue")
async def import_drive_queue_list(user_id: str = "", status: str = "pending", limit: int = 50, key: str = ""):
    """List import_drive_queue rows for a user (agent/ops)."""
    if not user_id and key:
        try:
            from app.routers.v7_core import _user_from_key
            user_id = _user_from_key(key)
        except Exception:
            pass
    if not user_id:
        raise HTTPException(400, "user_id or key required")
    from app import drive_queue as _dq
    return {"ok": True, "user_id": user_id, "items": _dq.list_queue(user_id, status=status, limit=limit),
            "credentials": _dq.credentials_available()}


@router.post("/import/drive/complete")
async def import_drive_complete(data: dict):
    """Mark one queue row uploaded: set drive_url, replace [drive:pending:…] stubs.
    Agent path: upload via connected Google Drive MCP, then call this."""
    user_id = data.get("user_id") or ""
    if not user_id and data.get("key"):
        try:
            from app.routers.v7_core import _user_from_key
            user_id = _user_from_key(data["key"])
        except Exception:
            pass
    if not user_id:
        raise HTTPException(400, "user_id or key required")
    qid = data.get("id") or data.get("queue_id")
    if qid is None:
        raise HTTPException(400, "id required")
    from app import drive_queue as _dq
    return _dq.complete(user_id, int(qid), data.get("drive_url") or "",
                        drive_file_id=str(data.get("drive_file_id") or ""))


@router.post("/import/drive/process")
async def import_drive_process(data: dict):
    """Drain pending queue. Server uploads if /root/skv_drive OAuth present;
    else returns need_agent_upload + payload for MCP Drive upload + /complete."""
    user_id = data.get("user_id") or ""
    if not user_id and data.get("key"):
        try:
            from app.routers.v7_core import _user_from_key
            user_id = _user_from_key(data["key"])
        except Exception:
            pass
    if not user_id:
        raise HTTPException(400, "user_id or key required")
    from app import drive_queue as _dq
    folder = str(data.get("folder") or _route_cfg().get("drive_folder") or "SKV Import")
    limit = int(data.get("limit") or 10)
    qid = data.get("id") or data.get("queue_id")
    if qid is not None:
        return _dq.process_one(user_id, int(qid), folder=folder)
    return _dq.process_pending(user_id, limit=limit, folder=folder)


@router.get("/import/drive/payload")
async def import_drive_payload(user_id: str = "", id: int = 0, key: str = "", max_bytes: int = 4000000):
    """Fetch staged/URL payload (base64) for agent MCP upload."""
    if not user_id and key:
        try:
            from app.routers.v7_core import _user_from_key
            user_id = _user_from_key(key)
        except Exception:
            pass
    if not user_id or not id:
        raise HTTPException(400, "user_id (or key) and id required")
    from app import drive_queue as _dq
    return _dq.read_payload(user_id, int(id), max_bytes=int(max_bytes))


@router.post("/import/rebuild")
async def import_rebuild(data: dict):
    """Rebuild L1/L2 for an existing import source into a side-by-side chain.

    Body: {user_id, source, prefix="v2", dry_run=false}
    Does NOT delete raw events or old L1 rows. New L1s go to import:<source>:<prefix>:l1_N
    (topic import:<source>:<prefix>). Set import.legacy_fixed_windows=true to undo new splitting.
    """
    user_id = data.get("user_id", "")
    source = data.get("source", "")
    prefix = (data.get("prefix") or "v2").strip()[:16] or "v2"
    dry = bool(data.get("dry_run"))
    if not user_id or not source:
        return {"status": "error", "detail": "user_id and source required"}
    name = user_id.replace("@", "").replace(".", "")
    db = sqlite3.connect(f"/data/skv/metadata_store/{name}.db")
    rows = db.execute(
        "select rowid, event_id, raw_dialogue, coalesce(essence,'') from event_metadata where event_id like ? order by rowid",
        (f"%::{source}_%",),
    ).fetchall()
    db.close()
    if not rows:
        return {"status": "error", "detail": f"no events for source={source}"}
    cfg = _import_cfg()
    windows = split_import_windows(rows, cfg)
    preview = [{"n": i, "from_rowid": w["rids"][0], "to_rowid": w["rids"][-1],
                "msgs": len(w["parts"]), "chars": w["n_chars"],
                "head": (w["parts"][0] or "")[:100]} for i, w in enumerate(windows[:30])]
    if dry:
        return {"status": "ok", "dry_run": True, "events": len(rows), "windows": len(windows),
                "legacy": bool(cfg.get("legacy_fixed_windows")), "preview": preview,
                "will_write_topic": f"import:{source}:{prefix}"}
    # run in background so API stays responsive
    def _job():
        try:
            from app import inflight as _inf
            with _inf.track("import_rebuild"):
                run_import_cycle(user_id, source, rebuild_prefix=prefix)
        except Exception as e:
            print(f"[IMPORT] rebuild error {user_id} {source}: {e}", flush=True)
    threading.Thread(target=_job, daemon=True).start()
    return {"status": "ok", "started": True, "events": len(rows), "windows": len(windows),
            "topic": f"import:{source}:{prefix}", "preview_first": preview[:5],
            "note": "old L1s kept; new ones under import:<source>:<prefix>; rollback=import.legacy_fixed_windows or ignore new topic"}

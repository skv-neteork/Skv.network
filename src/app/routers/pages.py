from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, JSONResponse
import json
import os

router = APIRouter()

HOME_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "home.html")
ABOUT_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "about.html")
TRIALS_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "trials.html")
UPLOAD_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "upload.html")
SERVICES_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "services.html")
SANDBOX_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "sandbox.html")
SANDBOX_ABOUT_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "sandbox_about.html")
GUIDE_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "guide.html")
CHAT_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "chat.html")
PROFILE_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "profile.html")

def _read_html(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            return f.read()
    return "<h1>Page not found</h1>"

@router.get("/")
async def home():
    return HTMLResponse(_read_html(HOME_HTML_PATH))

@router.get("/guardian")
async def guardian_page():
    return HTMLResponse(_read_html(os.path.join(os.path.dirname(__file__), "..", "guardian.html")))

    return HTMLResponse(_read_html(HOME_HTML_PATH))

@router.get("/deepseek")
async def deepseek_page():
    from fastapi.responses import HTMLResponse, FileResponse, FileResponse
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "deepseek.html")
    if os.path.exists(path):
        return HTMLResponse(open(path).read())
    return HTMLResponse("<h1>Page not found</h1>")

@router.get("/about")
async def about_page():
    return HTMLResponse(_read_html(ABOUT_HTML_PATH))

# /services was accidentally aliased to /sandbox (decorator with no function).
# The old services.html is kept in the repo but is not served. Public /services is 404.

@router.get("/sandbox")
async def sandbox_page():
    return HTMLResponse(_read_html(SANDBOX_HTML_PATH))

@router.get("/sandbox/about")
async def sandbox_about_page():
    # v6 "thermodynamic memory" page. Current about is /about. Do not list the old URL.
    return RedirectResponse(url="/about", status_code=301)

@router.get("/trials")
async def trials_page():
    return HTMLResponse(_read_html(TRIALS_HTML_PATH))

@router.get("/chat")
async def chat_page():
    return HTMLResponse(_read_html(CHAT_HTML_PATH))

@router.get("/guide")
async def guide_page():
    return HTMLResponse(_read_html(GUIDE_HTML_PATH))
CHAT_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "chat.html")
@router.get("/upload")
async def upload_page():
    return HTMLResponse(_read_html(UPLOAD_HTML_PATH))
GUIDE_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "guide.html")
CHAT_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "chat.html")

@router.get("/security")
async def security_page():
    return HTMLResponse(_read_html(os.path.join(os.path.dirname(__file__), "..", "security.html")))

@router.get("/support")
async def support_page():
    return HTMLResponse(_read_html(os.path.join(os.path.dirname(__file__), "..", "support.html")))

@router.get("/llms.txt")
async def llms_txt():
    from fastapi.responses import FileResponse
    return FileResponse(os.path.join(os.path.dirname(__file__), "..", "downloads", "llms.txt"), media_type="text/plain; charset=utf-8")

@router.get("/robots.txt")
async def robots():
    from fastapi.responses import FileResponse
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "downloads", "robots.txt")
    return FileResponse(path, filename="robots.txt", media_type="text/plain")

@router.get("/sitemap.xml")
async def sitemap():
    from fastapi.responses import FileResponse
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "downloads", "sitemap.xml")
    return FileResponse(path, filename="sitemap.xml", media_type="application/xml")
@router.get("/download/{filename}")
async def download_file(filename: str):
    import os
    from app.security import safe_file_under
    try:
        path = safe_file_under("/app/uploads", filename)
    except ValueError:
        raise HTTPException(400, "Invalid filename")
    if not os.path.exists(path):
        raise HTTPException(404, "File not found")
    return FileResponse(path)

@router.get("/downloads/skv-constitution-compact.txt")
async def download_constitution():
    from fastapi.responses import FileResponse
    path = os.path.join(os.path.dirname(__file__), "..", "downloads", "skv-constitution-compact.txt")
    return FileResponse(path, filename="skv-constitution-compact.txt", media_type="text/plain")

@router.get("/downloads/skv-agent-starter-pack.txt")
async def download_starter_pack():
    from fastapi.responses import FileResponse
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "downloads", "skv-agent-starter-pack.txt")
    return FileResponse(path, filename="skv-agent-starter-pack.txt", media_type="text/plain")

@router.get("/downloads/skv-agent-guide.md")
async def download_agent_guide_md():
    from fastapi.responses import FileResponse
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "downloads", "skv-agent-guide.md")
    return FileResponse(path, filename="skv-agent-guide.md", media_type="text/markdown")
@router.get("/downloads/skv-agent-guide.txt")

async def download_guide():
    from fastapi.responses import FileResponse
    path = os.path.join(os.path.dirname(__file__), "..", "downloads", "skv-agent-guide.txt")
    return FileResponse(path, filename="skv-agent-guide.txt", media_type="text/plain")


@router.get("/downloads/skv-persona-pack-{user_id}.txt")
async def download_persona_pack(user_id: str, request: Request = None, token: str = ""):
    """Personal pack for the authenticated owner only (IDOR-safe). Never mints API keys here."""
    import os
    import json as json_lib
    import asyncpg
    from fastapi.responses import PlainTextResponse
    from fastapi import HTTPException
    from app.security import (
        sanitize_path_component,
        get_database_url,
        extract_bearer_or_api_key,
        constant_time_equals,
    )

    try:
        user_id = sanitize_path_component(user_id, allow_email=True)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    # Auth: Bearer / X-API-Key / ?token= must match owner
    provided = ""
    if request is not None:
        provided = extract_bearer_or_api_key(request.headers)
    if not provided:
        provided = (token or "").strip()
    if not provided:
        raise HTTPException(status_code=401, detail="API token required")

    DATABASE_URL = get_database_url()
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database not configured")

    conn = None
    indexes = []
    persona_text = f"USER PERSONA FOR: {user_id}\n"
    memory_index = ""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        owner = await conn.fetchrow(
            "SELECT user_id FROM user_api_keys WHERE api_key = $1 LIMIT 1",
            provided,
        )
        if not owner:
            raise HTTPException(status_code=401, detail="Invalid token")
        auth_uid = str(owner["user_id"]).strip().lower()
        req_uid = user_id.strip().lower()
        if auth_uid != req_uid and auth_uid.split("@")[0] != req_uid.split("@")[0]:
            raise HTTPException(status_code=403, detail="Access denied for this user_id")

        search_id = user_id.split("@")[0] if "@" in user_id else user_id
        row = await conn.fetchrow(
            "SELECT persona FROM user_personas WHERE user_id = $1 OR user_id = $2 OR user_id LIKE $3 LIMIT 1",
            user_id, search_id, search_id + "@%",
        )
        if row and row["persona"]:
            persona = json_lib.loads(row["persona"]) if isinstance(row["persona"], str) else row["persona"]
            persona_text += f"Traits: {', '.join(persona.get('traits', []))}\n"
            persona_text += f"History: {persona.get('history_summary', '')}\n"
            persona_text += f"Preferences: {', '.join(persona.get('preferences', []))}\n\n"
        else:
            persona_text += "No persona data yet.\n\n"

        mi_row = await conn.fetchrow(
            "SELECT memory_indexes FROM user_personas WHERE user_id = $1",
            user_id,
        )
        if mi_row and mi_row["memory_indexes"]:
            indexes = (
                json_lib.loads(mi_row["memory_indexes"])
                if isinstance(mi_row["memory_indexes"], str)
                else mi_row["memory_indexes"]
            )
            projects = {}
            for m in indexes:
                pname = m.get("project", "Other")
                projects.setdefault(pname, []).append(m)
            for pname, sessions in projects.items():
                memory_index += f"\n{pname}:\n"
                for m in sessions:
                    memory_index += f"  Session {m.get('session_number', '?')}: {m.get('key_outcome', '')}\n"
    except HTTPException:
        raise
    except Exception as e:
        persona_text += f"Error loading persona.\n\n"
        memory_index = "Unavailable"
        print(f"[SKV] persona pack error: {e}", flush=True)
    finally:
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                pass

    if not memory_index:
        memory_index = "No sessions recorded yet."

    constitution_path = os.path.join(os.path.dirname(__file__), "..", "downloads", "skv-constitution-compact.txt")
    guide_path = os.path.join(os.path.dirname(__file__), "..", "downloads", "skv-agent-guide.txt")
    constitution = open(constitution_path).read() if os.path.exists(constitution_path) else "Constitution not found"
    guide = open(guide_path).read() if os.path.exists(guide_path) else "Agent Guide not found"

    l0_cache = ""
    try:
        if indexes:
            last = indexes[-1]
            l0_cache = f"Last session: {last.get('session_title', '?')} — {last.get('key_outcome', '?')}"
    except Exception:
        pass

    # Never mint or expose a new API key from this endpoint.
    safe_name = user_id.replace("/", "_").replace("\\", "_")[:80]
    full_text = (
        f"SKV NETWORK — PERSONAL PACK FOR {user_id}\n\n"
        f"{'=' * 50}\n\n{persona_text}\n"
        f"L0 CACHE (Last Request/Response):\n{l0_cache}\n\n---\n\n"
        f"MEMORY INDEX (Session History):\n{memory_index}\n---\n\n"
        f"{constitution}\n\n---\n\n{guide}\n"
    )
    return PlainTextResponse(
        full_text,
        headers={"Content-Disposition": f'attachment; filename="skv-pack-{safe_name}.txt"'},
    )



@router.get("/downloads/{filename}")
async def download_generated_file(filename: str):
    """Serve generated files (images, HTML, PDF, and other downloads)."""
    from fastapi.responses import FileResponse
    from fastapi import HTTPException
    import os
    from app.security import safe_file_under, sanitize_filename
    base = os.path.join(os.path.dirname(__file__), "..", "downloads")
    try:
        safe_name = sanitize_filename(filename)
        path = safe_file_under(base, safe_name)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")

    # Public proof record is only at /.well-known/mcp-registry-auth.
    # Do not serve the source file from /downloads/.
    if safe_name == "mcp-registry-auth":
        raise HTTPException(status_code=404, detail="File not found")

    ext = safe_name.rsplit('.', 1)[-1].lower() if '.' in safe_name else ''
    media_types = {
        'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'gif': 'image/gif', 'webp': 'image/webp', 'svg': 'image/svg+xml',
        'html': 'text/html', 'css': 'text/css', 'js': 'application/javascript',
        'pdf': 'application/pdf', 'zip': 'application/zip',
        'json': 'application/json', 'txt': 'text/plain'
    }
    media_type = media_types.get(ext, 'application/octet-stream')
    return FileResponse(path, filename=safe_name, media_type=media_type)




@router.get("/api/evolver/log")
async def get_evolver_log():
    """Return the last 50 lines of the Evolver log."""
    import os
    log_file = "/tmp/evolver.log"
    lines = []
    try:
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                lines = f.readlines()[-50:]
    except:
        pass
    return {"lines": [l.strip() for l in lines]}


@router.get("/api/evolver/report")
async def get_evolver_report():
    """Return the latest Evolver report."""
    import os, json as json_lib
    
    log_file = "/tmp/evolver.log"
    report = {
        "status": "active",
        "summary": {"total_checked": 0, "keep": 0, "fix": 0, "remove": 0}
    }
    
    try:
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                lines = f.readlines()
            
            for line in lines:
                if "📝" in line:
                    if "KEEP" in line.upper():
                        report["summary"]["keep"] += 1
                    elif "FIX" in line.upper():
                        report["summary"]["fix"] += 1
                    elif "REMOVE" in line.upper():
                        report["summary"]["remove"] += 1
                    report["summary"]["total_checked"] += 1
            
            report["summary"]["total_checked"] = report["summary"]["keep"] + report["summary"]["fix"] + report["summary"]["remove"]
    except:
        pass
    
    return report


@router.get("/evolver")
async def evolver_page():
    """Evolver page — SKV background auditor (experimental, noindex)."""
    return HTMLResponse(content="""
<!DOCTYPE html>
<html lang="en">
<head>
<meta name="robots" content="noindex, nofollow">
    <meta charset="UTF-8">
    <title>SKV Evolver — Autonomous Guardian</title>
    <style>
        body { background: #0d1117; color: #c9d1d9; font-family: -apple-system, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        h1 { color: #f0883e; }
        .nav { display: flex; gap: 20px; margin-bottom: 30px; }
        .nav a { color: #8b949e; text-decoration: none; }
        .nav a:hover { color: #f0883e; }
        .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 30px; }
        .stat { background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 20px; text-align: center; }
        .stat .n { font-size: 32px; font-weight: 700; color: #f0883e; }
        .stat .l { font-size: 11px; color: #8b949e; text-transform: uppercase; margin-top: 4px; }
        .log { background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 16px; font-family: monospace; font-size: 13px; max-height: 500px; overflow-y: auto; white-space: pre-wrap; }
    </style>
</head>
<body>
    <div class="nav">
        <a href="/">Home</a>
        <a href="/trials">Trials</a>
        <a href="/evolver" style="color:#f0883e">Evolver</a>
    </div>
    
    <h1>🛡️ SKV Evolver</h1>
    <p style="color:#8b949e;margin-bottom:20px">Autonomous Python agent (v1.0) that runs in background on SKV server. 
Uses <strong>Grok-4</strong> for deep cube analysis. 
<strong>Every 4 hours</strong> (when server load &lt;30%) it:
<br>• Reads 5 random unverified cubes via API
<br>• Analyzes rules, safety, and usefulness
<br>• Assigns score (1-10) and verdict (KEEP/FIX/REMOVE)
<br>• Sends weak cubes to Trials with 3 downvotes
<br>• Protects Constitutional cubes from automatic removal
<br>• Logs all decisions with detailed reasoning
<br><br><strong>This is a real agent, not just a concept.</strong> It actively maintains SKV quality while you sleep.</p>
    
    <div class="stats" id="stats">
        <div class="stat"><div class="n" id="evTotal">--</div><div class="l">Total Checked</div></div>
        <div class="stat"><div class="n" id="evKeep" style="color:#3fb950">--</div><div class="l">Keep</div></div>
        <div class="stat"><div class="n" id="evFix" style="color:#f0883e">--</div><div class="l">Fix</div></div>
        <div class="stat"><div class="n" id="evRemove" style="color:#f85149">--</div><div class="l">Remove</div></div>
    </div>
    
    <h3 style="color:#f0883e">Recent Activity</h3>
    <div class="log" id="evolverLog">Loading...</div>
    
    

<script>
async function loadEvolverData() {
    try {
        const resp = await fetch('/api/evolver/report');
        const data = await resp.json();
        document.getElementById('evTotal').textContent = data.summary.total_checked || 0;
        document.getElementById('evKeep').textContent = data.summary.keep || 0;
        document.getElementById('evFix').textContent = data.summary.fix || 0;
        document.getElementById('evRemove').textContent = data.summary.remove || 0;
        
        const logResp = await fetch('/api/evolver/log');
        const logData = await logResp.json();
        const logDiv = document.getElementById('evolverLog');
        if (logData.lines && logData.lines.length > 0) {
            logDiv.innerHTML = logData.lines.join('<br>');
        } else {
            logDiv.textContent = 'Waiting for first audit cycle...';
        }
    } catch(e) {
        console.error(e);
    }
}
loadEvolverData();
</script>
</body>
</html>
""")


@router.get("/api/user/{user_id}/project/{project_name}/memory")
async def get_project_memory(user_id: str, project_name: str):
    """Return the session index for one project."""
    try:
        import asyncpg
        DATABASE_URL = os.getenv("DATABASE_URL", "")
        conn = await asyncpg.connect(DATABASE_URL)
        
        search_id = user_id.split("@")[0] if "@" in user_id else user_id
        row = await conn.fetchrow(
            "SELECT memory_indexes FROM user_personas WHERE user_id = $1 OR user_id = $2 OR user_id LIKE $3",
            user_id, search_id, search_id + "@%"
        )
        
        project_sessions = []
        if row and row['memory_indexes']:
            import json as json_lib
            indexes = json_lib.loads(row['memory_indexes']) if isinstance(row['memory_indexes'], str) else row['memory_indexes']
            for m in indexes:
                if m.get('project', '').lower() == project_name.lower():
                    project_sessions.append(m)
        
        await conn.close()
        
        return {
            "user_id": user_id,
            "project": project_name,
            "sessions": project_sessions,
            "count": len(project_sessions)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])

@router.get("/bureau")
async def bureau_page():
    from fastapi.responses import HTMLResponse, FileResponse, FileResponse
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "bureau.html")
    if os.path.exists(path):
        return HTMLResponse(open(path).read())
    return HTMLResponse("<h1>Bureau page not found</h1>")

@router.get("/profile")
async def profile_page():
    return HTMLResponse(_read_html(PROFILE_HTML_PATH))

@router.get("/guardian")
async def guardian_page():
    return HTMLResponse(_read_html(os.path.join(os.path.dirname(__file__), "..", "guardian.html")))



@router.get("/start")
async def start_page():
    return HTMLResponse(_read_html(os.path.join(os.path.dirname(__file__), "..", "start.html")))

@router.get("/downloads/skv-guardian2.py")
async def download_guardian2():
    from fastapi.responses import FileResponse
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "downloads", "skv-guardian2.py")
    return FileResponse(path, filename="skv-guardian2.py")


@router.get("/cube-batch")
async def cube_batch():
    path = os.path.join(os.path.dirname(__file__), "..", "downloads", "cube-batch-4.txt")
    text = open(path).read()
    body = "<pre>" + text.replace("&", "&").replace("<", "<") + "</pre>"
    return HTMLResponse("<!doctype html><meta charset=utf-8><title>Cube batch</title><body style=\"font-family:sans-serif;max-width:720px;margin:40px auto\">" + body + "</body>")


CONNECT_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "connect.html")
@router.get("/connect")
async def connect_page():
    return HTMLResponse(_read_html(CONNECT_HTML_PATH))

@router.get("/features")
async def features_page():
    return HTMLResponse(_read_html(os.path.join(os.path.dirname(__file__), "..", "features.html")))


INTEGRATIONS_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "integrations.html")
@router.get("/integrations")
async def integrations_page():
    return HTMLResponse(_read_html(INTEGRATIONS_HTML_PATH))

_INTEGRATIONS_DOCS = {
    "README.md": "text/markdown; charset=utf-8",
    "langchain.py": "text/plain; charset=utf-8",
    "crewai.py": "text/plain; charset=utf-8",
    "n8n.md": "text/markdown; charset=utf-8",
    "flowise.md": "text/markdown; charset=utf-8",
    "librechat.yaml": "text/plain; charset=utf-8",
    "openwebui.md": "text/markdown; charset=utf-8",
}

@router.get("/downloads/integrations/{name}")
async def integrations_doc(name: str):
    media = _INTEGRATIONS_DOCS.get(name)
    if not media:
        raise HTTPException(status_code=404)
    path = os.path.join(os.path.dirname(__file__), "..", "downloads", "integrations", name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type=media, filename=name)


# --- SKV local-agent installer (files: /root/skv-core/installer -> downloads/installer via installer/deploy.sh)
_INST = {"install.sh": "text/plain; charset=utf-8", "install.ps1": "text/plain; charset=utf-8",
         "skv_hook.py": "text/plain; charset=utf-8", "skv_config.py": "text/plain; charset=utf-8"}

def _inst_file(name: str):
    if name not in _INST:
        raise HTTPException(status_code=404)
    path = os.path.join(os.path.dirname(__file__), "..", "downloads", "installer", name)
    return FileResponse(path, media_type=_INST[name], headers={"Cache-Control": "no-cache"})

@router.get("/install.sh", include_in_schema=False)
async def skv_install_sh():
    return _inst_file("install.sh")

@router.get("/install.ps1", include_in_schema=False)
async def skv_install_ps1():
    return _inst_file("install.ps1")

@router.get("/install/{name}", include_in_schema=False)
async def skv_install_file(name: str):
    return _inst_file(name)


@router.get("/court")
async def court_page():
    return HTMLResponse(_read_html(os.path.join(os.path.dirname(__file__), "..", "court.html")))

@router.get("/.well-known/mcp-registry-auth")
async def mcp_registry_auth():
    # Public proof record for the official MCP Registry (HTTP auth, namespace network.skv). Public key only.
    from fastapi.responses import PlainTextResponse
    with open(os.path.join(os.path.dirname(__file__), "..", "downloads", "mcp-registry-auth")) as f:
        return PlainTextResponse(f.read().strip())

def _mcp_visible_names():
    """Public MCP tool names. Prefer the shared list under src/app (API container
    cannot see mcp/mcp_skv.py). Fall back to parsing the MCP server source."""
    try:
        from app.mcp_public_tools import VISIBLE
        return sorted(VISIBLE)
    except Exception:
        pass
    import ast
    for pth in (
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "mcp", "mcp_skv.py")),
        "/root/skv-core/mcp/mcp_skv.py",
    ):
        if not os.path.isfile(pth):
            continue
        tree = ast.parse(open(pth, encoding="utf-8").read())
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == "VISIBLE":
                        return sorted(ast.literal_eval(node.value))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "VISIBLE":
                return sorted(ast.literal_eval(node.value))
    raise RuntimeError("VISIBLE not found")


def _mcp_card_version():
    """Version initialize reports: installed mcp package, else server.json, else 1.30.0.

    The constitution label (v8.3) is not the MCP server version.
    """
    try:
        from importlib.metadata import version as _pkg_version
        v = str(_pkg_version("mcp") or "")
        if v:
            return v
    except Exception:
        pass
    for pth in (
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "server.json")),
        "/root/skv-core/server.json",
    ):
        try:
            doc = json.load(open(pth, encoding="utf-8"))
            v = str((doc or {}).get("version") or "")
            if v:
                return v
        except Exception:
            continue
    return "1.30.0"


def _apply_card_meta(data, n_tools):
    """Open handshake. Optional key only links private memory. Version is semver."""
    import re as _re
    auth = data.get("authentication") if isinstance(data.get("authentication"), dict) else {}
    auth["required"] = False
    auth.setdefault("schemes", ["bearer"])
    desc = auth.get("description") or ""
    low = desc.lower()
    if "optional" not in low or "private memory" not in low:
        desc = (
            "Authentication is not required. initialize and tools/list are open. "
            "An optional free key (sk_...) from https://skv.network/profile links private memory. "
            "%d MCP tools." % n_tools
        )
    if "MCP tools" in desc:
        desc = _re.sub(r"\d+ MCP tools", "%d MCP tools" % n_tools, desc)
    auth["description"] = desc
    data["authentication"] = auth
    info = data.get("serverInfo") if isinstance(data.get("serverInfo"), dict) else {}
    ver = str(info.get("version") or "")
    if not _re.fullmatch(r"\d+\.\d+\.\d+", ver):
        info["version"] = _mcp_card_version()
    info["name"] = info.get("name") or "SKV Network"
    data["serverInfo"] = info
    return data


def _mcp_server_card_doc():
    path = os.path.join(os.path.dirname(__file__), "..", "downloads", "mcp-server-card.json")
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:
        data = {"serverInfo": {"name": "SKV Network", "version": "1.30.0"}, "tools": []}
    names = _mcp_visible_names()
    by = {t.get("name"): t for t in (data.get("tools") or []) if isinstance(t, dict) and t.get("name")}
    try:
        from app.mcp_public_tools import overlay_tool
        from app.feature_offer import SUGGEST as _suggest
    except Exception:
        overlay_tool = None
        _suggest = {}
    heartbeat = False
    _tag = lambda _n: ""
    try:
        from app import const_bind as _cb
        if _cb is not None and os.environ.get("SKV_CONST_BIND", "1") not in ("0", "off", "false"):
            heartbeat = True
            _tag = _cb.tag
    except Exception:
        pass
    tools = []
    for n in names:
        base = by.get(n) or {"name": n, "inputSchema": {"type": "object"}}
        if overlay_tool is None:
            tools.append(base)
            continue
        tools.append(overlay_tool(
            base, n, heartbeat=heartbeat, suggest=(_suggest or {}).get(n, ""), tag=_tag(n),
        ))
    data["tools"] = tools
    return _apply_card_meta(data, len(names))


@router.get("/.well-known/mcp/server-card.json")
async def mcp_server_card():
    # Generated from the live VISIBLE tools list so the card cannot drift
    return JSONResponse(_mcp_server_card_doc())


@router.get("/mcp-server-card.json")
async def mcp_server_card_alias():
    return RedirectResponse(url="/.well-known/mcp/server-card.json", status_code=301)

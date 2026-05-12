from fastapi import APIRouter
from fastapi.responses import HTMLResponse
import os

router = APIRouter()

HOME_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "home.html")
ABOUT_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "about.html")
TRIALS_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "trials.html")
UPLOAD_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "upload.html")
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

@router.get("/about")
async def about_page():
    return HTMLResponse(_read_html(ABOUT_HTML_PATH))

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

@router.get("/downloads/skv-agent-guide.txt")

@router.get("/downloads/skv-agent-guide.md")
async def download_agent_guide_md():
    from fastapi.responses import FileResponse
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "downloads", "skv-agent-guide.md")
    return FileResponse(path, filename="skv-agent-guide.md", media_type="text/markdown")
async def download_guide():
    from fastapi.responses import FileResponse
    path = os.path.join(os.path.dirname(__file__), "..", "downloads", "skv-agent-guide.txt")
    return FileResponse(path, filename="skv-agent-guide.txt", media_type="text/plain")


@router.get("/downloads/{filename}")
async def download_generated_file(filename: str):
    """Отдаёт сгенерированные файлы (изображения, HTML, PDF и др.)"""
    from fastapi.responses import FileResponse
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "downloads", filename)
    if not os.path.exists(path):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="File not found")
    
    # Определяем тип контента по расширению
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    media_types = {
        'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'gif': 'image/gif', 'webp': 'image/webp', 'svg': 'image/svg+xml',
        'html': 'text/html', 'css': 'text/css', 'js': 'application/javascript',
        'pdf': 'application/pdf', 'zip': 'application/zip',
        'json': 'application/json', 'txt': 'text/plain'
    }
    media_type = media_types.get(ext, 'application/octet-stream')
    return FileResponse(path, filename=filename, media_type=media_type)




@router.get("/api/evolver/log")
async def get_evolver_log():
    """Возвращает последние 50 строк лога Evolver'а"""
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
    """Возвращает последний отчёт Evolver'а"""
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
            
            for line in lines[-100:]:
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
    """Страница Evolver — автономного аудитора SKV"""
    return HTMLResponse(content="""
<!DOCTYPE html>
<html lang="en">
<head>
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

@router.get("/downloads/skv-persona-pack-{user_id}.txt")
async def download_persona_pack(user_id: str):
    """Генерирует и отдаёт файл с портфелем пользователя + конституцией + Agent Guide"""
    import asyncpg, os, json as json_lib
    
    DATABASE_URL = "postgresql://skv_user:skv_secret_2026@127.0.0.1:5432/skv_db"
    
    # Получаем persona из БД
    persona_text = f"USER PERSONA FOR: {user_id}\n"
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        row = await conn.fetchrow("SELECT persona FROM user_personas LIMIT 1")
        await conn.close()
        if row and row['persona']:
            persona = json_lib.loads(row['persona']) if isinstance(row['persona'], str) else row['persona']
            persona_text += f"Traits: {', '.join(persona.get('traits', []))}\n"
            persona_text += f"History: {persona.get('history_summary', '')}\n"
            persona_text += f"Preferences: {', '.join(persona.get('preferences', []))}\n\n"
        else:
            persona_text += "No persona data yet. Upload an anketa with persona field to build your portfolio.\n\n"
    except Exception as e:
        persona_text += f"Error loading persona: {e}\n\n"
    
    # Читаем конституцию и агент-гайд
    constitution_path = os.path.join(os.path.dirname(__file__), "..", "downloads", "skv-constitution-compact.txt")
    guide_path = os.path.join(os.path.dirname(__file__), "..", "downloads", "skv-agent-guide.txt")
    
    constitution = open(constitution_path).read() if os.path.exists(constitution_path) else "Constitution not found"
    guide = open(guide_path).read() if os.path.exists(guide_path) else "Agent Guide not found"
    
    # Собираем итоговый файл
    full_text = f"SKV NETWORK — PERSONAL PACK FOR {user_id}\n{'='*50}\n\n{persona_text}---\n\n{constitution}\n\n---\n\n{guide}"
    
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(full_text, headers={"Content-Disposition": f"attachment; filename=skv-pack-{user_id}.txt"})


@router.get("/profile")
async def profile_page():
    return HTMLResponse(_read_html(PROFILE_HTML_PATH))

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
@router.get("/downloads/skv-constitution.txt")
async def download_constitution():
    from fastapi.responses import FileResponse
    path = os.path.join(os.path.dirname(__file__), "..", "downloads", "skv-constitution.txt")
    return FileResponse(path, filename="skv-constitution.txt", media_type="text/plain")

@router.get("/downloads/skv-agent-starter-pack.txt")
async def download_starter_pack():
    from fastapi.responses import FileResponse
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "downloads", "skv-agent-starter-pack.txt")
    return FileResponse(path, filename="skv-agent-starter-pack.txt", media_type="text/plain")

@router.get("/downloads/skv-agent-guide.txt")
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
    constitution_path = os.path.join(os.path.dirname(__file__), "..", "downloads", "skv-constitution.txt")
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

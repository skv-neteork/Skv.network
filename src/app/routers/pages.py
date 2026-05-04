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

@router.get("/downloads/skv-agent-guide.txt")
async def download_guide():
    from fastapi.responses import FileResponse
    path = os.path.join(os.path.dirname(__file__), "..", "downloads", "skv-agent-guide.txt")
    return FileResponse(path, filename="skv-agent-guide.txt", media_type="text/plain")
@router.get("/profile")
async def profile_page():
    return HTMLResponse(_read_html(PROFILE_HTML_PATH))

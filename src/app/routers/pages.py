from fastapi import APIRouter
from fastapi.responses import HTMLResponse
import os

router = APIRouter()

HOME_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "home.html")
ABOUT_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "about.html")
TRIALS_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "trials.html")
UPLOAD_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "upload.html")
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

@router.get("/upload")
async def upload_page():
    return HTMLResponse(_read_html(UPLOAD_HTML_PATH))

@router.get("/profile")
async def profile_page():
    return HTMLResponse(_read_html(PROFILE_HTML_PATH))

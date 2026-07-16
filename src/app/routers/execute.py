"""SKV Executor — generate artifacts (image/html/pdf). No in-process code execution."""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse
import requests
import json
import time
import os
import re

from app.security import safe_file_under, sanitize_filename

router = APIRouter()

DOWNLOADS_DIR = os.environ.get("SKV_DOWNLOADS_DIR", "/app/downloads")
_SAFE_ACTION = re.compile(r"^[a-z_]+$")


def _ensure_downloads_dir():
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)


@router.post("/api/execute")
async def execute_action(request: Request):
    data = await request.json()
    action = data.get("action", data.get("instructions", {}).get("action", ""))
    prompt = data.get("instructions", {}).get("prompt", data.get("prompt", ""))

    if not action:
        raise HTTPException(status_code=400, detail="Missing 'action' field")
    if not _SAFE_ACTION.fullmatch(str(action)):
        raise HTTPException(status_code=400, detail="Invalid action")

    # RCE removed: in-process exec() is not allowed. Use sandboxed /api/execute/code.
    if action == "execute_code":
        raise HTTPException(
            status_code=403,
            detail="In-process code execution is disabled. Use POST /api/execute/code (sandboxed) with a valid API key.",
        )

    instructions = data.get("instructions") or {}
    _ensure_downloads_dir()

    if action == "generate_image":
        width = int(data.get("parameters", {}).get("width", 1024))
        height = int(data.get("parameters", {}).get("height", 1024))
        width = max(64, min(width, 2048))
        height = max(64, min(height, 2048))
        encoded = str(prompt).replace(" ", "_")[:200]
        url = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&nologo=true"
        resp = requests.get(url, timeout=60)
        if resp.status_code == 200:
            fname = f"image_{int(time.time())}.png"
            path = safe_file_under(DOWNLOADS_DIR, fname)
            with open(path, "wb") as f:
                f.write(resp.content)
            return {
                "status": "success",
                "action": action,
                "file_url": f"/api/execute/file/{fname}",
                "file_size": len(resp.content),
            }
        return {"status": "error", "message": f"API error {resp.status_code}"}

    if action == "generate_html":
        html = instructions.get("html", "") or data.get("html", "")
        css = instructions.get("css", "") or data.get("css", "")
        if not html:
            raise HTTPException(400, "Missing HTML")
        # Basic XSS hardening for stored HTML
        if re.search(r"(?i)<script|javascript:|on\w+\s*=", html + css):
            raise HTTPException(400, "Script content is not allowed in generate_html")
        fname = f"page_{int(time.time())}.html"
        path = safe_file_under(DOWNLOADS_DIR, fname)
        full = (
            "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
            f"<style>{css}</style>\n</head>\n<body>\n{html}\n</body>\n</html>"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(full)
        return {
            "status": "success",
            "action": action,
            "file_url": f"/api/execute/file/{fname}",
            "file_size": len(full),
        }

    if action == "generate_pdf":
        text = instructions.get("text", "") or prompt
        title = data.get("title", "SKV Document")
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas

            fname = f"doc_{int(time.time())}.pdf"
            path = safe_file_under(DOWNLOADS_DIR, fname)
            c = canvas.Canvas(path, pagesize=A4)
            c.setFont("Helvetica", 16)
            c.drawString(50, 800, str(title)[:80])
            c.setFont("Helvetica", 12)
            y = 770
            for line in str(text).split("\n")[:50]:
                if y < 50:
                    c.showPage()
                    y = 800
                c.drawString(50, y, line[:100])
                y -= 20
            c.save()
            return {
                "status": "success",
                "action": action,
                "file_url": f"/api/execute/file/{fname}",
                "file_size": os.path.getsize(path),
            }
        except ImportError:
            return {"status": "error", "message": "ReportLab not installed"}

    if action == "generate_all":
        prompt = instructions.get("prompt", "")
        html = instructions.get("html", "")
        css = instructions.get("css", "")
        text = instructions.get("text", "")
        results = []

        if prompt:
            encoded = str(prompt).replace(" ", "_")[:200]
            url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=768&nologo=true"
            resp = requests.get(url, timeout=60)
            if resp.status_code == 200:
                fname = f"all_image_{int(time.time())}.png"
                path = safe_file_under(DOWNLOADS_DIR, fname)
                with open(path, "wb") as f:
                    f.write(resp.content)
                results.append({"type": "image", "file_url": f"/api/execute/file/{fname}"})

        if html:
            if re.search(r"(?i)<script|javascript:|on\w+\s*=", html + css):
                raise HTTPException(400, "Script content is not allowed in generate_html")
            fname = f"all_page_{int(time.time())}.html"
            path = safe_file_under(DOWNLOADS_DIR, fname)
            full = (
                "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"UTF-8\">\n"
                f"<style>{css}</style>\n</head>\n<body>\n{html}\n</body>\n</html>"
            )
            with open(path, "w", encoding="utf-8") as f:
                f.write(full)
            results.append({"type": "html", "file_url": f"/api/execute/file/{fname}"})

        if text:
            try:
                from reportlab.lib.pagesizes import A4
                from reportlab.pdfgen import canvas

                fname = f"all_doc_{int(time.time())}.pdf"
                path = safe_file_under(DOWNLOADS_DIR, fname)
                c = canvas.Canvas(path, pagesize=A4)
                c.setFont("Helvetica", 16)
                c.drawString(50, 800, "SKV Generated Document")
                c.setFont("Helvetica", 12)
                y = 770
                for line in str(text).split("\n")[:50]:
                    if y < 50:
                        c.showPage()
                        y = 800
                    c.drawString(50, y, line[:100])
                    y -= 20
                c.save()
                results.append({"type": "pdf", "file_url": f"/api/execute/file/{fname}"})
            except Exception:
                pass

        return {"status": "success", "action": "generate_all", "files": results}

    return {
        "status": "error",
        "message": f"Unknown action: '{action}'. Supported: generate_image, generate_html, generate_pdf, generate_all.",
        "help": "Send POST to /api/execute with JSON body: {'action': 'generate_image', 'instructions': {'prompt': 'your description'}, 'parameters': {'width': 1024, 'height': 768}}",
    }


@router.get("/api/execute/file/{filename}")
async def get_executed_file(filename: str):
    try:
        safe_name = sanitize_filename(filename)
        path = safe_file_under(DOWNLOADS_DIR, safe_name)
    except ValueError:
        raise HTTPException(400, "Invalid filename")
    if not os.path.exists(path):
        raise HTTPException(404, "File not found")
    ext = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    mt = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "html": "text/html",
        "pdf": "application/pdf",
    }
    import urllib.parse

    safe_disp = urllib.parse.quote(safe_name)
    return FileResponse(
        path,
        media_type=mt.get(ext, "application/octet-stream"),
        headers={"Content-Disposition": f"attachment; filename={safe_disp}"},
    )

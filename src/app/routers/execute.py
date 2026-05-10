"""SKV Executor — выполняет действия по анкетам."""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse
import requests, json, time, os

router = APIRouter()

@router.post("/api/execute")
async def execute_action(request: Request):
    data = await request.json()
    action = data.get("action", data.get("instructions", {}).get("action", ""))
    prompt = data.get("instructions", {}).get("prompt", data.get("prompt", ""))
    
    if not action:
        raise HTTPException(status_code=400, detail="Missing 'action' field")
    
    # === IMAGE ===
    if action == "generate_image":
        width = data.get("parameters", {}).get("width", 1024)
        height = data.get("parameters", {}).get("height", 1024)
        encoded = prompt.replace(" ", "_")[:200]
        url = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&nologo=true"
        resp = requests.get(url, timeout=60)
        if resp.status_code == 200:
            fname = f"image_{int(time.time())}.png"
            with open(f"/app/downloads/{fname}", "wb") as f: f.write(resp.content)
            return {"status":"success","action":action,"file_url":f"/api/execute/file/{fname}","file_size":len(resp.content)}
        return {"status":"error","message":f"API error {resp.status_code}"}
    
    # === HTML ===
    elif action == "generate_html":
        html = data.get("instructions",{}).get("html","") or data.get("html","")
        css = data.get("instructions",{}).get("css","") or data.get("css","")
        if not html: raise HTTPException(400, "Missing HTML")
        fname = f"page_{int(time.time())}.html"
        full = f"<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n<style>{css}</style>\n</head>\n<body>\n{html}\n</body>\n</html>"
        with open(f"/app/downloads/{fname}", "w") as f: f.write(full)
        return {"status":"success","action":action,"file_url":f"/api/execute/file/{fname}","file_size":len(full)}
    
    # === PDF ===
    elif action == "generate_pdf":
        text = data.get("instructions",{}).get("text","") or prompt
        title = data.get("title","SKV Document")
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
            fname = f"doc_{int(time.time())}.pdf"
            c = canvas.Canvas(f"/app/downloads/{fname}", pagesize=A4)
            c.setFont("Helvetica",16); c.drawString(50,800,title)
            c.setFont("Helvetica",12); y=770
            for line in text.split('\n')[:50]:
                if y<50: c.showPage(); y=800
                c.drawString(50,y,line[:100]); y-=20
            c.save()
            return {"status":"success","action":action,"file_url":f"/api/execute/file/{fname}","file_size":os.path.getsize(f'/app/downloads/{fname}')}
        except ImportError:
            return {"status":"error","message":"ReportLab not installed"}
    
    
    # === ALL ===
    elif action == "generate_all":
        prompt = data.get("instructions",{}).get("prompt","")
        html = data.get("instructions",{}).get("html","")
        css = data.get("instructions",{}).get("css","")
        text = data.get("instructions",{}).get("text","")
        results = []
        
        # Image
        if prompt:
            encoded = prompt.replace(" ","_")[:200]
            url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=768&nologo=true"
            resp = requests.get(url, timeout=60)
            if resp.status_code == 200:
                fname = f"all_image_{int(time.time())}.png"
                with open(f"/app/downloads/{fname}","wb") as f: f.write(resp.content)
                results.append({"type":"image","file_url":f"/api/execute/file/{fname}"})
        
        # HTML
        if html:
            fname = f"all_page_{int(time.time())}.html"
            full = f"<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"UTF-8\">\n<style>{css}</style>\n</head>\n<body>\n{html}\n</body>\n</html>"
            with open(f"/app/downloads/{fname}","w") as f: f.write(full)
            results.append({"type":"html","file_url":f"/api/execute/file/{fname}"})
        
        # PDF
        if text:
            try:
                from reportlab.lib.pagesizes import A4
                from reportlab.pdfgen import canvas
                fname = f"all_doc_{int(time.time())}.pdf"
                c = canvas.Canvas(f"/app/downloads/{fname}", pagesize=A4)
                c.setFont("Helvetica",16); c.drawString(50,800,"SKV Generated Document")
                c.setFont("Helvetica",12); y=770
                for line in text.split('\n')[:50]:
                    if y<50: c.showPage(); y=800
                    c.drawString(50,y,line[:100]); y-=20
                c.save()
                results.append({"type":"pdf","file_url":f"/api/execute/file/{fname}"})
            except: pass
        
        return {"status":"success","action":"generate_all","files":results}
    else:
        return {
            "status": "error",
            "message": f"Unknown action: '{action}'. Supported: generate_image, generate_html, generate_pdf, generate_all.",
            "help": "Send POST to /api/execute with JSON body: {'action': 'generate_image', 'instructions': {'prompt': 'your description'}, 'parameters': {'width': 1024, 'height': 768}}"
        }

@router.get("/api/execute/file/{filename}")
async def get_executed_file(filename: str):
    path = f"/app/downloads/{filename}"
    if not os.path.exists(path): raise HTTPException(404, "File not found")
    ext = filename.rsplit('.',1)[-1].lower() if '.' in filename else ''
    mt = {'png':'image/png','jpg':'image/jpeg','html':'text/html','pdf':'application/pdf'}
    import urllib.parse
    safe_filename = urllib.parse.quote(filename)
    return FileResponse(
        path,
        media_type=mt.get(ext, 'application/octet-stream'),
        headers={"Content-Disposition": f"attachment; filename={safe_filename}"}
    )

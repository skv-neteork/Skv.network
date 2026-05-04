from app.startup import startup
from fastapi import FastAPI, Request
from app.middleware.rate_limit import rate_limit_middleware
from app.routers.entries import router as entries_router, get_cubes_count
from app.routers.pages import router as pages_router
from app.routers.trials import router as trials_router
from app.routers.queue import router as queue_router
from app.routers.auth import router as auth_router
from app.routers.consult import router as consult_router
import io, zipfile, os

app = FastAPI(title="SKV Network", version="2.0")

@app.on_event("startup")
async def on_startup():
    await startup()


@app.middleware("http")
async def rate_limit_handler(request: Request, call_next):
    return await rate_limit_middleware(request, call_next)

app.include_router(pages_router)
app.include_router(entries_router)
app.include_router(trials_router)
app.include_router(queue_router)
app.include_router(auth_router)
app.include_router(consult_router)

@app.get("/api/v1/info")
async def api_info():
    return {"service": "SKV Network", "version": "2.0", "status": "running", "cubes_count": get_cubes_count()}

@app.get("/.well-known/skv")
async def discovery():
    return {
        "service": "SKV Network", "version": "2.0",
        "description": "Public library of rules and experience for AI agents.",
        "documentation": "https://skv.network/about",
        "core_endpoints": {
            "discovery": "/.well-known/skv", "search": "/api/cubes/search",
            "get_cube": "/api/v1/entries/{cube_id}", "info": "/api/v1/info", "consult": "/api/consult"
        },
        "usage_flow": ["1. Search cubes", "2. Get full cube", "3. Apply rules", "4. Rate"],
        "auth": {"read": "Public", "write": "API key required"},
        "format": "JSON",
        "contact": "deniz@skv.network"
    }

@app.post("/api/tools/generate")
async def generate_files(request: Request):
    data = await request.json()
    outputs = data.get("outputs", ["pdf"])
    files = []

    if "pdf" in outputs:
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
            buf = io.BytesIO()
            doc = SimpleDocTemplate(buf, pagesize=A4)
            styles = getSampleStyleSheet()
            story = [Paragraph(f"<b>{data.get('title','Report')}</b>", styles["Title"]), Spacer(1, 20)]
            for r in data.get("rules", [])[:20]:
                story.append(Paragraph(f"• {r}", styles["BodyText"]))
            doc.build(story)
            buf.seek(0)
            pdfname = f"{data.get('cube_id','report')}.pdf"
            with open(f"/app/uploads/{pdfname}", "wb") as pf:
                pf.write(buf.read())
            files.append({"type":"pdf","url":f"/download/{pdfname}"})
        except Exception as e:
            files.append({"error":f"PDF: {str(e)[:50]}"})

    if "chart" in outputs:
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            cc = data.get("chart_config", {})
            labels = cc.get("labels", ["A","B","C"])
            values = cc.get("values", [10,20,30])
            plt.figure(figsize=(8,4))
            plt.bar(labels, values, color="#6366f1")
            plt.title(data.get("title","Chart"))
            chartname = f"{data.get('cube_id','chart')}.png"
            plt.savefig(f"/app/uploads/{chartname}", dpi=100, bbox_inches="tight")
            plt.close()
            files.append({"type":"png","url":f"/download/{chartname}"})
        except Exception as e:
            files.append({"error":f"Chart: {str(e)[:50]}"})

    return {"status": "ok", "files": files}

@app.get("/download/{filename}")
async def download_file(filename: str):
    from fastapi.responses import FileResponse
    path = f"/app/uploads/{filename}"
    if os.path.exists(path):
        return FileResponse(path, filename=filename)
    return {"error": "File not found"}

@app.post("/api/v2/entries")
async def create_full_entry(request: Request):
    return {"status": "ok"}

@app.get("/api/qdrant/count")
async def qdrant_count():
    return {"count": 0}

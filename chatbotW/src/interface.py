from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
import shutil
from pathlib import Path
from typing import List

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FILE_PATH = Path(__file__).resolve()
ROOT_DIR = FILE_PATH.parent.parent
PDF_FOLDER = ROOT_DIR / "PDFs"
LOGS_DIR = ROOT_DIR / "logs"
ENV_FILE = ROOT_DIR / ".env"

PDF_FOLDER.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    html_path = FILE_PATH.parent / "index.html"
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/apikey")
async def guardar_api_key(key: str = Form(...)):
    try:
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.write(f"GOOGLE_API_KEY={key}")
        return {"status": "success", "message": "API Key guardada en .env"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/pdfs")
async def listar_pdfs():
    archivos = [f.name for f in PDF_FOLDER.glob("*.pdf")]
    return {"pdfs": archivos}

@app.post("/api/pdfs")
async def subir_pdfs(files: List[UploadFile] = File(...)):
    for file in files:
        file_location = PDF_FOLDER / file.filename
        with open(file_location, "wb+") as file_object:
            shutil.copyfileobj(file.file, file_object)
    return {"status": "success", "message": "Archivos subidos correctamente"}

@app.delete("/api/pdfs/{filename}")
async def eliminar_pdf(filename: str):
    ruta = PDF_FOLDER / filename
    if ruta.exists():
        os.remove(ruta)
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Archivo no encontrado")

@app.get("/api/pdfs/{filename}")
async def descargar_pdf(filename: str):
    ruta = PDF_FOLDER / filename
    if not ruta.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(ruta, filename=filename, media_type='application/pdf')

@app.get("/api/logs")
async def listar_logs():
    archivos = [f.name for f in LOGS_DIR.glob("*.txt") if not f.name.startswith("temp_")]
    return {"logs": archivos}

@app.get("/api/logs/{filename}")
async def leer_log(filename: str):
    ruta = LOGS_DIR / filename
    if not ruta.exists():
        raise HTTPException(status_code=404, detail="Log no encontrado")
    try:
        temp_log = LOGS_DIR / f"temp_v_{filename}"
        shutil.copy2(ruta, temp_log)
        with open(temp_log, "r", encoding="utf-8", errors="ignore") as f:
            contenido = f.read()
        os.remove(temp_log)
        return {"contenido": contenido}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
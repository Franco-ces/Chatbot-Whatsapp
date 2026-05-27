from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import set_key
import uvicorn
import os
import shutil
from pathlib import Path
from typing import List
from jose import jwt, JWTError
from datetime import datetime, timedelta
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from fastapi.responses import JSONResponse
import secrets

# Importamos tu clase ConfigManager (asegurate de que ConfigManager.py esté en la misma carpeta)
from ConfigManager import ConfigManager

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

# ─── Auth Configuration ────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_urlsafe(32)
    os.environ["SECRET_KEY"] = SECRET_KEY
    set_key(str(ENV_FILE), "SECRET_KEY", SECRET_KEY)

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")

EXCLUDED_PATHS = {"/api/auth/login", "/api/auth/verify", "/"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Skip excluded paths and non-API paths
        if path in EXCLUDED_PATHS or not path.startswith("/api/"):
            return await call_next(request)

        auth = request.headers.get("Authorization")
        if not auth or not auth.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

        token = auth.split(" ", 1)[1]
        try:
            jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        except JWTError:
            return JSONResponse(status_code=401, content={"detail": "Invalid or expired token"})

        return await call_next(request)


app.add_middleware(AuthMiddleware)
# ────────────────────────────────────────────────────────────────────────

# Instanciamos el manager de configuración
config_manager = ConfigManager()

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    html_path = FILE_PATH.parent / "index.html"
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/apikey")
async def guardar_api_key(key: str = Form(...)):
    try:
        # 1. dotenv se encarga de actualizar el archivo físico de forma segura
        # Preserva todas las demás variables existentes.
        dotenv.set_key(str(ENV_FILE), "GOOGLE_API_KEY", key)
        
        # 2. ACTUALIZACIÓN EN VIVO (Hot-Reload)
        # Seteamos la variable en la memoria del proceso actual para que el bot
        # la lea de inmediato en la próxima consulta sin tener que reiniciar.
        os.environ["GOOGLE_API_KEY"] = key
        
        return {"status": "success", "message": "API Key guardada y actualizada en vivo"}
        
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- NUEVOS ENDPOINTS PARA EL MANAGER DE CONFIGURACIÓN ---
@app.get("/api/config")
async def obtener_config():
    config_manager.cargar() # Nos aseguramos de tener la versión más reciente del disco
    return config_manager.config

@app.post("/api/config")
async def guardar_config(email: str = Form(None), telefono: str = Form(None)):
    try:
        config_manager.guardar(nuevo_email=email, nuevo_tel=telefono)
        return {"status": "success", "message": "✅ Datos de contacto actualizados"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
# ---------------------------------------------------------

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

# ─── Auth Endpoints ────────────────────────────────────────────────────
@app.post("/api/auth/login")
async def login(username: str = Form(...), password: str = Form(...)):
    if username != ADMIN_USER or password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    exp = datetime.utcnow() + timedelta(hours=24)
    token = jwt.encode(
        {"sub": username, "exp": exp},
        SECRET_KEY,
        algorithm="HS256",
    )
    return {"token": token}


@app.get("/api/auth/verify")
async def verify_token(request: Request):
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return {"valid": False}

    token = auth.split(" ", 1)[1]
    try:
        jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return {"valid": True}
    except JWTError:
        return {"valid": False}
# ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)

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
import csv

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
CSV_FOLDER = ROOT_DIR / "CSVs"
CSV_FOLDER.mkdir(parents=True, exist_ok=True)

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
async def guardar_config(email: str = Form(None), telefono: str = Form(None), bot_phone: str = Form(None)):
    try:
        config_manager.guardar(nuevo_email=email, nuevo_tel=telefono, nuevo_bot_phone=bot_phone)
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

# ─── CSV CRUD Endpoints ────────────────────────────────────────────────
@app.get("/api/csvs")
async def listar_csvs():
    archivos = [f.name for f in CSV_FOLDER.glob("*.csv")]
    return {"csvs": archivos}

@app.post("/api/csvs")
async def subir_csvs(files: List[UploadFile] = File(...)):
    for file in files:
        if not file.filename.lower().endswith(".csv"):
            raise HTTPException(
                status_code=422,
                detail=f"'{file.filename}' no es un archivo CSV. Solo se permiten archivos .csv"
            )
        file_location = CSV_FOLDER / file.filename
        with open(file_location, "wb+") as file_object:
            shutil.copyfileobj(file.file, file_object)
    return {"status": "success", "message": "Archivos subidos correctamente"}

@app.delete("/api/csvs/{filename}")
async def eliminar_csv(filename: str):
    ruta = CSV_FOLDER / filename
    if ruta.exists():
        os.remove(ruta)
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Archivo no encontrado")

@app.get("/api/csvs/{filename}")
async def descargar_csv(filename: str):
    ruta = CSV_FOLDER / filename
    if not ruta.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(ruta, filename=filename, media_type='text/csv')

@app.get("/api/csvs/{filename}/data")
async def leer_csv_data(filename: str):
    ruta = CSV_FOLDER / filename
    if not ruta.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = [[row[h] for h in headers] for row in reader]
        return {"headers": headers, "rows": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/csvs/{filename}/data")
async def escribir_csv_data(filename: str, data: dict):
    if not filename.endswith(".csv"):
        raise HTTPException(status_code=422, detail="El archivo debe tener extensión .csv")

    headers = data.get("headers")
    rows = data.get("rows")

    if not headers or not rows:
        raise HTTPException(status_code=400, detail="headers y rows no pueden estar vacíos")

    ruta = CSV_FOLDER / filename
    if not ruta.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    # Validate column count matches headers
    num_cols = len(headers)
    for i, row in enumerate(rows):
        if len(row) != num_cols:
            raise HTTPException(
                status_code=422,
                detail=f"La fila {i+1} tiene {len(row)} columnas, se esperaban {num_cols}"
            )

    # Backup original before write
    backup_path = CSV_FOLDER / f"{filename}.bak"
    shutil.copy2(ruta, backup_path)

    try:
        with open(ruta, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
        return {"status": "success", "message": "CSV actualizado correctamente"}
    except Exception as e:
        # Restore backup on write failure
        shutil.copy2(backup_path, ruta)
        raise HTTPException(status_code=500, detail=f"Error al escribir CSV: {str(e)}")
# ────────────────────────────────────────────────────────────────────────

@app.get("/api/logs")
async def listar_logs():
    archivos = [f.name for f in LOGS_DIR.glob("*.txt") if not f.name.startswith("temp_")]
    return {"logs": archivos}

@app.get("/api/logs/{filename}/phones")
async def obtener_phones_log(filename: str):
    """Extrae números de teléfono únicos (display_name) de un archivo de log."""
    ruta = LOGS_DIR / filename
    if not ruta.exists():
        raise HTTPException(status_code=404, detail="Log no encontrado")
    try:
        temp_log = LOGS_DIR / f"temp_v_{filename}"
        shutil.copy2(ruta, temp_log)
        phones = set()
        with open(temp_log, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.split("|||")
                if len(parts) >= 2 and parts[0].strip() == "id_usuario":
                    display_name = parts[1].strip()
                    if display_name:
                        phones.add(display_name)
        os.remove(temp_log)
        return {"phones": sorted(list(phones))}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/logs/{filename}")
async def leer_log(filename: str, phone: str = None):
    ruta = LOGS_DIR / filename
    if not ruta.exists():
        raise HTTPException(status_code=404, detail="Log no encontrado")
    try:
        temp_log = LOGS_DIR / f"temp_v_{filename}"
        shutil.copy2(ruta, temp_log)
        with open(temp_log, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        os.remove(temp_log)

        if phone:
            # Filtrar líneas donde display_name contenga el valor phone
            # e incluir líneas adyacentes de bot
            filtered = []
            for i, line in enumerate(lines):
                parts = line.split("|||")
                if len(parts) >= 2 and phone in parts[1]:
                    filtered.append(line)
                    # Incluir la siguiente línea si es del bot
                    if i + 1 < len(lines) and "id_bot" in lines[i + 1]:
                        filtered.append(lines[i + 1])
            contenido = "".join(filtered)
        else:
            contenido = "".join(lines)

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

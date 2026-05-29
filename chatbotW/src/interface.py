from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
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

from ConfigManager import ConfigManager
from error_handler import register_error_handlers
from error_codes import ErrorCode
from exceptions import APIError

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

FILE_PATH = Path(__file__).resolve()
ROOT_DIR = FILE_PATH.parent.parent
PDF_FOLDER = ROOT_DIR / "PDFs"
LOGS_DIR = ROOT_DIR / "logs"
ENV_FILE = ROOT_DIR / ".env"
STATIC_DIR = FILE_PATH.parent / "static"

PDF_FOLDER.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
CSV_FOLDER = ROOT_DIR / "CSVs"
CSV_FOLDER.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

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
        set_key(str(ENV_FILE), "GOOGLE_API_KEY", key)
        os.environ["GOOGLE_API_KEY"] = key
        return {"status": "success", "message": "API Key guardada y actualizada en vivo"}
    except Exception as e:
        raise APIError(ErrorCode.CFG_WRITE_FAILED, detail=str(e))

# --- NUEVOS ENDPOINTS PARA EL MANAGER DE CONFIGURACIÓN ---
@app.get("/api/config")
async def obtener_config():
    config_manager.cargar() # Nos aseguramos de tener la versión más reciente del disco
    return config_manager.config

@app.post("/api/config")
async def guardar_config(email: str = Form(None), telefono: str = Form(None), bot_phone: str = Form(None)):
    try:
        config_manager.guardar(nuevo_email=email, nuevo_tel=telefono, nuevo_bot_phone=bot_phone)
        return {"status": "success", "message": "Datos de contacto actualizados"}
    except Exception as e:
        raise APIError(ErrorCode.CFG_WRITE_FAILED, detail=str(e))
# ---------------------------------------------------------

@app.get("/api/pdfs")
async def listar_pdfs():
    archivos = [f.name for f in PDF_FOLDER.glob("*.pdf")]
    return {"pdfs": archivos}

@app.post("/api/pdfs")
async def subir_pdfs(files: List[UploadFile] = File(...)):
    for file in files:
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=422,
                detail=f"'{file.filename}' no es un archivo PDF. Solo se permiten archivos .pdf"
            )
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
    raise APIError(ErrorCode.API_NOT_FOUND, detail="Archivo no encontrado")

@app.get("/api/pdfs/{filename}")
async def descargar_pdf(filename: str):
    ruta = PDF_FOLDER / filename
    if not ruta.exists():
        raise APIError(ErrorCode.API_NOT_FOUND, detail="Archivo no encontrado")
    return FileResponse(ruta, filename=filename, media_type='application/pdf')

# ─── CSV CRUD Endpoints ────────────────────────────────────────────────
@app.get("/api/csvs")
async def listar_csvs():
    archivos = [f.name for f in CSV_FOLDER.glob("*.csv")]
    return {"csvs": archivos}

@app.post("/api/csvs")
async def subir_csvs(files: List[UploadFile] = File(...)):
    import subprocess
    for file in files:
        if not file.filename.lower().endswith(".csv"):
            raise HTTPException(
                status_code=422,
                detail=f"'{file.filename}' no es válido. Solo se permiten archivos .csv"
            )
        file_location = CSV_FOLDER / file.filename
        
        # Guardar archivo original si existe para hacer rollback
        backup_path = None
        if file_location.exists():
            backup_path = CSV_FOLDER / f"{file.filename}.bak"
            shutil.copy2(file_location, backup_path)
            
        with open(file_location, "wb+") as file_object:
            shutil.copyfileobj(file.file, file_object)
            
        # Correr la validación con verificar_datos.py
        result = subprocess.run(
            ["python", str(ROOT_DIR / "src" / "verificar_datos.py")],
            capture_output=True, text=True
        )
        
        if result.returncode != 0:
            # Si falla, borrar el archivo malo y restaurar backup si había
            os.remove(file_location)
            if backup_path:
                shutil.move(backup_path, file_location)
                
            error_msg = result.stdout.strip()
            # Limpiar ANSI codes por las dudas y devolver mensaje claro
            raise HTTPException(
                status_code=422,
                detail=f"Error en {file.filename}:\n{error_msg}"
            )
            
        # Si fue exitoso y había backup, borrar el backup
        if backup_path and backup_path.exists():
            os.remove(backup_path)
            
    return {"status": "success", "message": "Archivos subidos y validados correctamente"}

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

@app.get("/api/logs/search")
async def buscar_logs(q: str = ""):
    """Busca archivos de log por nombre de contacto o número de teléfono en el identificador."""
    if not q:
        return {"results": []}

    q_lower = q.lower().strip()
    resultados = []

    for f in LOGS_DIR.glob("chat_*.txt"):
        try:
            contact_name = None

            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    parts = line.split("|||")
                    # Solo miramos el campo identificador (parts[1]) de líneas de usuario
                    if len(parts) >= 2 and parts[0].strip() == "id_usuario":
                        identificador = parts[1].strip()
                        if contact_name is None:
                            contact_name = identificador
                        if q_lower in identificador.lower():
                            resultados.append({
                                "filename": f.name,
                                "contact_name": identificador,
                            })
                            break
        except Exception:
            continue

    return {"results": resultados}

@app.get("/api/logs/{filename}")
async def leer_log(filename: str):
    ruta = LOGS_DIR / filename
    if not ruta.exists():
        raise APIError(ErrorCode.API_NOT_FOUND, detail="Log no encontrado")
    try:
        temp_log = LOGS_DIR / f"temp_v_{filename}"
        shutil.copy2(ruta, temp_log)
        with open(temp_log, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        os.remove(temp_log)

        return {"contenido": "".join(lines)}
    except Exception as e:
        raise APIError(ErrorCode.API_SERVER_ERROR, detail=str(e))

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

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

import uvicorn
import os
import shutil
from pathlib import Path
from typing import List, Any
from jose import jwt, JWTError
from datetime import datetime, timedelta, time, date
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from fastapi.responses import JSONResponse
import secrets
import csv
import json
import re
import uuid
from pydantic import BaseModel, Field

from ConfigManager import ConfigManager
from error_handler import register_error_handlers
from error_codes import ErrorCode
from exceptions import APIError, AppError, CommunicationError
from evolution_models import ConnectionState
from faq_paths import FAQS_PATH
from logging_config import get_logger
from evo_client import build_evolution_admin
import telemetry
from prompts import TONOS_DISPONIBLES

logger = get_logger("interface")


@asynccontextmanager
async def _telemetry_lifespan(app: FastAPI):
    """Initialize telemetry pool on startup, close on shutdown."""
    await telemetry.init_pool()
    yield
    await telemetry.close_pool()


app = FastAPI(lifespan=_telemetry_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

# Importar rutas centralizadas que funcionan tanto en desarrollo como en ejecutables
from paths import BASE_PATH, PDF_FOLDER, LOGS_DIR, CSV_FOLDER, ENV_FILE, STATIC_DIR, FAQS_FILE

# Los directorios ya se crean en paths.py, pero aseguramos que FAQS_FILE existe
PDF_FOLDER.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
CSV_FOLDER.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
FAQS_FILE.parent.mkdir(parents=True, exist_ok=True)

# FAQS_FILE viene de `faq_paths` (resolución centralizada)
# Aquí para compatibilidad con código existente
ROOT_DIR = BASE_PATH

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _write_env(key: str, value: str) -> None:
    """Escribe una variable en .env sin usar os.replace() (falla en WSL2 bind-mounts).

    Reemplaza la línea existente o agrega al final. Preserve comentarios,
    formato y el resto del archivo intacto.
    """
    import re
    env_path = str(ENV_FILE)
    with open(env_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = rf"^{re.escape(key)}=.*$"
    replacement = f"{key}={value}"
    if re.search(pattern, content, flags=re.MULTILINE):
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    else:
        if not content.endswith("\n"):
            content += "\n"
        content += f"{replacement}\n"

    with open(env_path, "w", encoding="utf-8") as f:
        f.write(content)




# ─── Auth Configuration ────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_urlsafe(32)
    os.environ["SECRET_KEY"] = SECRET_KEY
    try:
        _write_env("SECRET_KEY", SECRET_KEY)
    except OSError:
        pass  # Bind-mount (Docker/WSL2) no permite escribir

# Auto-generar WEBHOOK_SECRET si no está seteado (misma lógica que SECRET_KEY)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
if not WEBHOOK_SECRET:
    WEBHOOK_SECRET = secrets.token_hex(32)
    os.environ["WEBHOOK_SECRET"] = WEBHOOK_SECRET
    try:
        _write_env("WEBHOOK_SECRET", WEBHOOK_SECRET)
    except OSError:
        pass  # Bind-mount (Docker/WSL2) no permite escribir

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")

EXCLUDED_PATHS = {"/api/auth/login", "/api/auth/verify", "/", "/api/reload-rag",
                  "/api/reportes/tipos", "/api/reportes/generar"}


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


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    """Fuerza `Cache-Control: no-store` en `/` y `/static/*`.

    Sin esto, `StaticFiles` y el response del index.html salen sin
    header de cache, y el browser decide solo (suele cachear en
    `disk cache` hasta cerrar la pestaña). Resultado: un cambio en
    `instances.js` o `index.html` deployado al contenedor NO se ve
    hasta hard refresh (Ctrl+Shift+R), que es exactamente el modo de
    falla que nos costo 10 minutos hoy con el fix de
    `connectionStatus`.

    `no-store` (no `no-cache`) porque no queremos revalidacion: el
    browser SIEMPRE va al server. Costo: ~30KB extra de trafico en
    cada refresh. Para una SPA de admin con 4 paginas, irrelevante.

    Solo se aplica a paths publicos (`/`, `/static/*`). Las rutas
    `/api/*` mantienen su semantica de cache default (y de hecho
    varias usan Authorization, que los browsers no cachean igual).
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response


# Orden: en Starlette, el middleware registrado ULTIMO es el mas
# externo (se ejecuta primero en la request, ultimo en la response).
# Ponemos NoCacheStatic afuera de Auth para que el cache header se
# aplique incluso en las responses de assets cuando el usuario
# todavia no esta autenticado (que es el caso normal: la pagina de
# login carga el JS y CSS antes de mandar credenciales).
app.add_middleware(AuthMiddleware)
app.add_middleware(NoCacheStaticMiddleware)
# ────────────────────────────────────────────────────────────────────────

# Instanciamos el manager de configuración
config_manager = ConfigManager()

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    html_path = STATIC_DIR.parent / "index.html"  # STATIC_DIR es src/static, parent es src
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/apikey")
async def guardar_api_key(key: str = Form(...)):
    try:
        os.environ["GOOGLE_API_KEY"] = key
        try:
            _write_env("GOOGLE_API_KEY", key)
        except OSError:
            pass  # Bind-mount (Docker/WSL2) no permite escribir
        # Persistir en volumen compartido para que el bot lea la key
        try:
            config_dir = os.path.dirname(os.environ.get("CONFIG_BOT_PATH", ""))
            if config_dir:
                api_key_path = os.path.join(config_dir, "google_api_key.txt")
                with open(api_key_path, "w") as f:
                    f.write(key)
        except (OSError, ValueError):
            pass
        return {"status": "success", "message": "API Key guardada y actualizada en vivo"}
    except Exception as e:
        raise APIError(ErrorCode.CFG_WRITE_FAILED, detail=str(e))


@app.post("/api/evolution-apikey")
async def guardar_evolution_api_key(key: str = Form(...)):
    """Guarda la API key de Evolution en .env y en memoria.

    No reinicia el contenedor — el operador debe hacerlo manualmente
    con `docker compose up -d evolution-api`.
    """
    try:
        os.environ["EVO_API_KEY"] = key
        _write_env("EVO_API_KEY", key)
    except OSError as e:
        raise APIError(ErrorCode.CFG_WRITE_FAILED, detail=str(e))
    return {
        "status": "success",
        "message": "API key guardada. Reiniciá el contenedor evolution-api para aplicar los cambios.",
    }


# --- NUEVOS ENDPOINTS PARA EL MANAGER DE CONFIGURACIÓN ---
@app.get("/api/config")
async def obtener_config():
    config_manager.cargar() # Nos aseguramos de tener la versión más reciente del disco
    return {
        **config_manager.config,
        "google_api_key_set": bool(os.environ.get("GOOGLE_API_KEY", "")),
        "evolution_api_key_set": bool(
            os.environ.get("EVO_API_KEY", "")
            or os.environ.get("EVOLUTION_API_KEY", "")
        ),
    }

@app.post("/api/config")
async def guardar_config(
    email: str = Form(None),
    telefono: str = Form(None),
    gemini_model: str = Form(None),
    gemini_embeddings_model: str = Form(None),
    bot_tone: str = Form(None),
):
    try:
        # Validar gemini_model si se provee
        if gemini_model is not None:
            gemini_model = gemini_model.strip()
            if not gemini_model:
                raise APIError(
                    ErrorCode.API_INVALID_PAYLOAD,
                    detail="gemini_model no puede estar vacío",
                )
            if not re.match(r"^[A-Za-z0-9/.\-]+$", gemini_model):
                raise APIError(
                    ErrorCode.API_INVALID_PAYLOAD,
                    detail="gemini_model contiene caracteres inválidos",
                )
            config_manager.config["gemini_model"] = gemini_model

        # Validar gemini_embeddings_model si se provee
        if gemini_embeddings_model is not None:
            gemini_embeddings_model = gemini_embeddings_model.strip()
            if not gemini_embeddings_model:
                raise APIError(
                    ErrorCode.API_INVALID_PAYLOAD,
                    detail="gemini_embeddings_model no puede estar vacío",
                )
            if not re.match(r"^[A-Za-z0-9/.\-]+$", gemini_embeddings_model):
                raise APIError(
                    ErrorCode.API_INVALID_PAYLOAD,
                    detail="gemini_embeddings_model contiene caracteres inválidos",
                )
            config_manager.config["gemini_embeddings_model"] = gemini_embeddings_model

        if bot_tone is not None:
            if bot_tone not in TONOS_DISPONIBLES:
                raise APIError(
                    ErrorCode.API_INVALID_PAYLOAD,
                    detail=f"bot_tone debe ser uno de: {', '.join(TONOS_DISPONIBLES.keys())}",
                )

        config_manager.guardar(nuevo_email=email, nuevo_tel=telefono, nuevo_tono=bot_tone)
        return {"status": "success", "message": "Datos de configuración actualizados"}
    except APIError:
        raise
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

# ─── FAQ CRUD Endpoints ────────────────────────────────────────────────
def _read_faqs() -> list:
    """Lee las FAQs del disco. Si el archivo no existe, devuelve []."""
    if not FAQS_PATH.exists():
        return []
    try:
        with open(FAQS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            logger.warning("faqs.json malformado: no es una lista", detail=str(type(data)))
            return []
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Error leyendo faqs.json", detail=str(e))
        return []


def _write_faqs(rows: list) -> None:
    """Escribe las FAQs atómicamente: temp + os.replace."""
    tmp_path = FAQS_PATH.with_suffix(".json.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, FAQS_PATH)
    except OSError as e:
        # Si quedó un temp colgado, intentar limpiarlo.
        if tmp_path.exists():
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise APIError(ErrorCode.FAQ_WRITE_FAILED, detail=str(e))


def _validate_faq_fields(pregunta: str | None, respuesta: str | None) -> tuple[str, str]:
    """Valida pregunta/respuesta: no vacías (post-strip) y máx 500 chars."""
    if pregunta is None or respuesta is None:
        raise APIError(
            ErrorCode.FAQ_INVALID_DATA,
            detail="Los campos pregunta y respuesta son obligatorios.",
        )
    p = pregunta.strip()
    r = respuesta.strip()
    if not p or not r:
        raise APIError(
            ErrorCode.FAQ_INVALID_DATA,
            detail="Los campos pregunta y respuesta no pueden estar vacíos.",
        )
    if len(p) > 500 or len(r) > 500:
        raise APIError(
            ErrorCode.FAQ_INVALID_DATA,
            detail="Los campos pregunta y respuesta no pueden superar los 500 caracteres.",
        )
    return p, r


@app.get("/api/faqs")
async def listar_faqs():
    """Devuelve la lista completa de FAQs."""
    return _read_faqs()


@app.post("/api/faqs")
async def crear_faq(data: dict):
    """Crea una nueva fila de FAQ. Genera id con uuid4."""
    pregunta, respuesta = _validate_faq_fields(data.get("pregunta"), data.get("respuesta"))
    rows = _read_faqs()
    new_row = {
        "id": str(uuid.uuid4()),
        "pregunta": pregunta,
        "respuesta": respuesta,
    }
    rows.append(new_row)
    _write_faqs(rows)
    return JSONResponse(status_code=201, content=new_row)


@app.put("/api/faqs/{faq_id}")
async def actualizar_faq(faq_id: str, data: dict):
    """Reemplaza la fila con ese id. 404 si no existe."""
    pregunta, respuesta = _validate_faq_fields(data.get("pregunta"), data.get("respuesta"))
    rows = _read_faqs()
    for i, row in enumerate(rows):
        if row.get("id") == faq_id:
            rows[i] = {
                "id": faq_id,
                "pregunta": pregunta,
                "respuesta": respuesta,
            }
            _write_faqs(rows)
            return rows[i]
    raise APIError(
        ErrorCode.FAQ_NOT_FOUND,
        detail=f"No existe una FAQ con id '{faq_id}'.",
    )


@app.delete("/api/faqs/{faq_id}")
async def eliminar_faq(faq_id: str):
    """Elimina la fila con ese id. 204 si OK, 404 si no existe."""
    rows = _read_faqs()
    new_rows = [r for r in rows if r.get("id") != faq_id]
    if len(new_rows) == len(rows):
        raise APIError(
            ErrorCode.FAQ_NOT_FOUND,
            detail=f"No existe una FAQ con id '{faq_id}'.",
        )
    _write_faqs(new_rows)
    return Response(status_code=204)
# ────────────────────────────────────────────────────────────────────────

# ─── RAG Reload Endpoint (CSV Hot-Reload safety valve) ─────────────────
# Reference to the shared RAG instance. Set by main.py after creation.
# When running as separate process (interface on port 8000), this stays None
# and the endpoint returns a no-op response. The bot handles reload
# automatically per-query via bot_service.py.
_rag_instance = None


def set_rag_instance(rag):
    """Set the shared RAG instance for manual reload endpoint."""
    global _rag_instance
    _rag_instance = rag


@app.post("/api/reload-rag")
async def reload_rag():
    """Manual RAG reload trigger for admin safety valve.

    Calls actualizar_memoria() on the shared RAG instance if available.
    When running in a separate process, returns no_changes since the bot
    handles hot-reload automatically per-query.
    """
    if _rag_instance is None:
        return {"status": "no_changes", "detail": "RAG instance not available in this process"}

    try:
        updated = await _rag_instance.actualizar_memoria()
        if updated:
            return {"status": "reloaded"}
        return {"status": "no_changes"}
    except Exception as e:
        logger.error("Manual RAG reload failed", detail=str(e))
        raise APIError(ErrorCode.RAG_QUERY_FAILED, detail=str(e))
# ────────────────────────────────────────────────────────────────────────

# ─── Evolution Instance Admin (PR 4) ───────────────────────────────────
# Cliente de Evolution construido una sola vez a partir de las env vars
# del bot. Si falta la key (caso de tests sin .env), la construimos igual
# con string vacio: los tests mockean los métodos del admin, asi que la
# URL/key reales no se tocan nunca en esos flujos.
#
# Importante: usamos `evo_client.build_evolution_admin` en vez de
# importar `evolution_admin` / `evolution_http` directamente. Asi
# `interface.py` no cuenta como cross-importer de ConfigManager +
# evolution_admin (el boundary test verifica que solo `instance_activation`
# cruce ese limite).
evolution_admin = build_evolution_admin()


class InstanceNameRequest(BaseModel):
    """Validacion del nombre de instancia: 1-64 chars, alfanumerico + _ -.

    Coincide con la regex del design (§API Contract) y con la convencion
    de Evolution API v2 para `instanceName`. FastAPI + Pydantic v2
    devuelven 400 via `validation_error_handler` cuando esto falla.
    """

    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


def _validate_instance_name(name: str) -> str:
    """Re-valida el nombre cuando viene como path param (FastAPI no corre
    la regex de Pydantic sobre path params automaticamente)."""
    try:
        return InstanceNameRequest(name=name).name
    except Exception:
        # Re-emitimos como APIError(API_INVALID_PAYLOAD) para mantener el
        # mismo cuerpo de error que el resto del panel.
        raise APIError(
            ErrorCode.API_INVALID_PAYLOAD,
            detail=f"Nombre de instancia inválido: '{name}'",
        )


def _qr_data_url(base64_value: str) -> str:
    """Envuelve el base64 en `data:image/png;base64,...` para que el
    frontend lo use directo en `<img src=...>` sin otra transformacion."""
    if not base64_value:
        return ""
    if base64_value.startswith("data:"):
        return base64_value
    return f"data:image/png;base64,{base64_value}"


@app.get("/api/evolution/instances")
async def list_evolution_instances():
    """Lista todas las instancias registradas en Evolution.

    La UI las renderiza en una tabla y permite crear/nombrar nuevas.
    200 con `{instances: [InstanceInfo, ...]}`. Errores de Evolution
    se mapean a 404/400/500 via `EvolutionAdmin._raise_as_api_error`.
    """
    items = await evolution_admin.list_instances()
    return {
        "instances": [i.model_dump(by_alias=True, exclude_none=True) for i in items]
    }


@app.post("/api/evolution/instances", status_code=201)
async def create_evolution_instance(req: InstanceNameRequest):
    """Crea una nueva instancia. 201 con `{name, connectionState, warning?}`.

    Si Evolution devuelve 400 (caso tipico: nombre duplicado), el admin
    lo mapea a APIError(API_INVALID_PAYLOAD). Aca lo re-traducimos a
    409 + `EVO_INSTANCE_ALREADY_EXISTS` para que la UI pueda mostrar
    el mensaje correcto sin tener que parsear la causa.

    Ademas del create, este endpoint configura el webhook de la instancia
    hacia el bot (mismo flujo que la activacion). Sin esto, la instancia
    queda en Evolution pero el bot nunca recibe mensajes hasta que el
    admin pulse "Activar" — un hazard de UX que sufrio el operador.
    Si el set_webhook falla (red, 500, etc.), el create sigue siendo 201
    pero devuelve un `warning` no-bloqueante para que la UI lo muestre.
    Si la instancia arranca en `close` (caso normal, aun sin escanear),
    se agrega un warning pidiendo escanear el QR.
    """
    try:
        info = await evolution_admin.create_instance(req.name)
    except APIError as e:
        if e.code == ErrorCode.API_UNAUTHORIZED:
            raise
        if e.code == ErrorCode.API_INVALID_PAYLOAD:
            # La unica razon valida para que Evolution rechace un create
            # con 400 es "instance already exists" (Evolution v2 no usa 409).
            raise APIError(
                ErrorCode.EVO_INSTANCE_ALREADY_EXISTS,
                detail=f"La instancia '{req.name}' ya existe",
                cause=e.cause,
            ) from e
        raise

    # Setup de webhook. Si falla, NO abortamos: la instancia ya existe
    # en Evolution, revertirla seria peor que dejarla con un warning.
    # El admin puede reintentar via "Activar" mas tarde.
    warnings: list[str] = []
    bot_url = os.environ.get("BOT_URL", "")
    webhook_secret = os.environ.get("WEBHOOK_SECRET", "")
    if bot_url:
        from evolution_models import WebhookConfig
        try:
            await evolution_admin.set_webhook(
                req.name,
                WebhookConfig(
                    url=bot_url,
                    headers={"X-Webhook-Secret": webhook_secret},
                ),
            )
        except Exception as e:  # noqa: BLE001 - queremos degradar, no propagar
            logger.warning(
                "Webhook setup failed during instance create",
                instance_name=req.name,
                error=str(e),
            )
            warnings.append(
                "Instancia creada, pero el webhook no se configuró. "
                "Activá la instancia para que el bot reciba mensajes."
            )
    else:
        # BOT_URL vacio: el bot no esta expuesto. Avisamos para que el
        # operador entienda por que los mensajes no van a llegar.
        logger.warning(
            "BOT_URL not set, skipping webhook setup on create",
            instance_name=req.name,
        )
        warnings.append(
            "Instancia creada, pero BOT_URL no está configurado. "
            "El bot no podrá recibir mensajes hasta definir la URL pública."
        )

    # Hint de UX: instancia recién creada siempre arranca en `close`
    # (aun no escaneada). Sin este hint, el operador asume que 'ya esta'
    # y se come el silencio del bot. El copy refleja el auto-activate
    # del flow create->scan->open: si no hay OTRA activa, la nueva se
    # vincula sola al escanear el QR; si ya hay una, queda esperando
    # que el operador la active a mano.
    from evolution_models import ConnectionState as _CS
    if info.connection_state == _CS.CLOSE:
        warnings.append(
            "Instancia creada. Escaneá el QR. Si no hay otra activa, "
            "esta se vincula sola."
        )

    response = info.model_dump(by_alias=True, exclude_none=True)
    if warnings:
        response["warning"] = " | ".join(warnings)
    return response


@app.get("/api/evolution/instances/{name}/qr")
async def get_evolution_instance_qr(name: str):
    """Devuelve el QR actual y el estado de la instancia.

    La UI polea este endpoint cada 5s mientras la instancia esta en
    estado `close`; deja de pollear al ver `state == "open"`. 404 si
    la instancia no existe (mapeado por `evolution_admin`).
    """
    _validate_instance_name(name)
    payload = await evolution_admin.get_qr(name)
    return {
        "qr": _qr_data_url(payload.base64),
        "state": payload.state.value,
    }


@app.get("/api/evolution/instances/{name}/state")
async def get_evolution_instance_state(name: str):
    """Devuelve `{state: open|close|connecting|unknown}` para la instancia."""
    _validate_instance_name(name)
    state = await evolution_admin.get_state(name)
    return {"state": state.value}


@app.post("/api/evolution/active", status_code=202)
async def activate_evolution_instance(req: InstanceNameRequest):
    """Activa una instancia: re-verifica estado, setea webhook, encola el
    write async de `config_bot.json.active_instance_name`.

    El bot ya se reinicia solo: el `InstanceWatcher` (PR 3) detecta el
    cambio de mtime en <=1s y el siguiente webhook usa la nueva
    instancia. No reinicia el contenedor.

    Devuelve **202 Accepted** con `{status: "accepted", active: name}`.
    La escritura atomica del config corre en background (puede tardar
    hasta ~100s si el bind-mount de WSL2 tiene EBUSY prolongado), asi el
    cliente no espera el write. La parte critica (disable_webhook +
    set_webhook) SI esta cubierta por el `activation_lock` en el bridge,
    asi no quedan dos instancias con webhook activo en Evolution.

    Si la instancia no esta en estado `open` (drift entre lo que mostro
    la UI y lo que ve Evolution al click), devuelve 409 con
    `EVO_INSTANCE_NOT_LINKED`. El bridge hace el re-verify, asi que no
    lo duplicamos aca.
    """
    # Import local: la mayoria de endpoints del archivo no necesitan el
    # bridge. Si el modulo no esta disponible (version pre-PR-2), el
    # endpoint falla con un error claro en vez de romper el import.
    from instance_activation import set_active as bridge_set_active

    bot_url = os.environ.get("BOT_URL", "")
    webhook_secret = os.environ.get("WEBHOOK_SECRET", "")

    await bridge_set_active(
        req.name,
        admin=evolution_admin,
        config=config_manager,
        webhook_url=bot_url,
        webhook_secret=webhook_secret,
    )
    return {"status": "accepted", "active": req.name}


@app.get("/api/evolution/active")
async def get_active_evolution_instance():
    """Devuelve el nombre de la instancia activa.

    Misma logica que el safety check del DELETE:
    1. `config_bot.json.active_instance_name` si esta seteada.
    2. `EVOLUTION_INSTANCE_NAME` de env vars como fallback.

    El frontend lo pide al cargar la lista para saber que botones
    deshabilitar. No es un secret: cualquier operador logueado puede
    ver cual es la activa.
    """
    config_manager.cargar()  # Relee del disco por si el watcher swapeo.
    config_active = config_manager.config.get("active_instance_name", "")
    # LEGACY: env var fallback. Solo usar si config_bot.json no tiene
    # el campo (nunca fue seteado). Si esta seteado en "", significa
    # que alguien desactivó explicitamente — no debemos ignorar eso.
    env_active = os.environ.get("EVOLUTION_INSTANCE_NAME", "")
    if config_active:
        return {"name": config_active}
    # LEGACY: Si config_bot.json no tiene active_instance_name (o es None),
    # usar env var como fallback solo si el campo no existe en config
    # (no si existe y es vacío).
    if "active_instance_name" not in config_manager.config:
        return {"name": env_active}
    return {"name": ""}


@app.post("/api/evolution/instances/{name}/deactivate", status_code=202)
async def deactivate_evolution_instance(name: str):
    """Desactiva una instancia: deshabilita su webhook en Evolution, y si
    era la activa limpia `active_instance_name` en config (async, via
    bridge.deactivate que comparte el `activation_lock` con set_active).

    Devuelve **202 Accepted** con `{status: "accepted", deactivated: name}`.
    La limpieza del config (si corresponde) corre en background; el
    cliente no espera el write.

    404 si la instancia no existe en Evolution.
    """
    from instance_activation import deactivate as bridge_deactivate

    await bridge_deactivate(
        name,
        admin=evolution_admin,
        config=config_manager,
    )
    return {"status": "accepted", "deactivated": name}


@app.delete("/api/evolution/instances/{name}", status_code=204)
async def delete_evolution_instance(name: str):
    """Elimina una instancia de Evolution. 204 si OK.

    Safety check: si la instancia a borrar es la ACTIVA, consulta
    `get_state` primero. Solo rechaza con 409 `EVO_INSTANCE_ACTIVE`
    si el estado es OPEN (conectada). Si la instancia activa está
    CLOSE, CONNECTING o UNKNOWN, permite la eliminación igual.
    Razon: borrar la activa mientras está conectada dejaria al bot
    sin outbound y la `WhatsAppClient` apuntaria a una instancia
    inexistente hasta el proximo swap. La unica forma limpia de
    desactivar la activa conectada es activando OTRA primero.

    Que cuenta como "activa" para este check:
    1. `config_bot.json.active_instance_name` si esta seteada (caso:
       el operador ya hizo swap manual al menos una vez).
    2. `EVOLUTION_INSTANCE_NAME` de env vars como fallback (caso por
       defecto: el operador NUNCA swapeo, el bot usa la del .env).

    Raises:
        APIError(EVO_INSTANCE_ACTIVE, 409): si la instancia activa
            está conectada (state == OPEN).
        APIError(API_NOT_FOUND, 404): si Evolution no la tiene.
        APIError(SYS_DEPENDENCY_MISSING, 503): si no se puede
            contactar a Evolution API para verificar el estado.
        APIError(API_INVALID_PAYLOAD, 400): nombre invalido o
            que ya esta en uso (poco probable en DELETE, pero mapeado).
    """
    _validate_instance_name(name)

    # Safety check contra la activa. Relee el config (puede haber
    # cambiado desde el startup si hubo un swap reciente) y combina
    # con el LEGACY fallback de env var (la activa que el bot estaria
    # usando si NUNCA se swapeo manualmente).
    config_manager.cargar()
    config_active = config_manager.config.get("active_instance_name", "")
    # LEGACY: env var fallback para instancias nunca swapeadas.
    env_active = os.environ.get("EVOLUTION_INSTANCE_NAME", "")
    active = config_active or env_active
    if name == active:
        try:
            state = await evolution_admin.get_state(name)
        except CommunicationError:
            raise APIError(
                ErrorCode.SYS_DEPENDENCY_MISSING,
                detail=(
                    f"No se pudo verificar el estado de '{name}' "
                    "por un error de conexión con Evolution API."
                ),
            )
        except APIError:
            # API_NOT_FOUND (404), API_UNAUTHORIZED (401), etc. — propagar.
            raise

        if state == ConnectionState.OPEN:
            raise APIError(
                ErrorCode.EVO_INSTANCE_ACTIVE,
                detail=(
                    f"La instancia '{name}' es la activa. Activá otra antes "
                    "de eliminarla."
                ),
            )
        # Si no es OPEN (CLOSE/CONNECTING/UNKNOWN), se permite la eliminación.

    try:
        await evolution_admin.delete_instance(name)
    except APIError:
        # Ya viene mapeado (404, 400, 5xx). Solo lo re-emitimos.
        raise

    return Response(status_code=204)
# ────────────────────────────────────────────────────────────────────────

# ─── Telemetry Summary Endpoint ────────────────────────────────────────
@app.get("/api/telemetry/summary")
async def get_telemetry_summary(days: int = 7):
    """Devuelve datos agregados de telemetría para el dashboard de admin.

    Args:
        days: Número de días hacia atrás para la agregación (default 7).

    Returns:
        JSON con estructura TS-2 del spec de telemetría.
    """
    try:
        data = await telemetry.get_summary(telemetry._pool, days=days)
        return {"status": "success", "data": data}
    except AppError:
        raise
    except Exception as e:
        logger.error("Telemetry summary failed", detail=str(e))
        raise AppError(ErrorCode.TELEMETRY_DB_ERROR, detail=str(e))
# ────────────────────────────────────────────────────────────────────────

# ─── Report Engine Endpoints ───────────────────────────────────────────
from report_generator import listar_tipos, generar_reporte


class GenerarReporteRequest(BaseModel):
    tipo: str
    parametros: dict[str, Any] = {}


@app.get("/api/reportes/tipos")
async def reportes_listar_tipos():
    """Lista los tipos de informe disponibles."""
    return {"tipos": listar_tipos()}


# ────────────────────────────────────────────────────────────────────────

# ─── Scheduled Report Endpoints ────────────────────────────────────────

def _serialize_schedule(row: dict) -> dict:
    """Convierte tipos de PostgreSQL a JSON-serializable.
    time → "HH:MM", date/timestamptz → ISO string."""
    result = {}
    for k, v in row.items():
        if isinstance(v, time):
            result[k] = v.strftime("%H:%M")
        elif isinstance(v, (datetime, date)):
            result[k] = v.isoformat()
        elif isinstance(v, date):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result

@app.get("/api/reportes/schedules")
async def listar_schedules():
    """Lista todos los schedules ordenados por hora_envio."""
    pool = telemetry._pool
    if not pool:
        raise AppError(ErrorCode.TELEMETRY_DB_ERROR, detail="Base de datos no disponible")

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM telemetry.report_schedules ORDER BY hora_envio ASC"
            )
        return [_serialize_schedule(dict(r)) for r in rows]
    except Exception as e:
        logger.error("Error listing schedules", detail=str(e))
        raise AppError(ErrorCode.TELEMETRY_DB_ERROR, detail=str(e))


class ScheduleCreateRequest(BaseModel):
    tipo: str
    parametros: dict[str, Any] = {}
    hora_envio: str  # HH:MM format
    destino: str
    header_text: str | None = None
    footer_text: str | None = None


@app.post("/api/reportes/schedules", status_code=201)
async def crear_schedule(req: ScheduleCreateRequest):
    """Crea un nuevo schedule de informe programado."""
    pool = telemetry._pool
    if not pool:
        raise AppError(ErrorCode.TELEMETRY_DB_ERROR, detail="Base de datos no disponible")

    # Validate tipo against registered report types
    tipos = listar_tipos()
    valid_ids = {t["id"] for t in tipos}
    if req.tipo not in valid_ids:
        raise AppError(ErrorCode.API_INVALID_PAYLOAD, detail=f"Tipo de reporte no válido: '{req.tipo}'")

    # Validate required parametros for this tipo
    tipo_info = next(t for t in tipos if t["id"] == req.tipo)
    for p in tipo_info.get("parametros", []):
        if p.get("requerido", True) and p["key"] not in req.parametros:
            raise AppError(
                ErrorCode.API_INVALID_PAYLOAD,
                detail=f"Parámetro requerido para '{req.tipo}': {p['key']}"
            )

    # Validate hora_envio format (HH:MM)
    import re
    if not re.match(r"^\d{2}:\d{2}$", req.hora_envio):
        raise AppError(ErrorCode.API_INVALID_PAYLOAD, detail="Formato de hora inválido. Use HH:MM")

    # Convert string "HH:MM" to datetime.time for asyncpg
    horas, minutos = map(int, req.hora_envio.split(":"))
    hora_obj = time(horas, minutos)

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO telemetry.report_schedules (tipo, parametros, hora_envio, destino, header_text, footer_text)
                   VALUES ($1, $2, $3, $4, $5, $6) RETURNING *""",
                req.tipo,
                json.dumps(req.parametros) if isinstance(req.parametros, dict) else req.parametros,
                hora_obj,
                req.destino,
                req.header_text,
                req.footer_text,
            )
        return _serialize_schedule(dict(row))
    except AppError:
        raise
    except Exception as e:
        logger.error("Error creating schedule", detail=str(e))
        raise AppError(ErrorCode.TELEMETRY_DB_ERROR, detail=str(e))


@app.put("/api/reportes/schedules/{schedule_id}")
async def actualizar_schedule(schedule_id: int, req: dict):
    """Actualiza un schedule existente."""
    pool = telemetry._pool
    if not pool:
        raise AppError(ErrorCode.TELEMETRY_DB_ERROR, detail="Base de datos no disponible")

    # Validate tipo if provided
    if "tipo" in req:
        tipos = listar_tipos()
        valid_ids = {t["id"] for t in tipos}
        if req["tipo"] not in valid_ids:
            raise AppError(ErrorCode.API_INVALID_PAYLOAD, detail=f"Tipo de reporte no válido: '{req['tipo']}'")

    # Validate hora_envio format if provided
    if "hora_envio" in req:
        if not re.match(r"^\d{2}:\d{2}$", str(req["hora_envio"])):
            raise AppError(ErrorCode.API_INVALID_PAYLOAD, detail="Formato de hora inválido. Use HH:MM")
        # Convert to time object for asyncpg
        horas, minutos = map(int, req["hora_envio"].split(":"))
        req["hora_envio"] = time(horas, minutos)

    # Build dynamic UPDATE
    allowed_fields = {"tipo", "parametros", "hora_envio", "destino", "header_text", "footer_text", "activo"}
    updates = {k: v for k, v in req.items() if k in allowed_fields}
    if not updates:
        raise AppError(ErrorCode.API_INVALID_PAYLOAD, detail="No hay campos para actualizar")

    # Convert parametros to JSON string if it's a dict
    if "parametros" in updates and isinstance(updates["parametros"], dict):
        updates["parametros"] = json.dumps(updates["parametros"])

    set_clauses = []
    values = []
    idx = 1
    for key, val in updates.items():
        if key == "parametros":
            set_clauses.append(f"{key} = ${idx}::jsonb")
        else:
            set_clauses.append(f"{key} = ${idx}")
        values.append(val)
        idx += 1

    set_clauses.append("updated_at = NOW()")
    values.append(schedule_id)

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""UPDATE telemetry.report_schedules SET {', '.join(set_clauses)}
                WHERE id = ${idx} RETURNING *""",
                *values
            )
        if not row:
            raise AppError(ErrorCode.API_NOT_FOUND, detail=f"Schedule {schedule_id} no encontrado")
        return _serialize_schedule(dict(row))
    except AppError:
        raise
    except Exception as e:
        logger.error("Error updating schedule", detail=str(e))
        raise AppError(ErrorCode.TELEMETRY_DB_ERROR, detail=str(e))


@app.delete("/api/reportes/schedules/{schedule_id}")
async def eliminar_schedule(schedule_id: int):
    """Elimina un schedule permanentemente."""
    pool = telemetry._pool
    if not pool:
        raise AppError(ErrorCode.TELEMETRY_DB_ERROR, detail="Base de datos no disponible")

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "DELETE FROM telemetry.report_schedules WHERE id = $1 RETURNING id",
                schedule_id,
            )
        if not row:
            raise AppError(ErrorCode.API_NOT_FOUND, detail=f"Schedule {schedule_id} no encontrado")
        return {"message": "Schedule eliminado"}
    except AppError:
        raise
    except Exception as e:
        logger.error("Error deleting schedule", detail=str(e))
        raise AppError(ErrorCode.TELEMETRY_DB_ERROR, detail=str(e))


@app.post("/api/reportes/schedules/{schedule_id}/toggle")
async def toggle_schedule(schedule_id: int):
    """Activa o desactiva un schedule (toggle activo)."""
    pool = telemetry._pool
    if not pool:
        raise AppError(ErrorCode.TELEMETRY_DB_ERROR, detail="Base de datos no disponible")

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE telemetry.report_schedules
                   SET activo = NOT activo, updated_at = NOW()
                   WHERE id = $1 RETURNING *""",
                schedule_id,
            )
        if not row:
            raise AppError(ErrorCode.API_NOT_FOUND, detail=f"Schedule {schedule_id} no encontrado")
        return _serialize_schedule(dict(row))
    except AppError:
        raise
    except Exception as e:
        logger.error("Error toggling schedule", detail=str(e))
        raise AppError(ErrorCode.TELEMETRY_DB_ERROR, detail=str(e))


# ────────────────────────────────────────────────────────────────────────────

@app.post("/api/reportes/generar")
async def reportes_generar(req: GenerarReporteRequest):
    """Genera un PDF y lo devuelve como descarga."""
    pool = telemetry._pool
    if not pool:
        raise AppError(ErrorCode.TELEMETRY_DB_ERROR, detail="Base de datos no disponible")

    try:
        pdf_bytes = await generar_reporte(req.tipo, pool, req.parametros)
    except ValueError as e:
        # Map validation errors to appropriate API errors
        msg = str(e)
        if "no encontrado" in msg:
            raise AppError(ErrorCode.API_NOT_FOUND, detail=msg)
        raise AppError(ErrorCode.API_INVALID_PAYLOAD, detail=msg)
    except Exception as e:
        logger.error("Report generation failed", detail=str(e))
        raise AppError(ErrorCode.TELEMETRY_DB_ERROR, detail=str(e))

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="reporte_{req.tipo}.pdf"'},
    )
# ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)

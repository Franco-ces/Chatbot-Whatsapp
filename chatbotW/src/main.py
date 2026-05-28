# src/main.py
import asyncio
import os
import sys
import uuid
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import time
from collections import defaultdict

from logging_config import setup_logging, get_logger, request_id_ctx
from rag_langchain_con_audio import RAGLangchain
from whatsapp_client import WhatsAppClient
from payload_parser import EvolutionWebhook, extraer_datos_limpios
from bot_service import procesar_mensaje_bot
from error_handler import register_error_handlers
from error_codes import ErrorCode
from exceptions import AppError
from sesionLoggerManager import SessionManager
from health import run_health_probes

rag = None
wa_client = None
session_manager = None
logger = None

# ---- CONFIGURACIÓN DE RATE LIMITING ----
MAX_MENSAJES = 5        # Máximo de mensajes permitidos
TIEMPO_VENTANA = 60     # En un rango de X segundos

# Diccionario en memoria para rastrear los mensajes por usuario
# Formato: { "numero": [timestamp1, timestamp2, ...] }
historial_mensajes = defaultdict(list)

# ---- DEDUPLICACIÓN DE WEBHOOKS ----
# Evolution API reenvía el webhook si no recibe 200 a tiempo.
# Rastreamos los IDs de mensaje procesados para evitar respuestas duplicadas.
# Formato: { "message_id": timestamp }
mensajes_procesados: dict[str, float] = {}
PROCESADOS_TTL = 300  # 5 minutos


def usuario_excedido(remitente: str) -> bool:
    """Verifica si el usuario excedió el límite de mensajes por frecuencia."""
    ahora = time.time()
    historial_mensajes[remitente] = [t for t in historial_mensajes[remitente] if ahora - t < TIEMPO_VENTANA]

    if len(historial_mensajes[remitente]) >= MAX_MENSAJES:
        return True

    historial_mensajes[remitente].append(ahora)
    return False


async def cleanup_loop():
    """Limpia sesiones expiradas y IDs de mensajes viejos cada 60 segundos."""
    global session_manager
    while True:
        await asyncio.sleep(60)
        if session_manager:
            session_manager.limpiar_sesiones_expiradas()

        # Limpiar IDs de mensajes procesados viejos
        ahora = time.time()
        for msg_id in list(mensajes_procesados.keys()):
            if ahora - mensajes_procesados[msg_id] > PROCESADOS_TTL:
                del mensajes_procesados[msg_id]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global rag, wa_client, session_manager, logger
    setup_logging()
    logger = get_logger("main")

    logger.info("Iniciando dependencias pesadas (RAG, FAISS)...")

    load_dotenv()

    google_key = os.getenv("GOOGLE_API_KEY")
    evolution_key = os.getenv("EVOLUTION_API_KEY")
    evolution_url = os.getenv("EVOLUTION_API_URL")
    instance = os.getenv("EVOLUTION_INSTANCE_NAME")

    try:
        if not google_key or not evolution_key or not evolution_url or not instance:
            logger.error("Faltan variables de entorno requeridas", error_code=ErrorCode.SYS_DEPENDENCY_MISSING.value)
            sys.exit(1)

        wa_client = WhatsAppClient(
            api_url=evolution_url,
            api_key=evolution_key,
            instance_name=instance
        )

        rag = RAGLangchain(google_key)
    except Exception as e:
        logger.error("Fallo al inicializar RAG", error_code=ErrorCode.SYS_DEPENDENCY_MISSING.value, detail=str(e))
        logger.warning("El bot arrancará SIN RAG. Las consultas a PDFs no estarán disponibles.")
        rag = None

    # Inicializamos el SessionManager (logger con buffer + timeout)
    session_manager = SessionManager(timeout_seconds=300, max_mensajes=6)

    # Arrancamos el loop de limpieza de sesiones expiradas
    task = asyncio.create_task(cleanup_loop())

    logger.info("Dependencias cargadas. Servidor listo para recibir mensajes.")
    yield

    # Shutdown: cancelamos el loop y finalizamos sesiones activas
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    if session_manager:
        session_manager.limpiar_sesiones_expiradas()

    logger.info("Apagando servidor y liberando recursos...")


app = FastAPI(title="Gemini WhatsApp Bot", lifespan=lifespan)

register_error_handlers(app)


# ---- ASGI MIDDLEWARE: Request Logging ----
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Auto-log every HTTP request with method, path, status, duration, request_id."""
    rid = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    token = request_id_ctx.set(rid)

    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.error("Request failed", method=request.method, path=request.url.path, duration_ms=duration_ms, status_code=500)
        raise
    finally:
        request_id_ctx.reset(token)

    duration_ms = int((time.perf_counter() - start) * 1000)
    status = response.status_code

    log_data = {"method": request.method, "path": request.url.path, "status_code": status, "duration_ms": duration_ms}

    if status >= 500:
        logger.error("Request completed", **log_data)
    elif status >= 400:
        logger.warning("Request completed", **log_data)
    else:
        logger.info("Request completed", **log_data)

    response.headers["X-Request-ID"] = rid
    return response


# ---- HEALTH ENDPOINT ----
@app.get("/health")
async def health_check():
    """Deep health check probing RAG and Evolution API."""
    result = await run_health_probes(wa_client, rag)
    return JSONResponse(content=result, status_code=200)


@app.post("/webhook")
async def webhook(payload: EvolutionWebhook):
    global session_manager

    datos = extraer_datos_limpios(payload)

    if datos:
        remitente = datos["remitente"]
        push_name = datos["push_name"]

        # Deduplicación: ignorar si ya procesamos este mensaje
        msg_id = payload.data.key.id
        if msg_id in mensajes_procesados:
            logger.info("Mensaje duplicado ignorado", message_id=msg_id)
            return {"status": "duplicate"}
        mensajes_procesados[msg_id] = time.time()

        # Validar Rate Limit por usuario
        if usuario_excedido(remitente):
            logger.warning("Rate limit exceeded", user=push_name or remitente)
            await wa_client.enviar_mensaje(remitente, "Estás enviando mensajes muy rápido. Por favor, espera un minuto.")
            return {"status": "rate_limited"}

        asyncio.create_task(
            procesar_mensaje_bot(
                rag_instance=rag,
                wa_client=wa_client,
                remitente=remitente,
                texto=datos["texto"],
                mensaje_data=datos["mensaje_data"],
                es_audio=datos["es_audio"],
                session_manager=session_manager,
                push_name=push_name,
            )
        )

    return {"status": "ok"}

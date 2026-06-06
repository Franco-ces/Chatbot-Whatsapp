# src/main.py
"""
Servidor Principal de la API del Chatbot (FastAPI).

Este módulo actúa como el punto de entrada del sistema y gestiona la infraestructura 
de red y el ciclo de vida de las dependencias. Implementa las siguientes capacidades:

1. Gestión de Lifespan: Inicialización asíncrona de dependencias pesadas (FAISS, RAG) 
   y limpieza de recursos al apagar el servidor.
2. Modelo de Concurrencia: Utiliza tareas asíncronas (asyncio.create_task) para procesar 
   webhooks sin bloquear la respuesta al servidor de Evolution API, evitando re-envíos.
3. Background Workers: Implementa loops de limpieza automática para sesiones expiradas 
   y un watcher para el hot-reload de la API Key de Google sin reiniciar el proceso.
4. Seguridad y Robustez: Middleware de logging con Request-ID, verificación de secretos 
   vía HMAC y Rate Limiting basado en ventanas de tiempo por usuario.
"""
import asyncio
import hmac
import os
import sys
import uuid
from dotenv import load_dotenv, set_key
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import time
from collections import defaultdict

from logging_config import setup_logging, get_logger, request_id_ctx
from rag_orchestrator import RAGOrchestrator
from whatsapp_client import WhatsAppClient
from payload_parser import EvolutionWebhook, extraer_datos_limpios
from bot_service import procesar_mensaje_bot
from error_handler import register_error_handlers
from error_codes import ErrorCode
from exceptions import AppError
from sesionLoggerManager import SessionManager
from health import run_health_probes
from instance_watcher import InstanceWatcher
from paths import CONFIG_FILE, ENV_FILE

rag = None
wa_client = None
instance_watcher = None
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

# ---- FILTRO DE ANTIGÜEDAD ----
# Ignorar mensajes con más de X segundos de antigüedad (evita procesar
# mensajes encolados cuando el bot estaba caído).
MENSAJE_MAX_ANTIGUEDAD = 300  # 5 minutos


def usuario_excedido(remitente: str) -> bool:
    """Verifica si el usuario excedió el límite de mensajes por frecuencia."""
    ahora = time.time()
    historial_mensajes[remitente] = [t for t in historial_mensajes[remitente] if ahora - t < TIEMPO_VENTANA]

    if len(historial_mensajes[remitente]) >= MAX_MENSAJES:
        return True

    historial_mensajes[remitente].append(ahora)
    return False


def _resolve_instance_name() -> str:
    """Resuelve el nombre de instancia activa para un request saliente.

    Prioridad:
    1) `instance_watcher.get_active_name()` — el nombre actualizado
       por el watcher despues de un swap. Una vez que el admin
       activo una instancia, este valor es el que manda.
    2) `os.environ["EVOLUTION_INSTANCE_NAME"]` — fallback pre-activacion
       (config vacio, primer deploy). El env var queda hasta que
       alguien use la UI/CLI para activar formalmente.

    Devuelve "" si ambos estan vacios — el caller debe decidir si
    eso es error o no (los call sites outbound actualmented no
    pueden funcionar sin nombre, asi que un string vacio se
    propagara como URL malformada; es preferible a un fallback
    silencioso que mande el mensaje a una instancia que no
    esperabamos).
    """
    if instance_watcher is not None:
        name = instance_watcher.get_active_name()
        if name:
            return name
    return os.environ.get("EVOLUTION_INSTANCE_NAME", "")


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
    global rag, wa_client, instance_watcher, session_manager, logger
    setup_logging()
    logger = get_logger("main")

    logger.info("Iniciando dependencias pesadas (RAG, FAISS)...")

    load_dotenv()

    # Generar WEBHOOK_SECRET si no está en .env
    import secrets as _secrets
    webhook_secret = os.getenv("WEBHOOK_SECRET", "")
    if not webhook_secret:
        webhook_secret = _secrets.token_hex(32)
        os.environ["WEBHOOK_SECRET"] = webhook_secret
        try:
            set_key(str(ENV_FILE), "WEBHOOK_SECRET", webhook_secret)
        except OSError:
            pass  # Bind-mount (Docker/WSL2) no permite os.replace

    google_key = os.getenv("GOOGLE_API_KEY")

    # Si GOOGLE_API_KEY no está en env, intentar leer del volumen compartido
    if not google_key:
        try:
            config_dir = os.path.dirname(os.environ.get("CONFIG_BOT_PATH", ""))
            api_key_file = os.path.join(config_dir, "google_api_key.txt") if config_dir else ""
            if api_key_file and os.path.exists(api_key_file):
                with open(api_key_file, "r") as f:
                    google_key = f.read().strip()
                if google_key:
                    os.environ["GOOGLE_API_KEY"] = google_key
        except (OSError, ValueError):
            pass
    evolution_key = os.getenv("EVOLUTION_API_KEY")
    evolution_url = os.getenv("EVOLUTION_API_URL")
    instance = os.getenv("EVOLUTION_INSTANCE_NAME")

    try:
        if not evolution_key or not evolution_url or not instance:
            logger.error("Faltan variables de entorno requeridas", error_code=ErrorCode.SYS_DEPENDENCY_MISSING.value)
            sys.exit(1)

        # Post-PR-3: wa_client es generico (no instance_name en ctor).
        # El nombre llega per-call via _resolve_instance_name().
        wa_client = WhatsAppClient(
            api_url=evolution_url,
            api_key=evolution_key,
        )

        if google_key:
            rag = RAGOrchestrator(google_key)
        else:
            logger.warning("GOOGLE_API_KEY no configurada. El bot arrancará SIN RAG. Cargala desde el panel admin.")
            rag = None
    except Exception as e:
        logger.error("Fallo al inicializar RAG", error_code=ErrorCode.SYS_DEPENDENCY_MISSING.value, detail=str(e))
        logger.warning("El bot arrancará SIN RAG. Las consultas a PDFs no estarán disponibles.")
        rag = None

    # Inicializamos el SessionManager (logger con buffer + timeout)
    session_manager = SessionManager(timeout_seconds=300, max_mensajes=6)

    # Post-PR-3: el InstanceWatcher polea config_bot.json y mantiene
    # _active_name actualizado. main.py consulta get_active_name() por
    # request (no por arranque), asi un swap hecho por la UI se ve
    # en el siguiente webhook sin reiniciar.
    instance_watcher = InstanceWatcher(CONFIG_FILE)
    await instance_watcher.start()
    initial_name = instance_watcher.get_active_name() or instance
    logger.info("InstanceWatcher inicializado", active_instance_name=initial_name)

    # Arrancamos el loop de limpieza de sesiones expiradas
    task = asyncio.create_task(cleanup_loop())

    # Watcher para detectar GOOGLE_API_KEY desde el volumen compartido
    _api_key_last_mtime = [0.0]

    async def _watch_api_key():
        """Polea google_api_key.txt en config_data cada 5s para hot-reload."""
        while True:
            await asyncio.sleep(5)
            try:
                config_dir = os.path.dirname(os.environ.get("CONFIG_BOT_PATH", ""))
                api_key_file = os.path.join(config_dir, "google_api_key.txt") if config_dir else ""
                if api_key_file and os.path.exists(api_key_file):
                    mtime = os.path.getmtime(api_key_file)
                    if mtime > _api_key_last_mtime[0]:
                        _api_key_last_mtime[0] = mtime
                        with open(api_key_file, "r") as f:
                            key = f.read().strip()
                        if key and key != os.getenv("GOOGLE_API_KEY"):
                            os.environ["GOOGLE_API_KEY"] = key
                            global rag
                            try:
                                rag = RAGOrchestrator(key)
                                logger.info("RAG reinicializado con GOOGLE_API_KEY desde panel admin")
                            except Exception as e:
                                logger.warning("No se pudo reinicializar RAG", detail=str(e))
            except (OSError, ValueError):
                pass

    api_key_task = asyncio.create_task(_watch_api_key())

    logger.info("Dependencias cargadas. Servidor listo para recibir mensajes.")
    yield

    # Shutdown: cancelamos loops y watchers
    api_key_task.cancel()
    try:
        await api_key_task
    except asyncio.CancelledError:
        pass

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    if instance_watcher:
        await instance_watcher.stop()

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
    """Deep health check probing RAG and Evolution API.

    Resuelve el instance_name via el watcher (mismo que los
    webhooks de produccion usan), asi el health probe golpea la
    instancia que el bot realmente esta usando.
    """
    instance_name = _resolve_instance_name()
    result = await run_health_probes(wa_client, rag, instance_name=instance_name)
    return JSONResponse(content=result, status_code=200)


@app.post("/webhook")
async def webhook(request: Request, payload: EvolutionWebhook):
    global session_manager

    # Verificación de secret del webhook (timing-safe)
    webhook_secret = os.environ.get("WEBHOOK_SECRET", "")
    if webhook_secret:
        provided = request.headers.get("X-Webhook-Secret", "")
        if not hmac.compare_digest(provided, webhook_secret):
            logger.warning("Webhook secret inválido")
            raise AppError(ErrorCode.API_UNAUTHORIZED, detail="Secret inválido")

    datos = extraer_datos_limpios(payload)

    if datos:
        remitente = datos["remitente"]
        push_name = datos["push_name"]

        # Resolvemos el instance_name UNA VEZ por webhook (atomic read
        # del watcher, sin re-entrar en el lock). Asi un swap del
        # admin durante este request puede afectar a webhooks
        # concurrentes pero NO a este: el que empezo con A termina
        # con A. Es la semantica del design (in-flight on old reference
        # complete; new requests pick up new name).
        instance_name = payload.instance or _resolve_instance_name()
        if not instance_name:
            # Sin nombre activo, no podemos responder. Loggeamos
            # claramente: en un deploy normal esto no deberia pasar
            # (siempre hay el env var de fallback); si pasa es un
            # bug de configuracion que el admin tiene que arreglar.
            logger.error(
                "No hay instancia activa para outbound",
                error_code=ErrorCode.SYS_DEPENDENCY_MISSING.value,
            )
            return {"status": "no_active_instance"}

        # Deduplicación: ignorar si ya procesamos este mensaje
        msg_id = payload.data.key.id
        if msg_id in mensajes_procesados:
            logger.info("Mensaje duplicado ignorado", message_id=msg_id)
            return {"status": "duplicate"}
        mensajes_procesados[msg_id] = time.time()

        # Ignorar mensajes viejos (encolados cuando el bot estaba caído)
        if payload.data.messageTimestamp:
            antiguedad = time.time() - payload.data.messageTimestamp
            if antiguedad > MENSAJE_MAX_ANTIGUEDAD:
                logger.info("Mensaje viejo ignorado", message_id=msg_id, age_seconds=int(antiguedad))
                return {"status": "stale"}

        # Validar Rate Limit por usuario
        if usuario_excedido(remitente):
            logger.warning("Rate limit exceeded", user=push_name or remitente)
            await wa_client.enviar_mensaje(
                remitente,
                "Estás enviando mensajes muy rápido. Por favor, espera un minuto.",
                instance_name=instance_name,
            )
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
                instance_name=instance_name,
            )
        )

    return {"status": "ok"}

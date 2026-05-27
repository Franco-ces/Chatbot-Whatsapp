# src/main.py
import asyncio
import os
import sys
from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks
from contextlib import asynccontextmanager
import time
from collections import defaultdict

from rag_langchain_con_audio import RAGLangchain
from whatsapp_client import WhatsAppClient
from payload_parser import EvolutionWebhook, extraer_datos_limpios
from bot_service import procesar_mensaje_bot
from error_handler import register_error_handlers
from error_codes import ErrorCode
from exceptions import AppError
from sesionLoggerManager import SessionManager

rag = None
wa_client = None
session_manager = None

# ---- CONFIGURACIÓN DE RATE LIMITING ----
MAX_MENSAJES = 5        # Máximo de mensajes permitidos
TIEMPO_VENTANA = 60     # En un rango de X segundos

# Diccionario en memoria para rastrear los mensajes por usuario
# Formato: { "numero": [timestamp1, timestamp2, ...] }
historial_mensajes = defaultdict(list)


def usuario_excedido(remitente: str) -> bool:
    """Verifica si el usuario excedió el límite de mensajes por frecuencia."""
    ahora = time.time()
    historial_mensajes[remitente] = [t for t in historial_mensajes[remitente] if ahora - t < TIEMPO_VENTANA]

    if len(historial_mensajes[remitente]) >= MAX_MENSAJES:
        return True

    historial_mensajes[remitente].append(ahora)
    return False


async def cleanup_loop():
    """Limpia sesiones expiradas cada 60 segundos mientras el servidor esté activo."""
    global session_manager
    while True:
        await asyncio.sleep(60)
        if session_manager:
            session_manager.limpiar_sesiones_expiradas()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global rag, wa_client, session_manager
    print("Iniciando dependencias pesadas (RAG, FAISS)...")

    load_dotenv()

    google_key = os.getenv("GOOGLE_API_KEY")
    evolution_key = os.getenv("EVOLUTION_API_KEY")
    evolution_url = os.getenv("EVOLUTION_API_URL")
    instance = os.getenv("EVOLUTION_INSTANCE_NAME")

    try:
        if not google_key or not evolution_key or not evolution_url or not instance:
            print(f"[ERROR {ErrorCode.SYS_DEPENDENCY_MISSING.value}] Faltan variables de entorno requeridas")
            sys.exit(1)

        wa_client = WhatsAppClient(
            api_url=evolution_url,
            api_key=evolution_key,
            instance_name=instance
        )

        rag = RAGLangchain(google_key)
    except Exception as e:
        print(f"[ERROR {ErrorCode.SYS_DEPENDENCY_MISSING.value}] Fallo al inicializar RAG: {e}")
        print("[WARN] El bot arrancará SIN RAG. Las consultas a PDFs no estarán disponibles.")
        rag = None

    # Inicializamos el SessionManager (logger con buffer + timeout)
    session_manager = SessionManager(timeout_seconds=300, max_mensajes=6)

    # Arrancamos el loop de limpieza de sesiones expiradas
    task = asyncio.create_task(cleanup_loop())

    print("Dependencias cargadas. Servidor listo para recibir mensajes.")
    yield

    # Shutdown: cancelamos el loop y finalizamos sesiones activas
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    if session_manager:
        session_manager.limpiar_sesiones_expiradas()

    print("Apagando servidor y liberando recursos...")


app = FastAPI(title="Gemini WhatsApp Bot", lifespan=lifespan)

register_error_handlers(app)


@app.post("/webhook")
async def webhook(payload: EvolutionWebhook, background_tasks: BackgroundTasks):
    global session_manager

    datos = extraer_datos_limpios(payload)

    if datos:
        remitente = datos["remitente"]
        push_name = datos["push_name"]

        # Validar Rate Limit por usuario
        if usuario_excedido(remitente):
            print(f"[RATE LIMIT] Usuario {push_name or remitente} ignorado por exceso de mensajes.")
            wa_client.enviar_mensaje(remitente, "Estás enviando mensajes muy rápido. Por favor, espera un minuto.")
            return {"status": "rate_limited"}

        background_tasks.add_task(
            procesar_mensaje_bot,
            rag_instance=rag,
            wa_client=wa_client,
            remitente=remitente,
            texto=datos["texto"],
            mensaje_data=datos["mensaje_data"],
            es_audio=datos["es_audio"],
            session_manager=session_manager,
            push_name=push_name,
        )

    return {"status": "ok"}

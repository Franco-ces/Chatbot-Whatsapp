# src/main.py
import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request, BackgroundTasks
from contextlib import asynccontextmanager
import time
from collections import defaultdict

from rag_langchain_con_audio import RAGLangchain
from whatsapp_client import WhatsAppClient
from payload_parser import EvolutionWebhook, extraer_datos_limpios
from bot_service import procesar_mensaje_bot

# Variables globales para nuestras instancias
rag = None
wa_client = None

# ---- CONFIGURACIÓN DE RATE LIMITING ----
MAX_MENSAJES = 5        # Máximo de mensajes permitidos
TIEMPO_VENTANA = 60     # En un rango de X segundos

# Diccionario en memoria para rastrear los mensajes por usuario
# Formato: { "numero": [timestamp1, timestamp2, ...] }
historial_mensajes = defaultdict(list)

def usuario_excedido(remitente: str) -> bool:
    """Verifica si el usuario excedió el límite de mensajes por frecuencia."""
    ahora = time.time()
    # Limpiamos los timestamps viejos que ya están fuera de la ventana de tiempo
    historial_mensajes[remitente] = [t for t in historial_mensajes[remitente] if ahora - t < TIEMPO_VENTANA]
    
    if len(historial_mensajes[remitente]) >= MAX_MENSAJES:
        return True
        
    # Si no excedió, registramos el nuevo mensaje
    historial_mensajes[remitente].append(ahora)
    return False

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gestor de ciclo de vida. Carga los modelos pesados SOLO cuando la API ya está lista.
    """
    global rag, wa_client
    print("Iniciando dependencias pesadas (RAG, FAISS)...")
    
    load_dotenv()
    
    # Obtenemos TODO desde el .env
    google_key = os.getenv("GOOGLE_API_KEY")
    evolution_key = os.getenv("EVOLUTION_API_KEY")
    evolution_url = os.getenv("EVOLUTION_API_URL")
    instance = os.getenv("EVOLUTION_INSTANCE_NAME")
    
    rag = RAGLangchain(google_key)

    wa_client = WhatsAppClient(
        api_url=evolution_url,
        api_key=evolution_key,
        instance_name=instance
    )
    
    print("Dependencias cargadas. Servidor listo para recibir mensajes.")
    yield
    
    # (Opcional) Acá podrías agregar lógica para cerrar conexiones a bases de datos si el servidor se apaga
    print("Apagando servidor y liberando recursos...")

# Instanciamos FastAPI inyectando el lifespan
app = FastAPI(title="Gemini WhatsApp Bot", lifespan=lifespan)


@app.post("/webhook")
async def webhook(payload: EvolutionWebhook, background_tasks: BackgroundTasks):
    # 'payload' ahora es un objeto validado, no un dict genérico
    datos = extraer_datos_limpios(payload)
    
    if datos:
        remitente = datos["remitente"]
        
        # Validar Rate Limit por usuario
        if usuario_excedido(remitente):
            print(f"[RATE LIMIT] Usuario {remitente} ignorado por exceso de mensajes.")
            wa_client.enviar_mensaje(remitente, "Estás enviando mensajes muy rápido. Por favor, espera un minuto.")
            return {"status": "rate_limited"}

        background_tasks.add_task(
            procesar_mensaje_bot, 
            rag_instance=rag, 
            wa_client=wa_client, 
            remitente=remitente,
            texto=datos["texto"],
            mensaje_data=datos["mensaje_data"],
            es_audio=datos["es_audio"]
        )
    
    return {"status": "ok"}